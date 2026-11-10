"""Analytics computed on read from the time-series store.

Fixes compared with the original version:
* Energy analytics report *consumption* (sum of positive steps of the cumulative
  counter). The old avg/min/max of a running kWh total had no meaning for a user.
* No more cached "analytics points": they were stamped with the computation time instead
  of the day they described, so a past day's analytics were never found, the past-date
  endpoint wrote a point and then returned 404 anyway, and every "today" request wrote
  another point. These aggregates are cheap enough to compute per request.
* Power min/max come from raw data, not from a downsampled series (which hides peaks).
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from config import settings
from storage import get_store

TZ = ZoneInfo(settings.timezone)


def day_bounds(target_date: date) -> tuple[datetime, datetime]:
    """UTC start/end of a local calendar day."""
    start = datetime.combine(target_date, time.min, tzinfo=TZ)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def tz_offset_s(at: datetime) -> int:
    return int(at.astimezone(TZ).utcoffset().total_seconds())


def power_analytics(target_date: date, phase: str, device_id: str, every_s: int = 60) -> dict:
    start, end = day_bounds(target_date)
    store = get_store()
    s = store.stats(device_id, start, end, "power_watt", phase)
    series = store.series(device_id, start, end, ["power_watt", "power_var", "power_va"], phase, every_s)
    return {
        "analytics_data": {
            "avg_power_watt": s["avg"],
            "max_power_watt": s["max"],
            "min_power_watt": s["min"],
            "samples": s["count"],
        },
        "power_data": series.get(phase, []),
    }


def energy_analytics(target_date: date, phase: str, device_id: str, every_s: int = 300) -> dict:
    start, end = day_bounds(target_date)
    store = get_store()
    hourly = store.energy_buckets(device_id, start, end, 3600, tz_offset_s(start), phase).get(phase, [])
    series = store.series(device_id, start, end, ["energy_kwh"], phase, every_s).get(phase, [])
    consumed = sum(h["kwh"] for h in hourly)
    peak = max(hourly, key=lambda h: h["kwh"], default=None)
    return {
        "analytics_data": {
            "consumed_kwh": consumed,
            "peak_hour": peak["start"] if peak and peak["kwh"] > 0 else None,
            "peak_hour_kwh": peak["kwh"] if peak else 0.0,
            "hourly": hourly,
        },
        "energy_data": series,
    }


def daily_energy(year: int, month: int, device_id: str) -> dict:
    """kWh consumed per local day of a month, per phase."""
    first = date(year, month, 1)
    days = [first + timedelta(days=i) for i in range(calendar.monthrange(year, month)[1])]
    start, _ = day_bounds(days[0])
    _, end = day_bounds(days[-1])
    buckets = get_store().energy_buckets(device_id, start, end, 86400, tz_offset_s(start))
    phases = {}
    for phase in ("R", "Y", "B"):
        by_day = {datetime.fromisoformat(b["start"]).astimezone(TZ).date(): b["kwh"] for b in buckets.get(phase, [])}
        phases[phase] = [round(by_day.get(d, 0.0), 6) for d in days]
    totals = {p: sum(v) for p, v in phases.items()}
    return {"days": [d.isoformat() for d in days], "phases": phases, "total_kwh": totals,
            "month_total_kwh": sum(totals.values())}
