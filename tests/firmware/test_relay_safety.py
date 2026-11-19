"""Fail-safe switching (feature 4) and dual energy metering (feature 1)."""

import pytest

from relay_safety import Limits, RelayController


class Rig:
    """Fake pins, fake clock and a fake 'world': current flows if the relay is closed or welded."""

    def __init__(self, tmp_path, **limits):
        self.t = 1_000_000.0
        self.pins = {}
        self.welded = {p: False for p in "RYB"}
        self.load_a = {p: 5.0 for p in "RYB"}
        self.volts = {p: 230.0 for p in "RYB"}
        self.readings = True
        self.ctl = RelayController("RYB", self.set_pin, self.read_live, tmp_path / "relay.json",
                                   Limits(**limits), clock=lambda: self.t, sleep=self.advance)

    def set_pin(self, p, on):
        self.pins[p] = on

    def advance(self, s):
        self.t += s

    def read_live(self):
        if not self.readings:
            return None
        flowing = {p: self.load_a[p] if (self.pins.get(p, True) or self.welded[p]) else 0.0 for p in "RYB"}
        return {"epoch": self.t, "voltage": dict(self.volts), "current": flowing}


@pytest.fixture()
def rig(tmp_path):
    return Rig(tmp_path)


def test_off_is_verified_by_measurement(rig):
    r = rig.ctl.command("Y", on=False)
    assert r == {"ok": True, "error": None, "verified": True}
    assert rig.pins["Y"] is False


def test_welded_contacts_are_detected(rig):
    rig.welded["Y"] = True
    r = rig.ctl.command("Y", on=False)
    assert not r["ok"] and "did not open" in r["error"] and "5.00 A" in r["error"]
    assert rig.ctl.details()["Y"]["welded"]
    assert rig.ctl.take_events()[0]["action"] == "welded"


def test_min_off_time_blocks_quick_restart(rig):
    rig.ctl.command("B", on=False)
    rig.advance(30)
    r = rig.ctl.command("B", on=True)
    assert not r["ok"] and "minimum off-time" in r["error"]
    assert rig.ctl.details()["B"]["lockout_s"] == 150
    rig.advance(151)
    assert rig.ctl.command("B", on=True)["ok"]


def test_refuses_on_into_abnormal_supply(rig):
    rig.ctl.command("R", on=False)
    rig.advance(200)
    rig.volts["R"] = 172.0  # brown-out
    r = rig.ctl.command("R", on=True)
    assert not r["ok"] and "supply too low" in r["error"]
    rig.volts["R"] = 0.0
    assert "no supply" in rig.ctl.command("R", on=True)["error"]


def test_anti_chatter(tmp_path):
    rig = Rig(tmp_path, min_off_time_s=0, max_switches=4)
    results = []
    for i in range(6):
        results.append(rig.ctl.command("R", on=(i % 2 == 1))["ok"])
        rig.advance(5)
    # 5th switch (OFF) refused, so the relay stays ON; the 6th (ON) is then a no-op.
    assert results == [True, True, True, True, False, True]
    assert rig.pins["R"] is True and len(rig.ctl.state["R"].switches) == 4


def test_overcurrent_trip(rig):
    rig.load_a["B"] = 40.0
    rig.ctl.tick()
    assert rig.pins.get("B", True)  # not instantly: needs to persist for trip_delay_s
    rig.advance(2.5)
    rig.ctl.tick()
    assert rig.pins["B"] is False
    assert "overcurrent trip: 40.0 A" in rig.ctl.details()["B"]["reason"]
    assert rig.ctl.take_events()[0]["action"] == "trip"


def test_short_inrush_does_not_trip(rig):
    rig.load_a["B"] = 40.0
    rig.ctl.tick()
    rig.load_a["B"] = 5.0  # motor start-up spike gone
    rig.advance(3)
    rig.ctl.tick()
    assert rig.pins.get("B", True)


def test_off_always_allowed_and_on_allowed_unverified_without_readings(rig):
    rig.readings = False  # sampler crashed
    assert rig.ctl.command("Y", on=False)["ok"]  # safe direction: always
    rig.advance(200)
    r = rig.ctl.command("Y", on=True)
    assert r["ok"] and r["verified"] is False  # don't strand the house without power


def test_state_survives_restart_without_toggling(tmp_path):
    rig = Rig(tmp_path)
    rig.ctl.command("R", on=False)
    rig2 = Rig(tmp_path)  # process restart
    rig2.ctl.restore_pins()
    assert rig2.pins == {"R": False, "Y": True, "B": True}
    assert not rig2.ctl.command("R", on=True)["ok"]  # min off-time remembered across the restart


def test_reads_old_state_file_format(tmp_path):
    (tmp_path / "relay.json").write_text('{"R": false, "Y": true, "B": true}')
    rig = Rig(tmp_path)
    assert rig.ctl.state["R"].on is False and rig.ctl.state["Y"].on is True


# ------------------------------------------------------------------ feature 1: energy
def test_wrap_delta_handles_32_bit_wraparound():
    from api import wrap_delta

    assert wrap_delta(100, 150) == 50
    assert wrap_delta(0xFFFFFFF0, 0x00000010) == 0x20  # wrapped forward
    assert wrap_delta(10, 0xFFFFFFF6) == -20  # export: counting down through zero


def test_chip_energy_baseline_and_deltas():
    from api import ChipEnergy
    from ADE9000CalibrationInputs import CAL_ENERGY_CC

    ce = ChipEnergy()
    assert ce.deltas_wh({"A": 1000, "B": 0, "C": 0}) == {"A": 0.0, "B": 0.0, "C": 0.0}  # baseline only
    d = ce.deltas_wh({"A": 1000 + 742_000, "B": 0, "C": 0})
    assert d["A"] == pytest.approx(742_000 * CAL_ENERGY_CC * 1e-6)  # ~1 Wh
    ce.reset()  # chip re-initialised: accumulators restarted, take a new baseline
    assert ce.deltas_wh({"A": 5, "B": 0, "C": 0})["A"] == 0.0
