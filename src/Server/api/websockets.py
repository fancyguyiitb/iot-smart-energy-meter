"""Device WebSocket and remote relay control.

Fixes compared with the original version:
* The device must authenticate (``X-Device-Id`` / ``X-Device-Key`` on the handshake);
  anyone could previously claim to be "random12" and receive its relay commands.
* Rejected handshakes stop there (the old code closed the socket and kept reading it).
* Relay commands require a logged-in owner of the device and are audit-logged.
* The command waits for the device's acknowledgement (see api.services.DeviceHub).
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from api.dependencies import authenticate_device, get_current_user, resolve_user_device
from api.services import DeviceOffline, hub
from config import settings
from utils.database import get_metadata_db
from utils.models import RelayCommand
from utils.sprint import Logger

l = Logger.get_instance(True)
ws_router = APIRouter()


@ws_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    device = await run_in_threadpool(authenticate_device, websocket.headers.get("x-device-id"),
                                     websocket.headers.get("x-device-key"))
    if device is None:
        await websocket.close(code=1008)  # policy violation; sent before accept -> HTTP 403
        return
    device_id = device["device_id"]
    await websocket.accept()
    await hub.register(device_id, websocket)
    try:
        while True:
            text = await websocket.receive_text()
            try:
                message = json.loads(text)
            except ValueError:
                l.eprint(f"{device_id}: ignoring non-JSON frame")
                continue
            if isinstance(message, dict):
                hub.handle_message(device_id, message)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        l.eprint(f"{device_id}: WebSocket error {type(e).__name__}: {e}")
    finally:
        hub.unregister(device_id, websocket)


@ws_router.post("/remote-control")
async def send_command(cmd: RelayCommand, user: dict = Depends(get_current_user)):
    """Switch a phase (or ALL) on/off. Returns the relay state the device confirmed."""
    device_id = await run_in_threadpool(resolve_user_device, user, cmd.device_id)
    db = get_metadata_db()
    try:
        ack = await hub.send_command(device_id, cmd.command, cmd.phase, settings.command_timeout_seconds)
    except DeviceOffline as e:
        await run_in_threadpool(db.log_relay, device_id, user["id"], cmd.phase, cmd.command, False, str(e))
        raise HTTPException(status_code=409, detail="Meter is offline")
    except asyncio.TimeoutError:
        await run_in_threadpool(db.log_relay, device_id, user["id"], cmd.phase, cmd.command, False, "timeout")
        raise HTTPException(status_code=504, detail="Meter did not confirm the command in time")
    await run_in_threadpool(db.log_relay, device_id, user["id"], cmd.phase, cmd.command,
                            bool(ack.get("ok")), ack.get("error"))
    if not ack.get("ok"):
        raise HTTPException(status_code=502, detail=f"Meter refused the command: {ack.get('error')}")
    return {"status": "confirmed", "relays": ack.get("relays")}


@ws_router.get("/remote-control/status")
async def get_status(device_id: str | None = None, refresh: bool = True, user: dict = Depends(get_current_user)):
    """Relay state. With refresh=true (default) asks the device for fresh state first."""
    device_id = await run_in_threadpool(resolve_user_device, user, device_id)
    if refresh and hub.is_online(device_id):
        try:
            await hub.send_command(device_id, "status", None, settings.command_timeout_seconds)
        except (DeviceOffline, asyncio.TimeoutError):
            pass  # fall back to the last reported state
    return hub.status(device_id)


@ws_router.get("/remote-control/history")
def relay_history(device_id: str | None = None, user: dict = Depends(get_current_user)):
    device_id = resolve_user_device(user, device_id)
    return get_metadata_db().relay_history(device_id)
