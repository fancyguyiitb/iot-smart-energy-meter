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
                event = hub.handle_message(device_id, message)
                if event:  # the meter acted on its own (overcurrent trip, welded relay): audit it
                    l.eprint(f"{device_id}: phase {event['phase']} {event['action']}: {event['reason']}")
                    await run_in_threadpool(get_metadata_db().log_relay, device_id, None, event["phase"],
                                            f"auto:{event['action']}", False, event["reason"])
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
    # Desired state follows what the owner asked for on the phases the meter accepted.
    accepted = [p for p, r in (ack.get("results") or {}).items() if r.get("ok")] or                (([cmd.phase] if cmd.phase != "ALL" else ["R", "Y", "B"]) if ack.get("ok") else [])
    if accepted:
        await run_in_threadpool(db.set_desired, device_id, accepted, cmd.command)
    if not ack.get("ok"):
        # The meter's safety logic said no (interlock) or the switch failed verification
        # (welded contacts). Its message explains why; the app shows it as is.
        raise HTTPException(status_code=409, detail=ack.get("error") or "Meter refused the command")
    unverified = [p for p, r in (ack.get("results") or {}).items() if not r.get("verified", True)]
    return {"status": "confirmed" if not unverified else "applied, not verified",
            "relays": ack.get("relays"), "details": ack.get("details"), "unverified": unverified}


@ws_router.get("/remote-control/status")
async def get_status(device_id: str | None = None, refresh: bool = True, user: dict = Depends(get_current_user)):
    """Relay state. With refresh=true (default) asks the device for fresh state first."""
    device_id = await run_in_threadpool(resolve_user_device, user, device_id)
    if refresh and hub.is_online(device_id):
        try:
            await hub.send_command(device_id, "status", None, settings.command_timeout_seconds)
        except (DeviceOffline, asyncio.TimeoutError):
            pass  # fall back to the last reported state
    status = hub.status(device_id)
    desired = await run_in_threadpool(get_metadata_db().get_desired, device_id)
    status["desired"] = {p: desired.get(p) for p in ("R", "Y", "B")}
    # A mismatch means the meter overrode the owner: overcurrent trip, welded contacts, ...
    status["mismatch"] = {p: bool(desired.get(p) and status["relays"].get(p) and desired[p] != status["relays"][p])
                          for p in ("R", "Y", "B")}
    return status


@ws_router.get("/remote-control/history")
def relay_history(device_id: str | None = None, user: dict = Depends(get_current_user)):
    device_id = resolve_user_device(user, device_id)
    return get_metadata_db().relay_history(device_id)
