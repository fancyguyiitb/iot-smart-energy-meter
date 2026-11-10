"""Data API: device ingest + user-facing queries.

Fixes compared with the original version:
* Every route is authenticated: devices with their key, users with a JWT, and users can
  only see meters they own (``device_id`` was a free query parameter).
* ``/fetch-all`` is gone: it returned the whole bucket - including every user's plaintext
  password - to anyone. ``/fetch-analytics`` (read a measurement nothing wrote) too.
* Ingest validates each reading; timestamps are parsed properly instead of falling back
  to ``now()`` (which collapsed each batch onto one timestamp and lost ~90% of the data).
  Invalid rows are reported and skipped instead of failing the whole batch, so one bad
  row can't block the device's sync forever.
* Writes are durable before 201 is returned (see storage.influx_store); storage failures
  return 503 so the device keeps the rows and retries.
* Routes are plain ``def`` so blocking storage calls run in FastAPI's threadpool instead
  of freezing the event loop (and every WebSocket with it).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import ValidationError

from api.dependencies import get_current_device, get_current_user, resolve_user_device
from api.services import hub
from config import settings
from storage import StorageError, get_store
from utils.database import get_metadata_db
from utils.models import READING_FIELDS, Reading
from utils.sprint import Logger

l = Logger.get_instance(True)
router = APIRouter()
TZ = ZoneInfo(settings.timezone)


def day_bounds(date_str: str | None) -> tuple[datetime, datetime]:
    """UTC start/end of a local calendar day (default: today)."""
    try:
        d = date.fromisoformat(date_str) if date_str else datetime.now(TZ).date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    start = datetime.combine(d, time.min, tzinfo=TZ)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def _store_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except StorageError as e:
        l.eprint(f"Storage error: {e}")
        raise HTTPException(status_code=503, detail="Storage temporarily unavailable")


# ---------------------------------------------------------------------- device endpoints
@router.post("/write-data", status_code=201)
def write_data(payload: list[dict] = Body(...), device: dict = Depends(get_current_device)):
    """Batch ingest from a device. Body: a list of readings (see utils.models.Reading)."""
    if not payload:
        raise HTTPException(status_code=400, detail="No data provided.")
    if len(payload) > settings.max_batch_size:
        raise HTTPException(status_code=413, detail=f"Batch too large (max {settings.max_batch_size})")
    readings, rejected = [], []
    for i, item in enumerate(payload):
        try:
            readings.append(Reading.model_validate(item))
        except ValidationError as e:
            rejected.append({"index": i, "error": e.errors(include_url=False, include_input=False)[0]["msg"]})
    if rejected:
        l.eprint(f"{device['device_id']}: rejected {len(rejected)}/{len(payload)} readings, e.g. {rejected[0]}")
    accepted = _store_call(get_store().write_readings, device["device_id"], readings) if readings else 0
    return {"message": "Data written successfully.", "accepted": accepted, "rejected": rejected}


@router.get("/last-energy-data")
def get_last_energy_val(device: dict = Depends(get_current_device)):
    """Latest cumulative energy per phase, used by the device to resume after a restart."""
    return _store_call(get_store().last_energy, device["device_id"])


# ---------------------------------------------------------------------- user endpoints
@router.get("/devices")
def list_devices(user: dict = Depends(get_current_user)):
    return [d | hub.status(d["device_id"]) for d in get_metadata_db().devices_for_user(user["id"])]


@router.get("/latest-values")
def get_latest_values(device_id: str | None = None, user: dict = Depends(get_current_user)):
    """Newest reading per phase (R, Y, B, Neutral) with its age in seconds."""
    device_id = resolve_user_device(user, device_id)
    latest = _store_call(get_store().latest, device_id)
    now = datetime.now(timezone.utc)
    for row in latest.values():
        row["age_s"] = round((now - datetime.fromisoformat(row["timestamp"])).total_seconds(), 1)
    return latest


@router.get("/series")
def get_series(
    fields: str = Query(..., description="Comma-separated, e.g. power_watt,power_var"),
    date_str: str | None = Query(None, description="YYYY-MM-DD (local), default today"),
    phase: str | None = Query(None, pattern="^(R|Y|B|Neutral)$"),
    every: int = Query(60, ge=1, le=86400, description="Average over buckets of this many seconds"),
    device_id: str | None = None,
    user: dict = Depends(get_current_user),
):
    wanted = [f.strip() for f in fields.split(",") if f.strip()]
    unknown = [f for f in wanted if f not in READING_FIELDS]
    if unknown or not wanted:
        raise HTTPException(status_code=400, detail=f"Unknown fields {unknown}; allowed: {list(READING_FIELDS)}")
    device_id = resolve_user_device(user, device_id)
    start, end = day_bounds(date_str)
    return _store_call(get_store().series, device_id, start, end, wanted, phase, every)


@router.get("/query-data")
def query_data(date_str: str | None = None, every: int = Query(60, ge=1, le=86400),
               device_id: str | None = None, user: dict = Depends(get_current_user)):
    """Power, voltage, current and energy for a day, grouped by phase."""
    return get_series("power_watt,voltage_rms,current_rms,energy_kwh", date_str, None, every, device_id, user)


@router.get("/thd-values")
def get_thd_data(date_str: str | None = None, every: int = Query(60, ge=1, le=86400),
                 device_id: str | None = None, user: dict = Depends(get_current_user)):
    """THD, power factor and frequency for a day, grouped by phase."""
    return get_series("voltage_thd,current_thd,power_factor,voltage_freq", date_str, None, every, device_id, user)


@router.get("/health")
def health_check():
    try:
        get_store().ping()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Storage unreachable: {e}")
    return {"message": "connection OK.", "storage": settings.storage_backend}
