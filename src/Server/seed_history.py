"""Synthetic history for demos and for testing the insights (balance advisor, bill forecast).

The virtual meter produces real-time data, so after a few minutes there are only a few
minutes of history - not enough for "usually runs 21:00-01:00" or a monthly forecast.
This writes N days of plausible 10-second data for one meter, ending just before its
first real reading, through the normal storage path (so rollups cover it too).

The household is deliberately unbalanced the way real ones often are: both ACs, the
water heater and the TV were wired to phase Y, so the advisor has something real to fix.

    python manage.py seed-history --device-id meter-001 --days 14
"""

from __future__ import annotations

import cmath
import math
import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from config import settings
from storage import get_store
from utils.models import Reading

TZ = ZoneInfo(settings.timezone)
NOMINAL_V = 230.0

# (name, phase, watts, pf, start hour, duration h, days of week (None = daily), probability)
SCHEDULE = [
    ("water heater", "Y", 2000, 1.00, 6.5, 0.75, None, 0.95),
    ("bedroom AC", "Y", 1500, 0.90, 21.0, 4.0, None, 0.90),
    ("living-room AC", "Y", 1200, 0.90, 19.5, 3.5, None, 0.85),
    ("tv", "Y", 150, 0.95, 19.0, 4.0, None, 1.0),
    ("microwave", "Y", 900, 0.95, 13.0, 0.17, None, 0.7),
    ("lights", "R", 120, 0.92, 18.0, 5.5, None, 1.0),
    ("fans", "R", 150, 0.90, 11.0, 13.0, None, 1.0),
    ("washing machine", "B", 500, 0.75, 10.0, 1.0, {5, 6}, 0.9),
    ("chargers", "B", 90, 0.60, 0.0, 24.0, None, 1.0),
]


def _plan(days: int, end: datetime, rng: random.Random) -> list[tuple[str, float, float, float, float]]:
    """Concrete (phase, start_epoch, end_epoch, watts, pf) runs with some day-to-day jitter."""
    runs = []
    first_day = (end - timedelta(days=days)).astimezone(TZ).date()
    for i in range(days + 1):
        day = first_day + timedelta(days=i)
        midnight = datetime(day.year, day.month, day.day, tzinfo=TZ).timestamp()
        for _, phase, watts, pf, hour, dur, dows, prob in SCHEDULE:
            if (dows is not None and day.weekday() not in dows) or rng.random() > prob:
                continue
            start = midnight + (hour + rng.gauss(0, 0.25 if dur < 20 else 0)) * 3600
            length = dur * 3600 * (rng.uniform(0.8, 1.2) if dur < 20 else 1)
            runs.append((phase, start, start + length, watts * rng.uniform(0.95, 1.05), pf))
    return runs


def seed(device_id: str, days: int = 14, step_s: int = 10, seed_value: int = 7) -> int:
    store = get_store()
    # End just before the meter's first real reading (or now): never overwrite real data.
    now = datetime.now(timezone.utc)
    existing = store.series(device_id, now - timedelta(days=400), now, ["power_watt"], "R", None)
    first_real = datetime.fromisoformat(existing["R"][0]["timestamp"]) if existing.get("R") else None
    end = (first_real or now) - timedelta(minutes=5)
    rng = random.Random(seed_value)
    runs = _plan(days, end, rng)
    fridge_period, fridge_on = 25 * 60, 10 * 60

    t = (end - timedelta(days=days)).timestamp()
    t -= t % step_s
    energy = {p: 0.0 for p in "RYB"}
    batch, written = [], 0
    while t < end.timestamp():
        loads = {p: [] for p in "RYB"}
        for phase, a, b, watts, pf in runs:
            if a <= t < b:
                loads[phase].append((watts, pf))
        if (t % fridge_period) < fridge_on:
            loads["R"].append((180.0, 0.82))
        ts = datetime.fromtimestamp(t, timezone.utc)
        phasor = 0j
        for p in "RYB":
            watts = sum(w for w, _ in loads[p]) + 40.0  # standby
            var = sum(w * math.tan(math.acos(pf)) for w, pf in loads[p]) + 25.0
            va = math.hypot(watts, var)
            volts = NOMINAL_V - 0.25 * va / NOMINAL_V + rng.gauss(0, 0.4)
            amps = va / volts
            energy[p] += watts * step_s / 3_600_000
            phasor += cmath.rect(amps, {"R": 0.0, "Y": -2 * math.pi / 3, "B": 2 * math.pi / 3}[p])
            batch.append(Reading(phase=p, time=ts, voltage_rms=volts, current_rms=amps, power_watt=watts,
                                 power_var=var, power_va=va, power_factor=watts / va, voltage_thd=2.0,
                                 current_thd=10.0, voltage_freq=50.0 + rng.gauss(0, 0.02),
                                 energy_kwh=energy[p], energy_sw_kwh=energy[p] * 0.998, export_kwh=0.0))
        batch.append(Reading(phase="Neutral", time=ts, current_rms=abs(phasor)))
        if len(batch) >= 4000:
            written += store.write_readings(device_id, batch)
            batch = []
        t += step_s
    if batch:
        written += store.write_readings(device_id, batch)
    store.run_maintenance()  # roll the new history up straight away
    return written
