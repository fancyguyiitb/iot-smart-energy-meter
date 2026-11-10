"""Remote relay control over a persistent, authenticated WebSocket to the server.

Fixes compared with the original version:
* One GPIO per phase (``RELAY_PINS``); previously R, Y and B all drove GPIO 17.
* Status reports the right phases (the heartbeat used to read "A", "R", "R").
* The connection reconnects with exponential backoff instead of exiting on any error.
* The last commanded state is persisted and restored at boot, so a restart of this
  process never toggles the consumer's supply (``GPIO.setup`` used to drive pins LOW).
* Every command carries an id and is acknowledged with the resulting relay state, so
  the app shows confirmed state instead of a guess.
* The device authenticates with its own key (anyone could impersonate "random12").

Protocol (JSON text frames)
  device -> server  {"type": "status", "relays": {"R": "on", "Y": "on", "B": "off"}}
  server -> device  {"type": "command", "id": "...", "command": "on"|"off"|"status", "phase": "R"|"Y"|"B"|"ALL"}
  device -> server  {"type": "ack", "id": "...", "ok": true, "error": null, "relays": {...}}
"""

from __future__ import annotations

import asyncio
import json
import random

import websockets

from config import (
    PHASES,
    RELAY_ACTIVE_HIGH,
    RELAY_PINS,
    RELAY_STATE_PATH,
    WS_URL,
    device_headers,
    require_identity,
)
from fileutil import atomic_write_text
from hal import gpio as GPIO

STATUS_INTERVAL_S = 30
MAX_BACKOFF_S = 60

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)


def _level(on: bool) -> int:
    return GPIO.HIGH if on == RELAY_ACTIVE_HIGH else GPIO.LOW


def load_state() -> dict[str, bool]:
    try:
        saved = json.loads(RELAY_STATE_PATH.read_text())
        return {p: bool(saved.get(p, True)) for p in PHASES}
    except (OSError, ValueError):
        return {p: True for p in PHASES}  # first boot: supply on


def save_state(state: dict[str, bool]) -> None:
    atomic_write_text(RELAY_STATE_PATH, json.dumps(state))


def setup_pins() -> None:
    state = load_state()
    for phase, pin in RELAY_PINS.items():
        GPIO.setup(pin, GPIO.OUT, initial=_level(state[phase]))
    print(f"[INFO]: Relays restored: {state} (pins {RELAY_PINS})")


def gpi_set(phase: str, command: str) -> None:
    """Drive one phase relay ("on"/"off") and persist the new state."""
    phase = phase.strip().upper()
    command = command.strip().lower()
    if phase not in RELAY_PINS:
        raise ValueError(f"Unknown phase {phase!r}")
    if command not in {"on", "off"}:
        raise ValueError(f"Unknown command {command!r}")
    GPIO.output(RELAY_PINS[phase], _level(command == "on"))
    state = load_state()
    state[phase] = command == "on"
    save_state(state)


def gpi_status(phase: str) -> str | None:
    """'on' / 'off' as read back from the pin."""
    phase = phase.strip().upper()
    if phase not in RELAY_PINS:
        return None
    return "on" if (GPIO.input(RELAY_PINS[phase]) == GPIO.HIGH) == RELAY_ACTIVE_HIGH else "off"


def all_status() -> dict[str, str | None]:
    return {p: gpi_status(p) for p in PHASES}


def handle_command(message: dict) -> dict:
    command = str(message.get("command", "")).lower()
    ack = {"type": "ack", "id": message.get("id"), "ok": True, "error": None}
    try:
        if command in {"on", "off"}:
            phase = str(message.get("phase", "")).upper()
            for p in (PHASES if phase == "ALL" else (phase,)):
                gpi_set(p, command)
            print(f"[INFO]: Phase {phase} turned {command.upper()}")
        elif command != "status":
            raise ValueError(f"Unknown command {command!r}")
    except Exception as e:  # report the failure to the app instead of dying
        ack.update(ok=False, error=str(e))
    ack["relays"] = all_status()
    return ack


async def session() -> None:
    async with websockets.connect(WS_URL, additional_headers=device_headers(),
                                  ping_interval=20, ping_timeout=20) as ws:
        print(f"[INFO]: Connected to {WS_URL}")
        await ws.send(json.dumps({"type": "status", "relays": all_status()}))

        async def heartbeat():
            while True:
                await asyncio.sleep(STATUS_INTERVAL_S)
                await ws.send(json.dumps({"type": "status", "relays": all_status()}))

        beat = asyncio.create_task(heartbeat())
        try:
            async for raw in ws:
                try:
                    message = json.loads(raw)
                except ValueError:
                    continue
                if message.get("type") == "command":
                    print(f"[INFO]: Command from server: {message}")
                    reply = await asyncio.to_thread(handle_command, message)
                    await ws.send(json.dumps(reply))
        finally:
            beat.cancel()


async def websocket_client() -> None:
    failures = 0
    while True:
        try:
            await session()
            failures = 0
            print("[INFO]: Server closed the connection; reconnecting")
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            failures += 1
            delay = min(2 ** failures, MAX_BACKOFF_S) * random.uniform(0.8, 1.2)
            print(f"[ERROR]: WebSocket {type(e).__name__}: {e}; reconnecting in {delay:.0f} s")
            await asyncio.sleep(delay)


if __name__ == "__main__":
    require_identity()
    setup_pins()
    try:
        asyncio.run(websocket_client())
    except KeyboardInterrupt:
        print("Disconnected by user")
