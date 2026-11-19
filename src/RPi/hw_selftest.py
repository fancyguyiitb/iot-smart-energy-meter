"""Hardware bring-up check: talk to the ADE9000 once and print what it measures.

Use it when assembling a board (``VOLTIX_HAL=hardware``) or to poke the virtual board.
On real hardware stop ``api.py`` first: two processes must not share the SPI bus.
It initialises the chip, checks it is running, prints one reading per phase, and
watches the energy accumulators for a few seconds. It writes nothing anywhere.

    python hw_selftest.py            # VOLTIX_HAL from device.env / environment
"""

from __future__ import annotations

import sys
import time

from ADE9000API import ADE9000, sign_extend_32
from ADE9000CalibrationInputs import CAL_ENERGY_CC
from ADE9000RegMap import ADDR_RUN
from config import HAL, PHASE_TO_CHIP, PHASES


def main() -> int:
    print(f"HAL: {HAL}")
    chip = ADE9000()
    try:
        chip.spi_init(spi_speed=5_000_000, chip_select_pin=8)
    except OSError as e:
        print(f"FAIL  cannot open SPI: {e}")
        return 1
    chip.setup_ADE9000()
    time.sleep(1.0)  # let the RMS filters settle
    run = chip.spi_read_16(ADDR_RUN)
    print(f"{'OK  ' if run & 1 else 'FAIL'}  RUN register = {run:#06x}")
    if not run & 1:
        return 1

    v, i = chip.read_voltage_rms_regs(), chip.read_current_rms_regs()
    p, pf = chip.read_active_power_regs(), chip.read_power_factor_regs_values()
    f = chip.read_period_regs_values()
    t = chip.read_temp_reg_value()
    print(f"      temperature {t['Temperature']:.1f} C, neutral current {i['CurrentRMSReg_N']:.2f} A")
    problems = 0
    for ph in PHASES:
        c = PHASE_TO_CHIP[ph]
        volts = v[f"VoltageRMSReg_{c}"]
        ok = 180 <= volts <= 270
        problems += not ok
        print(f"{'OK  ' if ok else 'WARN'}  {ph}: {volts:6.1f} V  {i[f'CurrentRMSReg_{c}']:6.2f} A  "
              f"{p[f'ActivePowerReg_{c}']:8.1f} W  PF {pf[f'PowerFactorValue_{c}']:+.2f}  "
              f"{f[f'FrequencyValue_{c}']:.2f} Hz")

    raw0 = chip.read_energy_watthr_raw()
    time.sleep(3)
    raw1 = chip.read_energy_watthr_raw()
    for ph in PHASES:
        c = PHASE_TO_CHIP[ph]
        wh = sign_extend_32((raw1[c] - raw0[c]) & 0xFFFFFFFF) * CAL_ENERGY_CC * 1e-6
        print(f"      {ph}: energy accumulator advanced {wh * 1000:.1f} mWh in 3 s")
    print("Done." if not problems else f"Done with {problems} warning(s) (voltage outside 180-270 V).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
