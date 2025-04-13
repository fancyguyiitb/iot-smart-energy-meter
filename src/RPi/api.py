import time
from datetime import datetime
from db import init_db, insert_power_data, get_last_max_energy
from ADE9000RegMap import *
from ADE9000API import ADE9000
from ADE9000API_header import *
from ADE9000CalibrationInputs import *
from zoneinfo import ZoneInfo  # Requires Python 3.9+
import shared_flags
import json

from helpers import get_max_energy

SPI_SPEED = 5000000
CS_PIN = 8

ade9000 = ADE9000()


def write_live_data(voltage, timestamp):
    data = {"voltage": voltage, "timestamp": timestamp}
    with open("live_data.json", "w") as f:
        json.dump(data, f)


def get_iso_timestamp():
    ist = ZoneInfo("Asia/Kolkata")
    ist_time = datetime.now(ist)
    return ist_time.isoformat(timespec="milliseconds")


def reset_ade9000():
    print("[RESET] Resetting ADE9000...")
    time.sleep(1)
    print("[RESET] Done.")


def initialize_ade9000():
    print("[INIT] Initializing ADE9000...")
    reset_ade9000()
    ade9000.spi_init(spi_speed=SPI_SPEED, chip_select_pin=CS_PIN)
    ade9000.setup_ADE9000()
    run_reg = ade9000.spi_read_16(ADDR_RUN)
    print(f"[INIT] RUN Register: {hex(run_reg)}")
    print("[INIT] ADE9000 is ready.\n")


PHASE_MAPPING = {"R": "A", "Y": "B", "B": "C"}


def monitor_data(interval=1.0):
    print("[MONITOR] Starting logging loop. Press Ctrl+C to stop.\n")

    # Energy counters for phases
    energy_accumulator = {"R": 0.0, "Y": 0.0, "B": 0.0}
    reactive_power = {"R": 0.0, "Y": 0.0, "B": 0.0}

    while True:
        try:
            voltage = ade9000.read_voltage_rms_regs()
            current = ade9000.read_current_rms_regs()
            active = ade9000.read_active_power_regs()
            reactive = ade9000.read_reactive_power_regs()
            apparent = ade9000.read_apparent_power_regs()
            voltage_thd = ade9000.read_voltage_thd_regs_values()
            current_thd = ade9000.read_current_thd_regs_values()
            freq = ade9000.read_period_regs_values()
            timestamp = get_iso_timestamp()
            print("=" * 70)
            print(f"Timestamp: {timestamp}")
            print(voltage)
            write_live_data(voltage, timestamp)

            for phase in ["R", "Y", "B"]:
                phase_m = PHASE_MAPPING[phase]
                vrms = voltage[f"VoltageRMSReg_{phase_m}"]
                irms = current[f"CurrentRMSReg_{phase_m}"]
                pw = active[f"ActivePowerReg_{phase_m}"]
                pvar = reactive[f"ReactivePowerReg_{phase_m}"]
                pva = apparent[f"ApparentPowerReg_{phase_m}"]
                vthd = voltage_thd[f"VoltageTHDValue_{phase_m}"]
                ithd = current_thd[f"CurrentTHDValue_{phase_m}"]
                pfactor = pw / pva if pva != 0 else 0
                vfreq = freq[f"FrequencyValue_{phase_m}"]

                # Case when the accumulated energy is 0.
                if energy_accumulator[phase] == 0.0:
                    local_max_energy = get_last_max_energy(phase) or 0.0

                    remote_max_energy = get_max_energy()[phase]["energy_kwh"] or 0.0
                    # print("[INFO]: Remot Things Working", local_max_energy, remote_max_energy)

                    last_energy = max(local_max_energy, remote_max_energy)
                    print(
                        "[INFO] Last Energy Fetched from Servers and the DB: ",
                        remote_max_energy,
                        local_max_energy,
                    )
                    energy_accumulator[phase] = last_energy

                print(
                    f"[INFO]: Energy Accumulator {phase}: {energy_accumulator[phase]}"
                )

                # Approximate energy accumulation (Wh = W * hours)
                energy_accumulator[phase] += pw * (
                    interval / 3600000.0
                )  # W * sec / 3600 = Wh
                energy_kwh = energy_accumulator[phase]
                if shared_flags.reset_flag:
                    energy_kwh = 0

                reactive_power[phase] = (abs(pva**2 - pw**2)) ** 0.5

                insert_power_data(
                    phase=phase,
                    voltage_rms=vrms,
                    current_rms=irms,
                    active_power=pw,
                    reactive_power=pvar,
                    apparent_power=pva,
                    voltage_thd=vthd,
                    current_thd=ithd,
                    power_factor=pfactor,
                    voltage_freq=vfreq,
                    timestamp=timestamp,
                    energy_kwh="{:.7f}".format(energy_kwh),
                )

            # Neutral logging
            neutral_current = current["CurrentRMSReg_N"]
            print("\n--- Neutral Line ---")
            print(f"Neutral Current RMS : {neutral_current:.2f} A")
            insert_power_data(
                phase="Neutral",
                voltage_rms=0.0,
                current_rms=neutral_current,
                active_power=None,
                reactive_power=None,
                apparent_power=None,
                voltage_thd=None,
                current_thd=None,
                power_factor=None,
                voltage_freq=None,
                timestamp=timestamp,
                energy_kwh=None,
            )

            print("=" * 70)
            time.sleep(interval)

        except Exception as e:
            print(f"[ERROR] {e}")
            time.sleep(2)


if __name__ == "__main__":
    init_db()
    initialize_ade9000()
    monitor_data(interval=1.0)
