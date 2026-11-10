"""Power-failure logger: records when a phase loses supply.

Reads the live voltages the sampler (api.py) publishes to ``live_data.json``.

Fixes compared with the original version:
* Removed ``import live_data`` (no such module, so the script could not start).
* Uses R/Y/B keys end to end. The sampler wrote raw chip keys (A/B/C) and this script
  looked for R/Y/B, so R and Y were never detected and "B" held phase Y's voltage.
* Ignores stale data: if the sampler stops, the last voltages are not trusted forever.
* Keeps the last 5 failures per phase (the comment said 5, the query kept 1).
* Shares the DB path with every other process via config.py.
"""

from __future__ import annotations

import json
import time
from datetime import datetime

from config import FAILURE_FLAGS_PATH, FAILURE_VOLTAGE_V, LIVE_DATA_MAX_AGE_S, LIVE_DATA_PATH, PHASES, TZ
from db import init_db, insert_failure

KEEP_PER_PHASE = 5
CONFIRM_SAMPLES = 2


def load_flags() -> dict[str, bool]:
    try:
        saved = json.loads(FAILURE_FLAGS_PATH.read_text())
        return {p: bool(saved.get(p, False)) for p in PHASES}
    except (OSError, ValueError):
        return {p: False for p in PHASES}


def save_flags(flags: dict[str, bool]) -> None:
    try:
        FAILURE_FLAGS_PATH.write_text(json.dumps(flags))
    except OSError as e:
        print(f"[Save Flag Error] {e}")


def read_live_data() -> tuple[dict[str, float], str | None]:
    """Latest voltages by phase, or ({}, None) if missing, unreadable or stale."""
    try:
        data = json.loads(LIVE_DATA_PATH.read_text())
    except (OSError, ValueError):
        return {}, None
    if time.time() - float(data.get("epoch", 0)) > LIVE_DATA_MAX_AGE_S:
        return {}, None
    return data.get("voltage", {}), data.get("timestamp") or datetime.now(TZ).isoformat(timespec="seconds")


def monitor_voltage() -> None:
    init_db()
    failure_logged = load_flags()
    low_count = {p: 0 for p in PHASES}
    stale_warned = False
    print("[Voltage Monitor] Monitoring started...")

    while True:
        try:
            voltage, ts = read_live_data()
            if ts is None:
                if not stale_warned:
                    print("[Voltage Monitor] No fresh data from the sampler; waiting")
                    stale_warned = True
                time.sleep(1)
                continue
            stale_warned = False

            for phase in PHASES:
                v = voltage.get(phase)
                if v is None:
                    continue
                # Require CONFIRM_SAMPLES consecutive low readings so one glitchy sample
                # isn't logged as a power cut.
                low_count[phase] = low_count[phase] + 1 if v < FAILURE_VOLTAGE_V else 0
                if low_count[phase] >= CONFIRM_SAMPLES and not failure_logged[phase]:
                    print(f"[ALERT] Voltage LOW on phase {phase}: {v:.2f}V. Logging failure.")
                    insert_failure(phase, ts, keep=KEEP_PER_PHASE)
                    failure_logged[phase] = True
                    save_flags(failure_logged)
                elif v >= FAILURE_VOLTAGE_V and failure_logged[phase]:
                    print(f"[INFO] Phase {phase} supply restored ({v:.1f} V)")
                    failure_logged[phase] = False
                    save_flags(failure_logged)

            time.sleep(1)

        except Exception as e:
            print(f"[Voltage Monitor Error] {e}")
            time.sleep(2)


if __name__ == "__main__":
    try:
        monitor_voltage()
    except KeyboardInterrupt:
        pass
