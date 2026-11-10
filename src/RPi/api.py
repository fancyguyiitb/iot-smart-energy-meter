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
from ADE9000RegMap import ADDR_RUN
from config import LIVE_DATA_PATH, PHASE_TO_CHIP, PHASES, SAMPLE_INTERVAL_S
from db import (
    ack_energy_reset,
    get_last_energy,
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

l = Logger.get_instance(debug=True)
ade9000 = ADE9000()


def write_live_data(voltage_by_phase: dict[str, float], timestamp: str) -> None:
    """Publish the latest voltages for failure_log.py. Written atomically (tmp + rename)."""
    payload = {"timestamp": timestamp, "epoch": time.time(), "voltage": voltage_by_phase}
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


def restore_energy() -> dict[str, float]:
    """Per phase, continue from whichever of local DB / server has the newer reading."""
    remote = get_remote_last_energy()
    restored = {}
    for p in PHASES:
        local_kwh, local_ts = get_last_energy(p)
        candidates = [(_parse(local_ts), local_kwh), (_parse(remote[p]["timestamp"]), remote[p]["energy_kwh"])]
        candidates = [c for c in candidates if c[0] is not None]
        restored[p] = max(candidates, key=lambda c: c[0])[1] if candidates else 0.0
    l.iprint("[INFO] Restored energy (kWh):", {p: round(v, 4) for p, v in restored.items()})
    return restored


def monitor_data(interval: float = SAMPLE_INTERVAL_S) -> None:
    l.iprint("[MONITOR] Starting logging loop. Press Ctrl+C to stop.")
    energy = restore_energy()
    last_sample_t = time.monotonic()
    last_prune = 0.0
    n = 0

    while True:
        loop_start = time.monotonic()
        try:
            if n % 10 == 0 and not (ade9000.spi_read_16(ADDR_RUN) & 0x1):
                l.eprint("[WARN] ADE9000 lost its configuration (RUN=0); re-initialising")
                initialize_ade9000()

            voltage = ade9000.read_voltage_rms_regs()
            current = ade9000.read_current_rms_regs()
            active = ade9000.read_active_power_regs()
            reactive = ade9000.read_reactive_power_regs()
            apparent = ade9000.read_apparent_power_regs()
            voltage_thd = ade9000.read_voltage_thd_regs_values()
            current_thd = ade9000.read_current_thd_regs_values()
            freq = ade9000.read_period_regs_values()

            now = time.monotonic()
            dt = now - last_sample_t
            last_sample_t = now
            if dt > MAX_DT_S:
                l.eprint(f"[WARN] {dt:.1f} s since the last sample; integrating only {MAX_DT_S:.0f} s")
                dt = MAX_DT_S

            token = pending_energy_reset()
            if token:
                energy = {p: 0.0 for p in PHASES}
                ack_energy_reset(token)
                l.iprint("[INFO] Energy counters reset on request from the GUI")

            timestamp = get_iso_timestamp()
            rows, deltas = [], {}
            for phase in PHASES:
                c = PHASE_TO_CHIP[phase]
                pw = active[f"ActivePowerReg_{c}"]
                pva = apparent[f"ApparentPowerReg_{c}"]
                # Import energy only: export (negative P) does not run this counter backwards.
                delta_kwh = max(pw, 0.0) * dt / 3_600_000.0
                energy[phase] += delta_kwh
                deltas[phase] = delta_kwh
                rows.append({
                    "phase": phase,
                    "voltage_rms": voltage[f"VoltageRMSReg_{c}"],
                    "current_rms": current[f"CurrentRMSReg_{c}"],
                    "active_power": pw,
                    "reactive_power": reactive[f"ReactivePowerReg_{c}"],
                    "apparent_power": pva,
                    "energy_kwh": round(energy[phase], 7),
                    "voltage_thd": voltage_thd[f"VoltageTHDValue_{c}"],
                    "current_thd": current_thd[f"CurrentTHDValue_{c}"],
                    "power_factor": pw / pva if pva else 0.0,
                    "voltage_freq": freq[f"FrequencyValue_{c}"],
                    "timestamp": timestamp,
                })
            rows.append({"phase": "Neutral", "voltage_rms": 0.0, "current_rms": current["CurrentRMSReg_N"],
                         "energy_kwh": 0.0, "timestamp": timestamp})

            insert_samples(rows, deltas, day=timestamp[:10])
            write_live_data({r["phase"]: r["voltage_rms"] for r in rows[:3]}, timestamp)

            if n % LOG_EVERY_N == 0:
                l.iprint("Sample", timestamp, " | ".join(
                    f"{r['phase']}: {r['voltage_rms']:.1f}V {r['current_rms']:.2f}A {r['active_power']:.0f}W "
                    f"{r['energy_kwh']:.4f}kWh" for r in rows[:3]) + f" | N: {rows[3]['current_rms']:.2f}A")

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
        monitor_data(interval=SAMPLE_INTERVAL_S)
    except KeyboardInterrupt:
        pass
