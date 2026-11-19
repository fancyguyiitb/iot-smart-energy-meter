"""Sampling process: reads the ADE9000 every second and stores the sample locally.

Fixes compared with the original version:
* Energy is integrated with the *measured* time between samples (``time.monotonic``),
  not a nominal 1 s, so loop overruns and errors no longer make the meter read low.
* Energy is restored once at start-up from the newer of the local DB and the server
  (the old code took ``max()`` and crashed on a healthy server response).
* Energy reset requests from the GUI arrive through the shared DB (a module-level flag
  can't cross process boundaries).
* All phases of one sample are written in a single transaction, and live voltages are
  published atomically with R/Y/B keys for the failure logger.
* The ADE9000 is re-initialised automatically if it loses its configuration
  (brown-out / board power cycle), detected via the RUN register.
"""

from __future__ import annotations

import json
import time
from datetime import datetime

from ADE9000API import ADE9000
from ADE9000CalibrationInputs import CAL_ENERGY_CC
from ADE9000RegMap import ADDR_RUN
from clock import wait_for_trusted_clock
from config import (
    CLOCK_SYNC_TIMEOUT_S,
    ENERGY_RESTORE_RETRY_S,
    ENERGY_STATE_PATH,
    LIVE_DATA_PATH,
    PHASE_TO_CHIP,
    PHASES,
    SAMPLE_INTERVAL_S,
)
from db import (
    ack_energy_reset,
    get_last_counters,
    get_latest_timestamp,
    init_db,
    insert_samples,
    now_local_iso,
    pending_energy_reset,
    prune_synced,
)
from fileutil import atomic_write_text
from helpers import get_last_energy as get_remote_last_energy
from sprint import Logger

SPI_SPEED = 5000000
CS_PIN = 8
PRUNE_EVERY_S = 3600
MAX_DT_S = 10 * SAMPLE_INTERVAL_S  # longest gap we integrate over after a stall
LOG_EVERY_N = 10
DSP_SETTLE_S = 1.0
STATE_EVERY_N = 10

l = Logger.get_instance(debug=True)
ade9000 = ADE9000()


def write_live_data(rows: list[dict], timestamp: str) -> None:
    """Publish the newest V/I/P per phase for failure_log.py and the relay safety checks.
    Written atomically (tmp + rename)."""
    payload = {"timestamp": timestamp, "epoch": time.time(),
               "voltage": {r["phase"]: r["voltage_rms"] for r in rows},
               "current": {r["phase"]: r["current_rms"] for r in rows},
               "power": {r["phase"]: r["active_power"] for r in rows}}
    atomic_write_text(LIVE_DATA_PATH, json.dumps(payload))


def get_iso_timestamp() -> str:
    return now_local_iso()


def initialize_ade9000() -> None:
    l.iprint("[INIT] Initializing ADE9000...")
    ade9000.spi_init(spi_speed=SPI_SPEED, chip_select_pin=CS_PIN)
    ade9000.setup_ADE9000()
    # Let the DSP's RMS filters settle; reading straight after RUN=1 returns zeros, which
    # the failure logger would record as a power cut on every boot.
    time.sleep(DSP_SETTLE_S)
    run_reg = ade9000.spi_read_16(ADDR_RUN)
    l.iprint(f"[INIT] RUN Register: {hex(run_reg)} - ADE9000 is ready.")


def _parse(ts: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(ts) if ts else None
    except ValueError:
        return None


COUNTERS = ("energy_kwh", "energy_sw_kwh", "export_kwh")
# energy_kwh    import energy from the ADE9000's own accumulators (billing grade)
# energy_sw_kwh import energy integrated in software from 1 Hz power readings (cross-check)
# export_kwh    export energy from the chip's accumulators (solar, or a CT clamped backwards)


def wrap_delta(prev: int, cur: int) -> int:
    """Signed difference of two 32-bit accumulator readings, correct across wrap-around.

    The xWATTHR_HI register wraps every ~2.9 kWh with this board's calibration. Reading it
    as a running value and differencing (instead of reset-on-read) means a failed or lost
    read can never lose energy: the next successful read still sees all of it.
    """
    return ((cur - prev + (1 << 31)) % (1 << 32)) - (1 << 31)


class ChipEnergy:
    """Turns successive raw accumulator readings into Wh deltas per phase."""

    def __init__(self) -> None:
        self.prev: dict[str, int] | None = None

    def reset(self) -> None:
        """After a chip (re)initialisation the accumulators restart: take a new baseline."""
        self.prev = None

    def deltas_wh(self, raw: dict[str, int]) -> dict[str, float]:
        if self.prev is None:
            self.prev = dict(raw)
            return {k: 0.0 for k in raw}
        out = {k: wrap_delta(self.prev[k], raw[k]) * CAL_ENERGY_CC * 1e-6 for k in raw}
        self.prev = dict(raw)
        return out


def save_energy_state(counters: dict[str, dict[str, float]], timestamp: str) -> None:
    """Small side file so the counters survive a lost or corrupt database."""
    atomic_write_text(ENERGY_STATE_PATH, json.dumps({"timestamp": timestamp, "counters": counters}))


def load_energy_state() -> dict | None:
    try:
        data = json.loads(ENERGY_STATE_PATH.read_text())
        if "counters" not in data:  # older format: only the import counter
            data["counters"] = {"energy_kwh": data["energy_kwh"]}
        return {"timestamp": data["timestamp"],
                "counters": {c: {p: float(data["counters"].get(c, {}).get(p, 0.0)) for p in PHASES}
                             for c in COUNTERS}}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def newest(candidates: list[tuple[str | None, float]]) -> float | None:
    """Value of the candidate with the newest timestamp, or None if none has one."""
    dated = [(_parse(ts), v) for ts, v in candidates if _parse(ts) is not None]
    return max(dated, key=lambda c: c[0])[1] if dated else None


def restore_energy(retry_s: float = ENERGY_RESTORE_RETRY_S, sleep=time.sleep) -> dict[str, dict[str, float]]:
    """Continue every energy counter from the newest of: local DB, state file, server.

    If the local DB and the state file are both empty (new SD card, corrupt DB) and the
    server can't be reached, keep asking the server for ``retry_s`` before starting from
    0. Previously an unreachable server at boot silently reset the counter.
    Returns {counter: {phase: kWh}}.
    """
    state = load_energy_state()
    local = {p: get_last_counters(p) for p in PHASES}
    have_local = state is not None or any(ts for _, ts in local.values())

    remote = get_remote_last_energy()
    waited, delay = 0.0, 2.0
    while remote is None and not have_local and waited < retry_s:
        l.eprint(f"[WARN] No local energy history and the server is unreachable; retrying in {delay:.0f} s")
        sleep(delay)
        waited += delay
        delay = min(delay * 2, 30.0)
        remote = get_remote_last_energy()
    if remote is None and not have_local:
        l.eprint("[WARN] Starting energy counters from 0: no local history and no server")

    restored = {c: {} for c in COUNTERS}
    for p in PHASES:
        values, ts = local[p]
        for c in COUNTERS:
            candidates = [(ts, values.get(c, 0.0))]
            if state:
                candidates.append((state["timestamp"], state["counters"][c][p]))
            if remote:
                candidates.append((remote[p]["timestamp"], remote[p].get(c, 0.0)))
            value = newest(candidates)
            restored[c][p] = value if value is not None else 0.0
    l.iprint("[INFO] Restored energy (kWh):",
             {c: {p: round(v, 4) for p, v in restored[c].items()} for c in COUNTERS})
    return restored


def monitor_data(interval: float = SAMPLE_INTERVAL_S) -> None:
    l.iprint("[MONITOR] Starting logging loop. Press Ctrl+C to stop.")
    counters = restore_energy()
    chip = ChipEnergy()
    last_sample_t = time.monotonic()
    last_prune = 0.0
    n = 0

    while True:
        loop_start = time.monotonic()
        try:
            # Checked every sample: an unconfigured chip reads 0 V, which must never be
            # stored (the failure logger would record a blackout on all phases).
            if not (ade9000.spi_read_16(ADDR_RUN) & 0x1):
                l.eprint("[WARN] ADE9000 lost its configuration (RUN=0); re-initialising")
                initialize_ade9000()
                chip.reset()  # its accumulators restarted from zero
                last_sample_t = time.monotonic()  # don't integrate energy across the outage
                continue

            voltage = ade9000.read_voltage_rms_regs()
            current = ade9000.read_current_rms_regs()
            active = ade9000.read_active_power_regs()
            reactive = ade9000.read_reactive_power_regs()
            apparent = ade9000.read_apparent_power_regs()
            voltage_thd = ade9000.read_voltage_thd_regs_values()
            current_thd = ade9000.read_current_thd_regs_values()
            freq = ade9000.read_period_regs_values()
            chip_wh = chip.deltas_wh(ade9000.read_energy_watthr_raw())

            now = time.monotonic()
            dt = now - last_sample_t
            last_sample_t = now
            if dt > MAX_DT_S:
                # The software integrator can only guess across a stall; the chip kept counting.
                l.eprint(f"[WARN] {dt:.1f} s since the last sample; software integration capped at "
                         f"{MAX_DT_S:.0f} s (chip accumulators are unaffected)")
                dt = MAX_DT_S

            token = pending_energy_reset()
            was_reset = bool(token)
            if token:
                counters = {c: {p: 0.0 for p in PHASES} for c in COUNTERS}
                ack_energy_reset(token)
                l.iprint("[INFO] Energy counters reset on request from the GUI")

            timestamp = get_iso_timestamp()
            rows, deltas = [], {}
            for phase in PHASES:
                c = PHASE_TO_CHIP[phase]
                pw = active[f"ActivePowerReg_{c}"]
                pva = apparent[f"ApparentPowerReg_{c}"]
                wh = chip_wh[c]
                import_kwh, export_kwh = max(wh, 0.0) / 1000.0, max(-wh, 0.0) / 1000.0
                counters["energy_kwh"][phase] += import_kwh
                counters["export_kwh"][phase] += export_kwh
                # Software cross-check: import only, integrated with the measured dt.
                counters["energy_sw_kwh"][phase] += max(pw, 0.0) * dt / 3_600_000.0
                deltas[phase] = import_kwh
                rows.append({
                    "phase": phase,
                    "voltage_rms": voltage[f"VoltageRMSReg_{c}"],
                    "current_rms": current[f"CurrentRMSReg_{c}"],
                    "active_power": pw,
                    "reactive_power": reactive[f"ReactivePowerReg_{c}"],
                    "apparent_power": pva,
                    **{k: round(counters[k][phase], 7) for k in COUNTERS},
                    "voltage_thd": voltage_thd[f"VoltageTHDValue_{c}"],
                    "current_thd": current_thd[f"CurrentTHDValue_{c}"],
                    "power_factor": pw / pva if pva else 0.0,
                    "voltage_freq": freq[f"FrequencyValue_{c}"],
                    "timestamp": timestamp,
                })
            rows.append({"phase": "Neutral", "voltage_rms": 0.0, "current_rms": current["CurrentRMSReg_N"],
                         "energy_kwh": 0.0, "timestamp": timestamp})

            insert_samples(rows, deltas, day=timestamp[:10])
            write_live_data(rows[:3], timestamp)
            if was_reset or n % STATE_EVERY_N == 0:  # every 10 s: limits SD-card writes
                save_energy_state(counters, timestamp)

            if n % LOG_EVERY_N == 0:
                l.iprint("Sample", timestamp, " | ".join(
                    f"{r['phase']}: {r['voltage_rms']:.1f}V {r['current_rms']:.2f}A {r['active_power']:.0f}W "
                    f"chip {r['energy_kwh']:.4f} / sw {r['energy_sw_kwh']:.4f} kWh" for r in rows[:3])
                    + f" | N: {rows[3]['current_rms']:.2f}A")

            if now - last_prune > PRUNE_EVERY_S:
                prune_synced()
                last_prune = now
        except Exception as e:
            l.eprint(f"[ERROR] {type(e).__name__}: {e}")

        n += 1
        time.sleep(max(0.0, interval - (time.monotonic() - loop_start)))


if __name__ == "__main__":
    init_db()
    while True:
        try:
            initialize_ade9000()
            break
        except Exception as e:  # board not powered / simulator not up yet
            l.eprint(f"[INIT] ADE9000 not reachable ({e}); retrying in 3 s")
            time.sleep(3)
    try:
        # Readings stamped with a wrong clock land on the wrong day forever; wait first.
        wait_for_trusted_clock(get_latest_timestamp, CLOCK_SYNC_TIMEOUT_S, log=l.iprint)
        monitor_data(interval=SAMPLE_INTERVAL_S)
    except KeyboardInterrupt:
        pass
