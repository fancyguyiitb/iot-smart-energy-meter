"""The real ADE9000 driver against the emulated chip (no HTTP: frames go straight in)."""

import pytest

from ADE9000API import ADE9000, sign_extend_32
from chip import VirtualADE9000
from physics import Installation


class DirectSpi:
    def __init__(self, chip):
        self.chip = chip

    def xfer2(self, tx):
        return self.chip.transfer(tx)


@pytest.fixture()
def board():
    inst = Installation()
    inst.update_grid(noise=False)
    chip = VirtualADE9000(inst)
    drv = ADE9000()
    drv.spi = DirectSpi(chip)
    return inst, chip, drv


def test_sign_extension_is_twos_complement():
    assert sign_extend_32(0xFFFFFFFF) == -1
    assert sign_extend_32(0x80000000) == -(1 << 31)
    assert sign_extend_32(0x7FFFFFFF) == (1 << 31) - 1
    # Regression: the old implementation returned the magnitude (+1) here.
    assert sign_extend_32((-1) & 0xFFFFFFFF) < 0


def test_measurements_read_zero_until_run(board):
    inst, chip, drv = board
    chip.update()
    assert drv.read_voltage_rms_regs()["VoltageRMSReg_A"] == 0
    drv.setup_ADE9000()
    chip.update()
    assert drv.read_voltage_rms_regs()["VoltageRMSReg_A"] > 200


def test_driver_decodes_what_the_wires_carry(board):
    inst, chip, drv = board
    drv.setup_ADE9000()
    for p in "RYB":
        inst.set_relay(p, True)
    inst.update_phase("R", custom_kw=-2.0)  # rooftop solar exporting on R
    chip.update()
    truth = inst.snapshot.phases
    v = drv.read_voltage_rms_regs()
    i = drv.read_current_rms_regs()
    p = drv.read_active_power_regs()
    pf = drv.read_power_factor_regs_values()
    assert v["VoltageRMSReg_A"] == pytest.approx(truth["R"].voltage, abs=0.01)
    assert i["CurrentRMSReg_B"] == pytest.approx(truth["Y"].current, abs=0.001)
    # Export must read negative (H4: it used to read as positive consumption).
    assert p["ActivePowerReg_A"] < 0
    assert p["ActivePowerReg_A"] == pytest.approx(truth["R"].active_w, rel=1e-3)
    assert -1.0 <= pf["PowerFactorValue_A"] < 0  # PF register is signed too
    assert p["ActivePowerReg_B"] > 0


def test_reversed_ct_shows_negative_power(board):
    inst, chip, drv = board
    drv.setup_ADE9000()
    inst.set_relay("B", True)
    inst.update_phase("B", ct_reversed=True)
    chip.update()
    assert inst.snapshot.phases["B"].active_w > 0  # really consuming
    assert drv.read_active_power_regs()["ActivePowerReg_C"] < 0  # but the CT says export


def test_energy_register_decoding_matches_chip_accumulator(board):
    inst, chip, drv = board
    drv.setup_ADE9000()
    chip.energy_acc_wh["Y"] = 123.456
    chip._write_energy("Y")
    # Regression: phases B/C were shifted left by 32 bits (2^32 too large).
    assert drv.read_energy_watthr_reg_value()["WATTHR_B"] == pytest.approx(123.456, abs=0.01)
    chip.energy_acc_wh["Y"] = -10.0
    chip._write_energy("Y")
    assert drv.read_energy_watthr_reg_value()["WATTHR_B"] == pytest.approx(-10.0, abs=0.01)


def test_angles_use_50hz_scale(board):
    inst, chip, drv = board
    drv.setup_ADE9000()
    chip.update()
    # Regression: `(accmode & 0x0100) >= 0` was always true -> 60 Hz scale on a 50 Hz grid.
    assert drv.read_angle_regs_values()["AngleValue_VA_VB"] == pytest.approx(120.0, abs=0.1)
