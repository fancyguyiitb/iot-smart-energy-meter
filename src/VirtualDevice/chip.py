"""Register-level emulation of the Analog Devices ADE9000 energy-metering IC.

The firmware's real driver (``src/RPi/ADE9000API.py``) talks to this exactly as it
would to silicon: 16/32-bit SPI frames where the first two bytes are
``(address << 4) | read_bit``. Register codes are produced from the physical
model using the same board calibration constants the firmware uses to decode them,
so every conversion (and every conversion *bug*) in the driver is exercised.

Implemented behaviour (the parts the firmware relies on):

* Measurement registers read as 0 until the DSP is started by writing ``RUN = 1``.
* xVRMS / xIRMS / NIRMS, xWATT / xVAR (signed) and xVA, xPF (signed, 2^27 = 1.0),
  xVTHD / xITHD (2^27 = 100 %), xPERIOD, half-cycle RMS, angle registers, temperature.
* xWATTHR_HI/LO energy accumulators: signed, wrap at 32 bits like the real part
  (about 2.9 kWh per wrap with this board's calibration), with optional reset-on-read
  when ``EP_CFG`` bit 5 (RD_RST_EN) is set.
"""

from __future__ import annotations

import math
import sys
import threading
import time
from pathlib import Path

# The register map and the board calibration constants are hardware facts shared with the
# firmware, so read them from the firmware tree instead of duplicating them.
RPI_DIR = Path(__file__).resolve().parents[1] / "RPi"
if str(RPI_DIR) not in sys.path:
    sys.path.insert(0, str(RPI_DIR))

import ADE9000RegMap as R  # noqa: E402
from ADE9000CalibrationInputs import (  # noqa: E402
    CAL_ENERGY_CC,
    CAL_IRMS_CC,
    CAL_POWER_CC,
    CAL_VRMS_CC,
)

from physics import PHASES, Installation  # noqa: E402

CHIP_PHASE = {"R": "A", "Y": "B", "B": "C"}  # board wiring: R->A, Y->B, B->C
EP_CFG_RD_RST_EN = 0x0020
ANGLE_LSB_50HZ = 0.017578125  # degrees per code at 50 Hz
TEMP_OFFSET_C = 100  # TEMP_TRIM offset; firmware computes (offset >> 5) - reg * gain / 65536

V_LSB = CAL_VRMS_CC * 1e-6  # volts per code
I_LSB = CAL_IRMS_CC * 1e-6  # amps per code
P_LSB = CAL_POWER_CC * 1e-3  # watts (var, VA) per code
E_LSB_WH = CAL_ENERGY_CC * 1e-6  # Wh per xWATTHR_HI code
FRAC27 = 1 << 27


def u32(value: float | int) -> int:
    """Two's-complement 32-bit encoding of a (possibly negative) number."""
    return int(round(value)) & 0xFFFFFFFF


def addr(name: str) -> int:
    return getattr(R, f"ADDR_{name}") & 0xFFF


class VirtualADE9000:
    def __init__(self, installation: Installation) -> None:
        self.installation = installation
        self.lock = threading.RLock()
        self.regs: dict[int, int] = {}
        self.running = False
        self.energy_acc_wh = {p: 0.0 for p in PHASES}  # what the chip has accumulated (measured, signed)
        self.var_acc = {p: 0.0 for p in PHASES}
        self.va_acc = {p: 0.0 for p in PHASES}
        self.spi_transactions = 0
        self.last_access = 0.0
        self.temperature_c = 38.0
        self._last_update = time.monotonic()
        self._energy_hi_addrs = {addr(f"{CHIP_PHASE[p]}WATTHR_HI"): p for p in PHASES}

    # ------------------------------------------------------------------ DSP side
    def update(self) -> None:
        """Called by the simulation loop: refresh measurement registers from the model."""
        snap = self.installation.step()
        with self.lock:
            now = time.monotonic()
            dt = min(max(now - self._last_update, 0.0), 2.0)
            self._last_update = now
            ep_cfg = self.regs.get(addr("EP_CFG"), 0)
            accumulate = self.running and (ep_cfg & 0x0001)
            for p in PHASES:
                c = CHIP_PHASE[p]
                t = snap.phases[p]
                sign = -1.0 if self.installation.supply[p].ct_reversed else 1.0
                watt = sign * t.active_w
                var = sign * t.reactive_var
                pf = sign * t.pf
                self._set(f"{c}VRMS", t.voltage / V_LSB)
                self._set(f"{c}IRMS", t.current / I_LSB)
                self._set(f"{c}VRMSONE", t.voltage / V_LSB)
                self._set(f"{c}IRMSONE", t.current / I_LSB)
                self._set(f"{c}WATT", watt / P_LSB)
                self._set(f"{c}VAR", var / P_LSB)
                self._set(f"{c}VA", t.apparent_va / P_LSB)
                self._set(f"{c}PF", pf * FRAC27)
                self._set(f"{c}VTHD", t.voltage_thd / 100.0 * FRAC27)
                self._set(f"{c}ITHD", t.current_thd / 100.0 * FRAC27)
                period = (8000 * 65536 / t.frequency - 1) if t.frequency > 1 else 0x7FFFFFFF
                self._set(f"{c}PERIOD", period)
                if accumulate:
                    self.energy_acc_wh[p] += watt * dt / 3600.0
                    self.var_acc[p] += var * dt / 3600.0
                    self.va_acc[p] += t.apparent_va * dt / 3600.0
                self._write_energy(p)
            self._set("NIRMS", snap.neutral_current / I_LSB)
            self._set("NIRMSONE", snap.neutral_current / I_LSB)
            self._update_angles(snap)
            self._set("TEMP_TRIM", (TEMP_OFFSET_C << 5) << 16 | 0x10000 >> 1)  # gain 0.5
            self._set("TEMP_RSLT", (TEMP_OFFSET_C - self.temperature_c) * 2)

    def _update_angles(self, snap) -> None:
        def ang(deg: float) -> int:
            return int(round((deg % 360.0) / ANGLE_LSB_50HZ))

        # Delay of each voltage zero crossing after VA's, for a positive (R-Y-B) sequence.
        v_ang = {"R": 0.0, "Y": 120.0, "B": 240.0}
        # Current lags its voltage by phi = atan2(Q, P).
        phi = {p: (math.degrees(math.atan2(snap.phases[p].reactive_var, snap.phases[p].active_w))
                   if snap.phases[p].current > 0 else 0.0) for p in PHASES}
        i_ang = {p: v_ang[p] + phi[p] for p in PHASES}
        self._set("ANGL_VA_VB", ang(v_ang["Y"] - v_ang["R"]))
        self._set("ANGL_VB_VC", ang(v_ang["B"] - v_ang["Y"]))
        self._set("ANGL_VA_VC", ang(v_ang["B"] - v_ang["R"]))
        self._set("ANGL_VA_IA", ang(phi["R"]))
        self._set("ANGL_VB_IB", ang(phi["Y"]))
        self._set("ANGL_VC_IC", ang(phi["B"]))
        self._set("ANGL_IA_IB", ang(i_ang["Y"] - i_ang["R"]))
        self._set("ANGL_IB_IC", ang(i_ang["B"] - i_ang["Y"]))
        self._set("ANGL_IA_IC", ang(i_ang["B"] - i_ang["R"]))

    def _write_energy(self, p: str) -> None:
        c = CHIP_PHASE[p]
        codes = int(self.energy_acc_wh[p] / E_LSB_WH * 8192)  # 13 fractional bits live in _LO
        self.regs[addr(f"{c}WATTHR_HI")] = (codes >> 13) & 0xFFFFFFFF
        self.regs[addr(f"{c}WATTHR_LO")] = (codes & 0x1FFF) << 19
        for kind, acc in (("VARHR", self.var_acc), ("VAHR", self.va_acc)):
            k = int(acc[p] / E_LSB_WH * 8192)
            self.regs[addr(f"{c}{kind}_HI")] = (k >> 13) & 0xFFFFFFFF
            self.regs[addr(f"{c}{kind}_LO")] = (k & 0x1FFF) << 19

    def _set(self, name: str, value: float) -> None:
        self.regs[addr(name)] = u32(value) if self.running or name.startswith("TEMP") else 0

    # ------------------------------------------------------------------ SPI side
    def transfer(self, tx: list[int]) -> list[int]:
        """Handle one SPI frame (chip-select asserted for the whole list)."""
        if len(tx) < 2:
            return [0] * len(tx)
        cmd = (tx[0] << 8) | tx[1]
        address = cmd >> 4
        is_read = bool(cmd & 0x08)
        payload = tx[2:]
        with self.lock:
            self.spi_transactions += 1
            self.last_access = time.time()
            if is_read:
                value = self.regs.get(address, 0)
                if len(payload) == 2:
                    data = [(value >> 8) & 0xFF, value & 0xFF]
                else:
                    data = [(value >> 24) & 0xFF, (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF]
                    data += [0] * (len(payload) - 4)
                if address in self._energy_hi_addrs and self.regs.get(addr("EP_CFG"), 0) & EP_CFG_RD_RST_EN:
                    self.energy_acc_wh[self._energy_hi_addrs[address]] = 0.0
                    self._write_energy(self._energy_hi_addrs[address])
                return [0, 0] + data[: len(payload)]
            value = 0
            for b in payload:
                value = (value << 8) | (b & 0xFF)
            self.regs[address] = value
            if address == addr("RUN"):
                self.running = bool(value & 0x1)
            return [0] * len(tx)

    def stats(self) -> dict:
        with self.lock:
            return {
                "running": self.running,
                "spi_transactions": self.spi_transactions,
                "last_access": self.last_access,
                "energy_accumulator_wh": dict(self.energy_acc_wh),
                "ep_cfg": self.regs.get(addr("EP_CFG"), 0),
            }
