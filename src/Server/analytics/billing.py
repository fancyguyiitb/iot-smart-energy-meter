"""Bill forecast against a slab (telescopic) tariff.

Indian residential tariffs charge per unit in slabs: the first 100 units at one rate, the
next 200 at a higher rate, and so on, plus a fixed charge. Crossing a slab boundary makes
every further unit more expensive, so the useful warning is *when* this month's use
will cross the next boundary, and what daily use would avoid it.

Forecast = units so far this billing cycle + expected daily use x days left. Expected
daily use is the average of recent complete days, weighted by day of week when there are
two weeks of history (weekends differ), falling back to today's rate when there is
little history. A confidence level reflects how much history there is.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from pydantic import BaseModel, Field, field_validator

from analytics.helpers import TZ, day_bounds, tz_offset_s
from storage import get_store

PHASES = ("R", "Y", "B")


class Slab(BaseModel):
    upto: float | None = Field(None, gt=0, description="Upper bound in units (kWh); null = no limit")
    rate: float = Field(..., ge=0, le=100, description="Price per unit")


class Tariff(BaseModel):
    name: str = Field("My tariff", max_length=80)
    currency: str = Field("₹", max_length=4)
    fixed_charge: float = Field(0.0, ge=0, le=100000)
    cycle_start_day: int = Field(1, ge=1, le=28)
    slabs: list[Slab] = Field(..., min_length=1, max_length=10)

    @field_validator("slabs")
    @classmethod
    def _ordered(cls, slabs: list[Slab]) -> list[Slab]:
        bounds = [s.upto for s in slabs]
        if any(b is None for b in bounds[:-1]) or bounds[-1] is not None:
            raise ValueError("only the last slab may be unlimited, and it must be")
        if bounds[:-1] != sorted(bounds[:-1]) or len(set(bounds[:-1])) != len(bounds) - 1:
            raise ValueError("slab limits must increase")
        return slabs


DEFAULT_TARIFF = Tariff(
    name="Example slab tariff (edit to match your electricity bill)",
    fixed_charge=50.0,
    slabs=[Slab(upto=100, rate=3.5), Slab(upto=300, rate=5.5), Slab(upto=500, rate=7.5), Slab(upto=None, rate=8.5)],
)


def bill_cost(units: float, tariff: Tariff) -> dict:
    """Telescopic slab cost: each slab's rate applies only to the units inside it."""
    remaining, lower, energy_cost, lines = units, 0.0, 0.0, []
    for s in tariff.slabs:
        width = (s.upto - lower) if s.upto is not None else remaining
        used = max(min(remaining, width), 0.0)
        if used > 0:
            energy_cost += used * s.rate
            lines.append({"from": lower, "to": s.upto, "units": round(used, 2), "rate": s.rate,
                          "cost": round(used * s.rate, 2)})
        remaining -= used
        lower = s.upto if s.upto is not None else lower
        if remaining <= 0:
            break
    return {"units": round(units, 2), "energy_charge": round(energy_cost, 2), "fixed_charge": tariff.fixed_charge,
            "total": round(energy_cost + tariff.fixed_charge, 2), "slabs": lines}


def rate_for(units: float, tariff: Tariff) -> float:
    for s in tariff.slabs:
        if s.upto is None or units < s.upto:
            return s.rate
    return tariff.slabs[-1].rate


def cycle_bounds(today: date, start_day: int) -> tuple[date, date]:
    """[start, end) of the billing cycle containing ``today``."""
    if today.day >= start_day:
        start = today.replace(day=start_day)
    else:
        prev = (today.replace(day=1) - timedelta(days=1))
        start = prev.replace(day=min(start_day, calendar.monthrange(prev.year, prev.month)[1]))
    nxt_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    end = nxt_month.replace(day=min(start_day, calendar.monthrange(nxt_month.year, nxt_month.month)[1]))
    return start, end


def daily_units(device_id: str, start: date, end: date) -> dict[date, float]:
    """kWh per local day (all phases, chip energy) for days in [start, end]."""
    s, _ = day_bounds(start)
    _, e = day_bounds(end)
    buckets = get_store().energy_buckets(device_id, s, e, 86400, tz_offset_s(s))
    out: dict[date, float] = defaultdict(float)
    for p in PHASES:
        for b in buckets.get(p, []):
            out[datetime.fromisoformat(b["start"]).astimezone(TZ).date()] += b["kwh"]
    return out


def forecast(device_id: str, tariff: Tariff, now: datetime | None = None) -> dict:
    now = (now or datetime.now(TZ)).astimezone(TZ)
    today = now.date()
    cycle_start, cycle_end = cycle_bounds(today, tariff.cycle_start_day)
    history = daily_units(device_id, min(cycle_start, today - timedelta(days=28)), today)
    so_far = sum(v for d, v in history.items() if cycle_start <= d <= today)

    full_days = {d: v for d, v in history.items() if d < today}
    recent = sorted(full_days)[-28:]
    day_fraction = (now - datetime.combine(today, time.min, tzinfo=TZ)).total_seconds() / 86400
    if len(recent) >= 14:  # enough to see weekly patterns
        by_dow = defaultdict(list)
        for d in recent:
            by_dow[d.weekday()].append(full_days[d])
        dow_rate = {k: sum(v) / len(v) for k, v in by_dow.items()}
        overall = sum(full_days[d] for d in recent) / len(recent)
        rate_of = lambda d: dow_rate.get(d.weekday(), overall)  # noqa: E731
        confidence = "high"
    elif recent:
        avg = sum(full_days[d] for d in recent) / len(recent)
        rate_of = lambda d: avg  # noqa: E731
        confidence = "medium" if len(recent) >= 7 else "low"
    else:  # only today so far: extrapolate today's pace
        pace = history.get(today, 0.0) / day_fraction if day_fraction > 0.05 else 0.0
        rate_of = lambda d: pace  # noqa: E731
        confidence = "very low"

    # Expected units for the rest of today and each remaining day of the cycle.
    future = [(today, rate_of(today) * (1 - day_fraction))]
    d = today + timedelta(days=1)
    while d < cycle_end:
        future.append((d, rate_of(d)))
        d += timedelta(days=1)
    projected = so_far + sum(u for _, u in future)
    avg_daily = (sum(u for _, u in future) / max(len(future) - 1 + (1 - day_fraction), 1e-9)) if future else 0.0

    # When will each slab boundary between "so far" and "projected" be crossed?
    warnings, running = [], so_far
    boundaries = [s.upto for s in tariff.slabs if s.upto is not None]
    for day, units in future:
        for b in boundaries:
            if running < b <= running + units:
                warnings.append({
                    "boundary_units": b, "expected_date": day.isoformat(),
                    "rate_before": rate_for(b - 0.01, tariff), "rate_after": rate_for(b, tariff),
                    "text": (f"You're on track to cross {b:.0f} units around {day.strftime('%d %b')}. "
                             f"After that each unit costs {tariff.currency}{rate_for(b, tariff):.2f} instead of "
                             f"{tariff.currency}{rate_for(b - 0.01, tariff):.2f}."),
                })
        running += units

    days_left = (cycle_end - today).days - day_fraction
    tip = None
    # Suggest the lowest slab limit that is still realistically avoidable (needs at most a
    # 40 % cut in daily use); "use 1 kWh a day instead of 20" is not advice.
    for b in boundaries:
        if so_far < b < projected and days_left > 0:
            needed = (b - so_far) / days_left
            if needed >= 0.6 * avg_daily:
                cut = (1 - needed / avg_daily) * 100 if avg_daily else 0
                tip = (f"To stay under {b:.0f} units this cycle, keep use below {needed:.1f} kWh per day "
                       f"(currently about {avg_daily:.1f}, a {cut:.0f} % cut). Each unit above {b:.0f} costs "
                       f"{tariff.currency}{rate_for(b, tariff):.2f}.")
                break

    return {
        "tariff": tariff.model_dump(),
        "cycle": {"start": cycle_start.isoformat(), "end": (cycle_end - timedelta(days=1)).isoformat(),
                  "days_left": round(days_left, 1)},
        "so_far": bill_cost(so_far, tariff),
        "projected": bill_cost(projected, tariff),
        "average_daily_kwh": round(avg_daily, 2),
        "confidence": confidence,
        "history_days": len(recent),
        "warnings": warnings,
        "tip": tip,
    }
