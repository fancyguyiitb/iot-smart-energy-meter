"""Live connections to devices (relay control).

Fixes compared with the original in-line dictionaries:
* A reconnecting device replaces its old socket, and the *old* socket's disconnect can no
  longer delete the *new* one (the device used to show "offline" after every reconnect).
* Any error, not just WebSocketDisconnect, removes the socket - no dead sockets left
  behind to make the next command fail with 500.
* Commands carry an id and wait for the device's acknowledgement, so the API returns the
  relay state the device actually reached, instead of "command sent" and a stale cache.

Note: state is in-process. Running several server workers needs a shared broker
(Redis pub/sub or MQTT) - a deliberate next step for the cloud deployment.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field

from fastapi import WebSocket

from utils.sprint import Logger

l = Logger.get_instance(True)


class DeviceOffline(Exception):
    pass


@dataclass
class DeviceConnection:
    websocket: WebSocket
    connected_at: float = field(default_factory=time.time)
    pending: dict[str, asyncio.Future] = field(default_factory=dict)


class DeviceHub:
    def __init__(self) -> None:
        self.connections: dict[str, DeviceConnection] = {}
        self.relays: dict[str, dict] = {}  # last reported relay state, kept while offline
        self.last_seen: dict[str, float] = {}

    async def register(self, device_id: str, websocket: WebSocket) -> None:
        old = self.connections.get(device_id)
        self.connections[device_id] = DeviceConnection(websocket)
        self.last_seen[device_id] = time.time()
        if old is not None:
            self._fail_pending(old, "Device reconnected")
            try:
                await old.websocket.close(code=4000)
            except Exception:
                pass
        l.iprint(f"Device {device_id} connected")

    def unregister(self, device_id: str, websocket: WebSocket) -> None:
        conn = self.connections.get(device_id)
        if conn is not None and conn.websocket is websocket:
            del self.connections[device_id]
            self._fail_pending(conn, "Device disconnected")
            l.iprint(f"Device {device_id} disconnected")

    @staticmethod
    def _fail_pending(conn: DeviceConnection, reason: str) -> None:
        for fut in conn.pending.values():
            if not fut.done():
                fut.set_exception(DeviceOffline(reason))
        conn.pending.clear()

    def handle_message(self, device_id: str, message: dict) -> None:
        self.last_seen[device_id] = time.time()
        relays = message.get("relays")
        if isinstance(relays, dict):
            self.relays[device_id] = {p: relays.get(p) for p in ("R", "Y", "B")}
        if message.get("type") == "ack":
            conn = self.connections.get(device_id)
            fut = conn.pending.pop(str(message.get("id")), None) if conn else None
            if fut is not None and not fut.done():
                fut.set_result(message)

    async def send_command(self, device_id: str, command: str, phase: str | None, timeout: float) -> dict:
        conn = self.connections.get(device_id)
        if conn is None:
            raise DeviceOffline("Device is offline")
        command_id = uuid.uuid4().hex
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        conn.pending[command_id] = fut
        try:
            await conn.websocket.send_text(json.dumps(
                {"type": "command", "id": command_id, "command": command, "phase": phase}))
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            raise
        except DeviceOffline:
            raise
        except Exception as e:  # socket died while sending
            raise DeviceOffline(str(e)) from e
        finally:
            conn.pending.pop(command_id, None)

    def is_online(self, device_id: str) -> bool:
        return device_id in self.connections

    def status(self, device_id: str) -> dict:
        return {
            "device_id": device_id,
            "online": self.is_online(device_id),
            "relays": self.relays.get(device_id, {"R": None, "Y": None, "B": None}),
            "last_seen": self.last_seen.get(device_id),
        }


hub = DeviceHub()
