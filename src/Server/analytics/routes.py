from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from analytics.helpers import TZ, daily_energy, energy_analytics, power_analytics
from api.dependencies import get_current_user, resolve_user_device
from storage import StorageError

analysis_router = APIRouter()

DEFAULT_PHASE = "R"


def _date(date_str: str | None) -> date:
    if not date_str:
        return datetime.now(TZ).date()
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")


def _guard(fn, *args):
    try:
        return fn(*args)
    except StorageError:
        raise HTTPException(status_code=503, detail="Storage temporarily unavailable")


@analysis_router.get("/power")
def get_power_analytics(
    date_str: str | None = Query(None, description="Date in YYYY-MM-DD format (default today)"),
    phase: str = Query(DEFAULT_PHASE, pattern="^(R|Y|B)$"),
    device_id: str | None = None,
    every: int = Query(60, ge=1, le=3600),
    user: dict = Depends(get_current_user),
):
    device_id = resolve_user_device(user, device_id)
    data = _guard(power_analytics, _date(date_str), phase, device_id, every)
    if not data["power_data"]:
        raise HTTPException(status_code=404, detail="No power data found for this date.")
    return data


@analysis_router.get("/energy")
def get_energy_analytics(
    date_str: str | None = Query(None, description="Date in YYYY-MM-DD format (default today)"),
    phase: str = Query(DEFAULT_PHASE, pattern="^(R|Y|B)$"),
    device_id: str | None = None,
    user: dict = Depends(get_current_user),
):
    device_id = resolve_user_device(user, device_id)
    return _guard(energy_analytics, _date(date_str), phase, device_id)


@analysis_router.get("/energy-daily")
def get_daily_energy(
    month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$", description="YYYY-MM (default this month)"),
    device_id: str | None = None,
    user: dict = Depends(get_current_user),
):
    device_id = resolve_user_device(user, device_id)
    today = datetime.now(TZ).date()
    year, mon = (int(month[:4]), int(month[5:])) if month else (today.year, today.month)
    if not 1 <= mon <= 12:
        raise HTTPException(status_code=400, detail="Invalid month")
    return _guard(daily_energy, year, mon, device_id)
