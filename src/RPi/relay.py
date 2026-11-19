"""Remote relay control over a persistent, authenticated WebSocket to the server.

The safety logic (closed-loop verification, interlocks, overcurrent trip) lives in
``relay_safety.RelayController``; this module wires it to the GPIOs, the live readings
and the server. The protection loop runs whether or not the server is reachable.

Fixes compared with the original version:
* One GPIO per phase (``RELAY_PINS``); previously R, Y and B all drove GPIO 17.
* Status reports the right phases (the heartbeat used to read "A", "R", "R").
* The connection reconnects with exponential backoff instead of exiting on any error.
* The last commanded state is persisted and restored at boot, so a restart of this
  process never toggles the consumer's supply (``GPIO.setup`` used to drive pins LOW).
* Every command carries an id and is acknowledged with the resulting relay state.
* The device authenticates with its own key (anyone could impersonate "random12").

Protocol (JSON text frames)
  device -> server  {"type": "status", "relays": {"R": "on", ...}, "details": {"R": {reason, lockout_s, welded, ...}}}
  server -> device  {"type": "command", "id": "...", "command": "on"|"off"|"status", "phase": "R"|"Y"|"B"|"ALL"}
  device -> server  {"type": "ack", "id": "...", "ok": bool, "error": str|null, "results": {...}, "relays": {...}, "details": {...}}
  device -> server  {"type": "event", "phase": "Y", "action": "trip"|"welded", "reason": "...", "at": iso}
"""

from __future__ import annotations

import asyncio
import json
import random

import websockets

from config import (
    LIVE_DATA_PATH,
    MAX_SWITCHES_PER_WINDOW,
    MIN_OFF_TIME_S,
    PHASES,
    RELAY_ACTIVE_HIGH,
    RELAY_PINS,
    RELAY_STATE_PATH,
    SUPPLY_MAX_V,
    SUPPLY_MIN_V,
    SWITCH_WINDOW_S,
    TRIP_CURRENT_A,
    TRIP_DELAY_S,
    VERIFY_OFF_CURRENT_A,
    VERIFY_TIMEOUT_S,
    WS_URL,
    device_headers,
    require_identity,
)
from hal import gpio as GPIO
from relay_safety import Limits, RelayController

STATUS_INTERVAL_S = 30
PROTECTION_TICK_S = 0.5
MAX_BACKOFF_S = 60

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)


def _level(on: bool) -> int:
    return GPIO.HIGH if on == RELAY_ACTIVE_HIGH else GPIO.LOW


_pins_ready = False


def set_pin(phase: str, on: bool) -> None:
    if _pins_ready:
        GPIO.output(RELAY_PINS[phase], _level(on))
    else:  # first call at boot: configure the pin straight into its persisted state
        GPIO.setup(RELAY_PINS[phase], GPIO.OUT, initial=_level(on))


def read_live() -> dict | None:
    try:
        return json.loads(LIVE_DATA_PATH.read_text())
    except (OSError, ValueError):
        return None


controller = RelayController(
    PHASES, set_pin, read_live, RELAY_STATE_PATH,
    Limits(min_off_time_s=MIN_OFF_TIME_S, max_switches=MAX_SWITCHES_PER_WINDOW, switch_window_s=SWITCH_WINDOW_S,
           trip_current_a=TRIP_CURRENT_A, trip_delay_s=TRIP_DELAY_S, supply_min_v=SUPPLY_MIN_V,
           supply_max_v=SUPPLY_MAX_V, verify_off_current_a=VERIFY_OFF_CURRENT_A, verify_timeout_s=VERIFY_TIMEOUT_S),
)


def setup_pins() -> None:
    global _pins_ready
    controller.restore_pins()
    _pins_ready = True
    print(f"[INFO]: Relays restored: { {p: s.on for p, s in controller.state.items()} } (pins {RELAY_PINS})")


def gpi_status(phase: str) -> str | None:
    """'on' / 'off' as read back from the pin."""
    phase = phase.strip().upper()
    if phase not in RELAY_PINS:
        return None
    return "on" if (GPIO.input(RELAY_PINS[phase]) == GPIO.HIGH) == RELAY_ACTIVE_HIGH else "off"


def all_status() -> dict[str, str | None]:
    return {p: gpi_status(p) for p in PHASES}


def status_message() -> dict:
    return {"type": "status", "relays": all_status(), "details": controller.details()}


def handle_command(message: dict) -> dict:
    command = str(message.get("command", "")).lower()
    ack = {"type": "ack", "id": message.get("id"), "ok": True, "error": None, "results": {}}
    try:
        if command in {"on", "off"}:
            phase = str(message.get("phase", "")).upper()
            targets = PHASES if phase == "ALL" else (phase,)
            if any(p not in PHASES for p in targets):
                raise ValueError(f"Unknown phase {phase!r}")
            errors = []
            for p in targets:
                result = controller.command(p, command == "on")
                ack["results"][p] = result
                if not result["ok"]:
                    errors.append(result["error"])
            if errors:
                ack.update(ok=False, error=" | ".join(errors))
            print(f"[INFO]: Phase {phase} {command.upper()}: {ack['results']}")
        elif command != "status":
            raise ValueError(f"Unknown command {command!r}")
    except Exception as e:  # report the failure to the app instead of dying
        ack.update(ok=False, error=str(e))
    ack["relays"] = all_status()
    ack["details"] = controller.details()
    return ack


async def protection_loop() -> None:
    """Overcurrent trip and welded-contact detection - runs even with the server down."""
    while True:
        try:
            await asyncio.to_thread(controller.tick)
        except Exception as e:
            print(f"[ERROR]: Protection loop: {e}")
        await asyncio.sleep(PROTECTION_TICK_S)


async def session() -> None:
    async with websockets.connect(WS_URL, additional_headers=device_headers(),
                                  ping_interval=20, ping_timeout=20) as ws:
        print(f"[INFO]: Connected to {WS_URL}")
        await ws.send(json.dumps(await asyncio.to_thread(status_message)))

        async def heartbeat():
            ticks = 0
            while True:
                await asyncio.sleep(1)
                events = controller.take_events()
                try:  # trips / welding found by the protection loop (also while offline)
                    for ev in events:
                        await ws.send(json.dumps({"type": "event", **ev}))
                except Exception:
                    with controller.lock:  # put them back: reported after reconnecting
                        controller.events[:0] = events
                    raise
                ticks += 1
                if events or ticks >= STATUS_INTERVAL_S:
                    ticks = 0
                    await ws.send(json.dumps(await asyncio.to_thread(status_message)))

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


async def main() -> None:
    await asyncio.gather(protection_loop(), websocket_client())


if __name__ == "__main__":
    require_identity()
    setup_pins()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Disconnected by user")
