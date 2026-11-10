"""Electrical model of a 3-phase, 4-wire (Wye) household installation.

This is the "physical world" the virtual meter measures: the grid supply, the wiring,
the relays on the meter board and the appliances behind them. It produces *true*
values; :mod:`chip` turns them into ADE9000 register codes, exactly like the analog
front end + DSP would on the real board.

Conventions
-----------
* Phases are named R / Y / B (Indian convention). The ADE9000 calls them A / B / C.
* Positive active power = power flowing from the grid into the house (import).
  A negative "custom load" models generation (e.g. rooftop solar) and produces export.
* Phase-to-neutral nominal voltage is 230 V, 50 Hz.
"""

from __future__ import annotations

import cmath
import math
import random
import threading
import time
from dataclasses import asdict, dataclass, field

PHASES = ("R", "Y", "B")
PHASE_ANGLE_DEG = {"R": 0.0, "Y": -120.0, "B": 120.0}
NOMINAL_V = 230.0
NOMINAL_F = 50.0
SOURCE_RESISTANCE_OHM = 0.25  # service cable + transformer, per phase

MODE_FACTOR = {"normal": 1.0, "sag": 0.75, "swell": 1.15, "outage": 0.0}


@dataclass
class Appliance:
    id: str
    name: str
    phase: str
    watts: float  # rated active power at nominal voltage
    pf: float  # displacement power factor (lagging)
    thd: float  # current THD in % this load injects
    kind: str  # resistive | motor | electronic
    on: bool = False
    cycle_on_s: float = 0.0  # >0: thermostat-style cycling (e.g. fridge compressor)
    cycle_off_s: float = 0.0

    def drawing(self, now: float) -> bool:
        if not self.on:
            return False
        if self.cycle_on_s <= 0:
            return True
        period = self.cycle_on_s + self.cycle_off_s
        return (now % period) < self.cycle_on_s

    def power_at(self, v: float) -> float:
        """Active power drawn at supply voltage ``v``.

        Resistive loads follow P = V^2 / R; motors and switch-mode supplies are
        roughly constant-power over the normal voltage band.
        """
        if v <= 1.0:
            return 0.0
        if self.kind == "resistive":
            return self.watts * (v / NOMINAL_V) ** 2
        return self.watts


def default_appliances() -> list[Appliance]:
    return [
        Appliance("r_lights", "LED lights", "R", 80, 0.92, 60, "electronic", on=True),
        Appliance("r_fridge", "Refrigerator", "R", 180, 0.82, 12, "motor", on=True, cycle_on_s=90, cycle_off_s=60),
        Appliance("r_fans", "Ceiling fans", "R", 150, 0.90, 8, "motor", on=True),
        Appliance("y_geyser", "Water heater", "Y", 2000, 1.0, 2, "resistive"),
        Appliance("y_tv", "TV + set-top box", "Y", 150, 0.95, 75, "electronic", on=True),
        Appliance("y_microwave", "Microwave", "Y", 1200, 0.95, 25, "electronic"),
        Appliance("b_ac", "Air conditioner", "B", 1500, 0.90, 10, "motor"),
        Appliance("b_washer", "Washing machine", "B", 500, 0.75, 15, "motor"),
        Appliance("b_chargers", "Laptop + phone chargers", "B", 90, 0.60, 90, "electronic", on=True),
    ]


@dataclass
class PhaseSupply:
    mode: str = "normal"  # normal | sag | swell | outage
    nominal_v: float = NOMINAL_V
    custom_kw: float = 0.0  # extra adjustable load; negative = generation (export)
    custom_pf: float = 0.95
    ct_reversed: bool = False  # CT clamped the wrong way round -> measured P/Q sign flips


@dataclass
class GridSettings:
    frequency: float = NOMINAL_F
    voltage_thd: float = 2.0  # background voltage distortion of the grid, %
    loose_neutral: float = 0.0  # 0 = healthy, 1 = neutral fully open
    noise: bool = True


@dataclass
class PhaseTruth:
    voltage: float = 0.0
    current: float = 0.0
    active_w: float = 0.0  # true power flow (import positive)
    reactive_var: float = 0.0
    apparent_va: float = 0.0
    pf: float = 0.0  # signed like the ADE9000 PF register (sign of P)
    voltage_thd: float = 0.0
    current_thd: float = 0.0
    frequency: float = 0.0
    current_angle_deg: float = 0.0  # angle of current phasor relative to phase-R voltage
    relay_closed: bool = False
    energy_import_wh: float = 0.0  # ground-truth energy counters, for accuracy checks
    energy_export_wh: float = 0.0


@dataclass
class Snapshot:
    phases: dict[str, PhaseTruth] = field(default_factory=dict)
    neutral_current: float = 0.0
    timestamp: float = 0.0


class Installation:
    """Thread-safe model of the installation. ``step()`` advances simulated time."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.appliances: dict[str, Appliance] = {a.id: a for a in default_appliances()}
        self.supply: dict[str, PhaseSupply] = {p: PhaseSupply() for p in PHASES}
        self.grid = GridSettings()
        self.relay_closed: dict[str, bool] = {p: False for p in PHASES}
        self.snapshot = Snapshot(phases={p: PhaseTruth() for p in PHASES})
        self._last_step = time.monotonic()
        self._freq_drift = 0.0

    # ------------------------------------------------------------------ physics
    def step(self) -> Snapshot:
        with self.lock:
            now_mono = time.monotonic()
            dt = min(max(now_mono - self._last_step, 0.0), 2.0)
            self._last_step = now_mono
            now = time.time()
            rnd = random.gauss if self.grid.noise else (lambda mu, sigma: mu)

            # Slow random walk of grid frequency around the set point.
            self._freq_drift = 0.98 * self._freq_drift + rnd(0.0, 0.004)
            supply_up_any = any(self.supply[p].mode != "outage" for p in PHASES)

            results: dict[str, PhaseTruth] = {}
            for p in PHASES:
                sup = self.supply[p]
                v_src = sup.nominal_v * MODE_FACTOR[sup.mode] * (1.0 + rnd(0.0, 0.002))
                closed = self.relay_closed[p]
                v = v_src
                p_tot = q_tot = 0.0
                harm_sq = 0.0
                # Two passes: the load current causes a drop across the source impedance,
                # and resistive loads depend on the resulting voltage.
                for _ in range(2):
                    p_tot = q_tot = harm_sq = 0.0
                    if closed and v_src > 1.0:
                        for a in self.appliances.values():
                            if a.phase != p or not a.drawing(now):
                                continue
                            pw = a.power_at(v) * (1.0 + rnd(0.0, 0.01))
                            q = pw * math.tan(math.acos(a.pf))
                            i_fund = math.hypot(pw, q) / max(v, 1.0)
                            harm_sq += (i_fund * a.thd / 100.0) ** 2
                            p_tot += pw
                            q_tot += q
                        if sup.custom_kw:
                            pw = sup.custom_kw * 1000.0
                            pf = min(max(sup.custom_pf, 0.05), 1.0)
                            p_tot += pw
                            if pw > 0:  # loads draw reactive power; inverters export at ~unity PF
                                q_tot += pw * math.tan(math.acos(pf))
                    s_fund = math.hypot(p_tot, q_tot)
                    i_fund = s_fund / max(v, 1.0) if v_src > 1.0 else 0.0
                    v = max(v_src - i_fund * SOURCE_RESISTANCE_OHM * (1 if p_tot >= 0 else -1), 0.0)
                i_harm = math.sqrt(harm_sq)
                i_rms = math.hypot(i_fund, i_harm)
                results[p] = PhaseTruth(
                    voltage=v if v_src > 1.0 else 0.0,
                    current=i_rms,
                    active_w=p_tot,
                    reactive_var=q_tot,
                    apparent_va=(v * i_rms) if v_src > 1.0 else 0.0,
                    pf=(p_tot / (v * i_rms)) if v * i_rms > 1e-6 else 0.0,
                    voltage_thd=0.0,
                    current_thd=(100.0 * i_harm / i_fund) if i_fund > 1e-6 else 0.0,
                    frequency=(self.grid.frequency + self._freq_drift) if v_src > 1.0 else 0.0,
                    relay_closed=closed,
                )

            # Loose neutral: the star point floats towards the heavily loaded phases, so the
            # heavily loaded phase sees under-voltage and the lightly loaded ones over-voltage.
            sev = min(max(self.grid.loose_neutral, 0.0), 1.0)
            if sev > 0 and supply_up_any:
                currents = [results[p].current for p in PHASES]
                mean_i = max(sum(currents) / 3.0, 0.5)
                for p in PHASES:
                    imbalance = (results[p].current - mean_i) / mean_i
                    factor = min(max(1.0 - 0.35 * sev * imbalance, 0.55), 1.45)
                    r = results[p]
                    if r.voltage > 0:
                        r.voltage *= factor
                        r.apparent_va = r.voltage * r.current

            # Voltage distortion: grid background + the drop that harmonic currents cause.
            for p in PHASES:
                r = results[p]
                if r.voltage > 0:
                    i_harm = r.current * (r.current_thd / 100.0) / math.sqrt(1 + (r.current_thd / 100.0) ** 2)
                    r.voltage_thd = max(self.grid.voltage_thd + 100.0 * i_harm * SOURCE_RESISTANCE_OHM / r.voltage
                                        + rnd(0.0, 0.05), 0.0)

            # Neutral current = phasor sum of fundamentals + triplen harmonics (which add up).
            phasor = 0j
            triplen = 0.0
            for p in PHASES:
                r = results[p]
                if r.current <= 0:
                    continue
                thd = r.current_thd / 100.0
                i_fund = r.current / math.sqrt(1 + thd * thd)
                phi = math.atan2(r.reactive_var, r.active_w) if (r.active_w or r.reactive_var) else 0.0
                angle = math.radians(PHASE_ANGLE_DEG[p]) - phi
                r.current_angle_deg = math.degrees(angle)
                phasor += cmath.rect(i_fund, angle)
                triplen += i_fund * thd * 0.7
            neutral = math.hypot(abs(phasor), triplen) * (1.0 - sev)

            # Ground-truth energy (integrated here, at the simulation rate).
            prev = self.snapshot.phases
            for p in PHASES:
                r = results[p]
                r.energy_import_wh = prev[p].energy_import_wh + max(r.active_w, 0.0) * dt / 3600.0
                r.energy_export_wh = prev[p].energy_export_wh + max(-r.active_w, 0.0) * dt / 3600.0

            self.snapshot = Snapshot(phases=results, neutral_current=neutral, timestamp=now)
            return self.snapshot

    # ------------------------------------------------------------------ controls
    def set_relay(self, phase: str, closed: bool) -> None:
        with self.lock:
            self.relay_closed[phase] = closed

    def set_appliance(self, appliance_id: str, on: bool) -> None:
        with self.lock:
            self.appliances[appliance_id].on = on

    def update_phase(self, phase: str, **changes) -> None:
        with self.lock:
            sup = self.supply[phase]
            for k, v in changes.items():
                if v is not None and hasattr(sup, k):
                    setattr(sup, k, v)

    def update_grid(self, **changes) -> None:
        with self.lock:
            for k, v in changes.items():
                if v is not None and hasattr(self.grid, k):
                    setattr(self.grid, k, v)

    def reset_truth_energy(self) -> None:
        with self.lock:
            for r in self.snapshot.phases.values():
                r.energy_import_wh = r.energy_export_wh = 0.0

    def apply_scenario(self, name: str) -> None:
        """Preset situations that are handy for demos and for testing the firmware."""
        with self.lock:
            for p in PHASES:
                self.supply[p] = PhaseSupply()
            self.grid = GridSettings()
            on = {
                "normal": {"r_lights", "r_fridge", "r_fans", "y_tv", "b_chargers"},
                "evening_peak": {"r_lights", "r_fridge", "r_fans", "y_tv", "y_microwave", "b_ac", "b_washer", "b_chargers"},
                "night": {"r_fridge", "b_chargers"},
                "imbalanced": {"r_lights", "y_geyser", "y_microwave", "y_tv", "b_chargers"},
            }
            if name in on:
                for a in self.appliances.values():
                    a.on = a.id in on[name]
            elif name == "brownout":
                for p in PHASES:
                    self.supply[p].mode = "sag"
            elif name == "phase_loss_y":
                self.supply["Y"].mode = "outage"
            elif name == "blackout":
                for p in PHASES:
                    self.supply[p].mode = "outage"
            elif name == "loose_neutral":
                for a in self.appliances.values():
                    a.on = a.id in on["imbalanced"]
                self.grid.loose_neutral = 0.8
            elif name == "solar_export":
                self.supply["R"].custom_kw = -2.5
            elif name == "reversed_ct":
                self.supply["B"].ct_reversed = True
            elif name == "harmonics":
                self.grid.voltage_thd = 7.5
                for a in self.appliances.values():
                    a.on = a.kind == "electronic"
            else:
                raise KeyError(name)

    def describe(self) -> dict:
        with self.lock:
            snap = self.snapshot
            return {
                "timestamp": snap.timestamp,
                "neutral_current": snap.neutral_current,
                "phases": {p: asdict(r) for p, r in snap.phases.items()},
                "supply": {p: asdict(s) for p, s in self.supply.items()},
                "grid": asdict(self.grid),
                "relays": dict(self.relay_closed),
                "appliances": [asdict(a) | {"drawing": a.drawing(time.time()) and self.relay_closed[a.phase]
                                            and self.supply[a.phase].mode != "outage"}
                               for a in self.appliances.values()],
            }
