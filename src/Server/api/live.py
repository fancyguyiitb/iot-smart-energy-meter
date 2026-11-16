"""Live lane: the newest reading, pushed by the meter every second and fanned out to
browsers over a WebSocket.

Two paths reach the cloud, on purpose:

* **Durable lane** (``/api/write-data``, every 10 s): batched, acknowledged, buffered on
  the meter while offline, idempotent. The source of truth for storage and analytics.
* **Live lane** (this module): best-effort, newest sample only, never stored. If it
  fails nothing is lost - the durable lane still delivers every reading - so it needs
  no retries or buffering, and a backlog never delays what the user sees "now".

Edge cases handled here:
* Out-of-order or replayed pushes (older than what we have) are ignored.
* A meter pushing faster than ``LIVE_MIN_INTERVAL_SECONDS`` is throttled.
* Browsers authenticate in the first message (tokens never go in URLs, which are
  logged), only see meters they own, and are disconnected when their token expires or
  the user logs out everywhere / changes password.
* A slow browser can't slow anyone down: each subscriber has a small queue, and the
  oldest sample is dropped if it's full.
* After a server restart the cache is empty; ``/api/latest-values`` falls back to storage.
  State is per process, like the relay hub (needs a broker for multiple workers).
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError

from api.dependencies import get_current_device
from config import settings
from utils.database import get_metadata_db
from utils.models import READING_FIELDS, Reading
from utils.security import verify_token
from utils.sprint import Logger

l = Logger.get_instance(True)
live_router = APIRouter()
AUTH_TIMEOUT_S = 5
RECHECK_S = 30


class LiveHub:
    def __init__(self) -> None:
        self.latest: dict[str, dict] = {}  # device_id -> {phase: {timestamp, fields}}
        self.received_at: dict[str, float] = {}
        self.subscribers: dict[str, set[asyncio.Queue]] = {}

    def publish(self, device_id: str, readings: list[Reading]) -> bool:
        now = time.monotonic()
        if now - self.received_at.get(device_id, -1e9) < settings.live_min_interval_seconds:
            return False  # throttled
        newest = max(r.time for r in readings)
        current = self.latest.get(device_id)
        if current and newest <= max(datetime.fromisoformat(v["timestamp"]) for v in current.values()):
            return False  # stale or replayed
        self.received_at[device_id] = now
        self.latest[device_id] = {
            r.phase: {"timestamp": r.time.isoformat(timespec="milliseconds"),
                      **{f: getattr(r, f) for f in READING_FIELDS}} for r in readings}
        message = json.dumps({"type": "sample", "phases": self.latest[device_id]})
        for q in self.subscribers.get(device_id, set()):
            if q.full():
                q.get_nowait()  # slow consumer: drop its oldest sample
            q.put_nowait(message)
        return True

    def subscribe(self, device_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=10)
        self.subscribers.setdefault(device_id, set()).add(q)
        return q

    def unsubscribe(self, device_id: str, q: asyncio.Queue) -> None:
        self.subscribers.get(device_id, set()).discard(q)


live_hub = LiveHub()


@live_router.post("/api/live")
async def push_live(payload: list[dict] = Body(...), device: dict = Depends(get_current_device)):
    """Newest sample from a meter (one row per phase + neutral). Best effort; not stored."""
    if not payload or len(payload) > 8:
        raise HTTPException(status_code=400, detail="Send one sample (one row per phase)")
    try:
        readings = [Reading.model_validate(item) for item in payload]
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors(include_url=False, include_input=False)[0]["msg"])
    return {"accepted": live_hub.publish(device["device_id"], readings)}


def _authenticate(token: str, device_id: str | None) -> tuple[dict, str, float]:
    """(user, device_id, token expiry epoch) or raise ValueError."""
    from fastapi import HTTPException as _H

    try:
        payload = verify_token(token)
    except _H as e:
        raise ValueError(e.detail)
    db = get_metadata_db()
    user = db.get_user(int(payload["sub"]))
    if user is None or payload.get("ver", 0) != user["token_version"]:
        raise ValueError("Session ended")
    devices = [d["device_id"] for d in db.devices_for_user(user["id"])]
    if device_id and device_id not in devices:
        raise ValueError("Device not found")
    if not devices:
        raise ValueError("No meter on this account")
    return user, device_id or devices[0], float(payload["exp"])


@live_router.websocket("/ws/live")
async def live_socket(websocket: WebSocket):
    await websocket.accept()
    try:
        first = json.loads(await asyncio.wait_for(websocket.receive_text(), AUTH_TIMEOUT_S))
        user, device_id, exp = await run_in_threadpool(_authenticate, str(first.get("token", "")),
                                                       first.get("device_id"))
    except (asyncio.TimeoutError, ValueError, json.JSONDecodeError, AttributeError) as e:
        await websocket.close(code=4401, reason=str(e)[:100] or "Unauthorised")
        return
    except WebSocketDisconnect:
        return

    q = live_hub.subscribe(device_id)
    try:
        await websocket.send_text(json.dumps({"type": "hello", "device_id": device_id}))
        if device_id in live_hub.latest:
            await websocket.send_text(json.dumps({"type": "sample", "phases": live_hub.latest[device_id]}))
        next_check = time.monotonic() + RECHECK_S
        while True:
            try:
                message = await asyncio.wait_for(q.get(), RECHECK_S)
                await websocket.send_text(message)
            except asyncio.TimeoutError:
                pass
            if time.monotonic() < next_check:
                continue
            next_check = time.monotonic() + RECHECK_S
            # Re-check the session: expiry, password change, log-out-everywhere.
            if time.time() >= exp:
                await websocket.close(code=4401, reason="Token expired")
                return
            current = await run_in_threadpool(get_metadata_db().get_user, user["id"])
            if current is None or current["token_version"] != user["token_version"]:
                await websocket.close(code=4401, reason="Session ended")
                return
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        live_hub.unsubscribe(device_id, q)


def merge_latest(device_id: str, stored: dict[str, dict]) -> dict[str, dict]:
    """Prefer the live sample where it is newer than what storage has."""
    live = live_hub.latest.get(device_id, {})
    merged = dict(stored)
    for phase, row in live.items():
        if phase not in merged or row["timestamp"] > merged[phase]["timestamp"]:
            merged[phase] = dict(row)
    return merged
