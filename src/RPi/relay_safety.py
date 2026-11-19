"""Fail-safe relay control, enforced on the meter itself.

Remote switching of a household supply is safety-critical and runs over an unreliable
network, so the meter - not the cloud or the app - has the final say:

* **Closed-loop verification.** After opening a relay the meter checks, with its own
  current sensor, that current actually stopped. If it didn't, the contacts are welded:
  the command is reported as failed with the measured current, and the phase is flagged.
  The same check runs continuously, so contacts that weld later are caught too.
* **Interlocks** (reported to the app with the reason):
  - minimum off-time before switching back ON (compressors in ACs and fridges are
    damaged by rapid restarts);
  - anti-chatter: at most N switches per phase per window;
  - no switching ON into an abnormal supply (sag, swell, outage);
  - local overcurrent trip, independent of the cloud.
* **Fail-safe direction.** Switching OFF is always allowed. Switching ON without fresh
  measurements is allowed but reported as unverified, so a crashed sampler can't leave a
  house without power.
* State (on/off, reasons, last switch-off, recent switches) is persisted, so interlocks
  survive a restart and the relay never changes state on boot.

Everything external (GPIO, clock, readings) is injected, so the logic is unit-tested
without hardware.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from fileutil import atomic_write_text


@dataclass
class Limits:
    min_off_time_s: float = 180
    max_switches: int = 6
    switch_window_s: float = 600
    trip_current_a: float = 32
    trip_delay_s: float = 2
    supply_min_v: float = 195
    supply_max_v: float = 253
    verify_off_current_a: float = 0.05
    verify_timeout_s: float = 3
    live_max_age_s: float = 3


@dataclass
class PhaseState:
    on: bool = True
    reason: str | None = None
    since: str | None = None
    last_off: float | None = None  # wall-clock epoch
    switches: list[float] = field(default_factory=list)
    welded: bool = False


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


class RelayController:
    def __init__(self, phases, set_pin: Callable[[str, bool], None], read_live: Callable[[], dict | None],
                 state_path: Path, limits: Limits | None = None, clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep):
        self.phases = tuple(phases)
        self.set_pin = set_pin
        self.read_live = read_live  # -> {"epoch", "voltage": {R:..}, "current": {R:..}} or None
        self.state_path = state_path
        self.limits = limits or Limits()
        self.clock, self.sleep = clock, sleep
        self.lock = threading.RLock()
        self.events: list[dict] = []  # trips / welding detected, waiting to be reported
        self._over_since: dict[str, float] = {}
        self._stuck_since: dict[str, float] = {}
        self.state = self._load()

    # ------------------------------------------------------------------ persistence
    def _load(self) -> dict[str, PhaseState]:
        try:
            saved = json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            saved = {}
        out = {}
        for p in self.phases:
            v = saved.get(p, True)
            if isinstance(v, bool):  # older format: {"R": true, ...}
                out[p] = PhaseState(on=v)
            else:
                known = {k: v[k] for k in PhaseState.__dataclass_fields__ if k in v}
                out[p] = PhaseState(**known)
        return out

    def _save(self) -> None:
        atomic_write_text(self.state_path, json.dumps({p: asdict(s) for p, s in self.state.items()}))

    def restore_pins(self) -> None:
        """Drive every pin to its persisted state (never toggles the supply on boot)."""
        with self.lock:
            for p, s in self.state.items():
                self.set_pin(p, s.on)

    # ------------------------------------------------------------------ measurements
    def _live(self) -> dict | None:
        live = self.read_live()
        if not live or self.clock() - float(live.get("epoch", 0)) > self.limits.live_max_age_s:
            return None
        return live

    def _wait_for_sample_after(self, t: float) -> dict | None:
        deadline = t + self.limits.verify_timeout_s
        while self.clock() < deadline:
            live = self.read_live()
            if live and float(live.get("epoch", 0)) > t + 0.2:
                return live
            self.sleep(0.1)
        return None

    # ------------------------------------------------------------------ commands
    def command(self, phase: str, on: bool, source: str = "remote") -> dict:
        """Switch one phase. Returns {"ok", "error", "verified"}; never raises for policy refusals."""
        with self.lock:
            s = self.state[phase]
            now = self.clock()
            if on and s.on:
                return {"ok": True, "error": None, "verified": True}
            if not on and not s.on and not s.welded:
                return {"ok": True, "error": None, "verified": True}
            if on:
                refusal = self._refuse_on(phase, s, now)
                if refusal:
                    return {"ok": False, "error": refusal, "verified": False}
            s.switches = [t for t in s.switches if now - t < self.limits.switch_window_s]
            if len(s.switches) >= self.limits.max_switches:
                wait = self.limits.switch_window_s - (now - s.switches[0])
                return {"ok": False, "verified": False,
                        "error": f"Phase {phase} was switched {len(s.switches)} times in "
                                 f"{self.limits.switch_window_s / 60:.0f} min; try again in {wait / 60:.0f} min"}
            self.set_pin(phase, on)
            s.switches.append(now)
            s.on = on
            s.since = _iso(now)
            s.reason = None if on else f"switched off ({source})"
            if on:
                s.welded = False
            else:
                s.last_off = now
            self._save()
        if on:
            live = self._live()
            return {"ok": True, "error": None, "verified": live is not None,
                    **({} if live else {"note": "no live readings to verify supply"})}
        return self._verify_off(phase, now)

    def _refuse_on(self, phase: str, s: PhaseState, now: float) -> str | None:
        if s.last_off is not None and now - s.last_off < self.limits.min_off_time_s:
            left = self.limits.min_off_time_s - (now - s.last_off)
            return (f"Phase {phase} was switched off {now - s.last_off:.0f} s ago. Wait {left:.0f} s "
                    f"(minimum off-time protects compressors in ACs and fridges)")
        live = self._live()
        if live is not None:
            v = float(live["voltage"].get(phase, 0))
            if not self.limits.supply_min_v <= v <= self.limits.supply_max_v:
                kind = "no supply" if v < 10 else "supply too low" if v < self.limits.supply_min_v else "supply too high"
                return (f"Not switching phase {phase} on: {kind} ({v:.0f} V, safe range "
                        f"{self.limits.supply_min_v:.0f}-{self.limits.supply_max_v:.0f} V)")
        return None

    def _verify_off(self, phase: str, t: float) -> dict:
        live = self._wait_for_sample_after(t)
        if live is None:
            return {"ok": True, "error": None, "verified": False, "note": "no live readings to confirm"}
        amps = float(live["current"].get(phase, 0))
        if amps <= self.limits.verify_off_current_a:
            return {"ok": True, "error": None, "verified": True}
        with self.lock:
            self._mark_welded(phase, amps)
        return {"ok": False, "verified": False,
                "error": f"Relay on phase {phase} did not open: still {amps:.2f} A after switching off. "
                         "Contacts may be welded - isolate the supply manually and call an electrician."}

    def _mark_welded(self, phase: str, amps: float) -> None:
        s = self.state[phase]
        if not s.welded:
            s.welded = True
            s.reason = f"relay welded: {amps:.2f} A flowing while open"
            self.events.append({"phase": phase, "action": "welded", "reason": s.reason, "at": _iso(self.clock())})
            self._save()

    # ------------------------------------------------------------------ protection loop
    def tick(self) -> None:
        """Called every ~0.5 s: overcurrent trip and continuous welded-contact detection."""
        live = self._live()
        if live is None:
            self._over_since.clear()
            self._stuck_since.clear()
            return
        now = self.clock()
        with self.lock:
            for p in self.phases:
                s = self.state[p]
                amps = float(live["current"].get(p, 0))
                if s.on and amps > self.limits.trip_current_a:
                    start = self._over_since.setdefault(p, now)
                    if now - start >= self.limits.trip_delay_s:
                        self.set_pin(p, False)
                        s.on, s.last_off, s.since = False, now, _iso(now)
                        s.switches.append(now)
                        s.reason = f"overcurrent trip: {amps:.1f} A (limit {self.limits.trip_current_a:.0f} A)"
                        self.events.append({"phase": p, "action": "trip", "reason": s.reason, "at": _iso(now)})
                        self._over_since.pop(p, None)
                        self._save()
                else:
                    self._over_since.pop(p, None)
                if not s.on and amps > self.limits.verify_off_current_a:
                    start = self._stuck_since.setdefault(p, now)
                    if now - start >= self.limits.verify_timeout_s:
                        self._mark_welded(p, amps)
                else:
                    self._stuck_since.pop(p, None)

    def take_events(self) -> list[dict]:
        with self.lock:
            out, self.events = self.events, []
            return out

    def details(self) -> dict[str, dict]:
        now = self.clock()
        live = self._live()
        out = {}
        with self.lock:
            for p, s in self.state.items():
                lockout = 0.0
                if not s.on and s.last_off is not None:
                    lockout = max(self.limits.min_off_time_s - (now - s.last_off), 0.0)
                out[p] = {"reason": s.reason, "since": s.since, "welded": s.welded,
                          "lockout_s": round(lockout), "measured_a": None if live is None else
                          round(float(live["current"].get(p, 0)), 2)}
        return out
