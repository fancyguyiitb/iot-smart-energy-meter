"""3-phase load-balancing advisor.

A 3-phase home with most of its load on one phase pays for it: more neutral current,
more losses and voltage drop on that phase, and a higher chance of tripping it while
the others sit idle. Only a 3-phase meter can see this - and suggest a fix.

1. **Profile.** Average current per phase for each hour of the day, from the hourly
   rollups over the last N days. Unbalance uses the NEMA definition:
   max deviation from the mean phase current / mean phase current.
2. **Find movable loads** (lightweight appliance detection). Power steps on each phase
   (a jump of at least 400 W that holds for 30 s) are paired into ON/OFF events, and events
   of similar size are clustered: "~1.5 kW on Y, usually 21:00-01:00, 13 times in 14 days".
   Small or always-on loads (fridge, lights) don't form steps and are ignored.
3. **Simulate.** For each cluster and each other phase, recompute the unbalance and
   the neutral current *while that load runs* if it were wired to the other phase.
   Recommend moves that cut unbalance by at least 5 percentage points.

Heuristic by design: overlapping appliances on one phase can merge or split clusters.
That's why every recommendation shows the evidence (size, hours, occurrences).
"""

from __future__ import annotations

import cmath
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from zoneinfo import ZoneInfo

from config import settings
from storage import get_store

PHASES = ("R", "Y", "B")
NOMINAL_V = 230.0
MIN_STEP_W = 400.0
SETTLE_POINTS = 3  # 3 x 10 s samples = the new level must hold for 30 s
STEP_RESOLUTION_S = 10
MIN_IMPROVEMENT_PTS = 5.0
TZ = ZoneInfo(settings.timezone)


def unbalance_pct(currents: dict[str, float]) -> float | None:
    vals = [currents.get(p, 0.0) or 0.0 for p in PHASES]
    mean = sum(vals) / 3
    if mean < 0.5:  # practically no load: unbalance is meaningless
        return None
    return max(abs(v - mean) for v in vals) / mean * 100


def neutral_estimate(currents: dict[str, float]) -> float:
    """Phasor sum of the phase currents (unity power factor approximation)."""
    angle = {"R": 0.0, "Y": -2 * math.pi / 3, "B": 2 * math.pi / 3}
    return abs(sum(cmath.rect(currents.get(p, 0.0) or 0.0, angle[p]) for p in PHASES))


# ---------------------------------------------------------------------- step detection
def detect_steps(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """[(epoch, watts)] at regular resolution -> [(epoch, delta_watts)] of sustained steps."""
    steps = []
    i = SETTLE_POINTS
    while i < len(points) - SETTLE_POINTS:
        if abs(points[i][1] - points[i - 1][1]) >= MIN_STEP_W * 0.6:
            before = median(p[1] for p in points[i - SETTLE_POINTS:i])
            after = median(p[1] for p in points[i:i + SETTLE_POINTS])
            if abs(after - before) >= MIN_STEP_W and points[i][0] - points[i - 1][0] <= 3 * STEP_RESOLUTION_S:
                steps.append((points[i][0], after - before))
                i += SETTLE_POINTS
                continue
        i += 1
    return steps


def pair_events(steps: list[tuple[float, float]], max_duration_s: float = 6 * 3600) -> list[dict]:
    """Match each ON step with the next OFF step of similar size (+-30 %)."""
    events, used = [], set()
    for i, (t_on, d_on) in enumerate(steps):
        if d_on <= 0:
            continue
        for j in range(i + 1, len(steps)):
            t_off, d_off = steps[j]
            if t_off - t_on > max_duration_s:
                break
            if j not in used and d_off < 0 and abs(-d_off - d_on) <= 0.3 * d_on:
                used.add(j)
                events.append({"kw": (d_on - d_off) / 2 / 1000, "start": t_on, "end": t_off})
                break
    return events


def cluster_events(events: list[dict], days: float) -> list[dict]:
    clusters: list[dict] = []
    for ev in sorted(events, key=lambda e: e["kw"]):
        for c in clusters:
            if abs(ev["kw"] - c["kw"]) <= 0.2 * c["kw"]:
                c["events"].append(ev)
                c["kw"] = median(e["kw"] for e in c["events"])
                break
        else:
            clusters.append({"kw": ev["kw"], "events": [ev]})
    out = []
    for c in clusters:
        if len(c["events"]) < 2:
            continue
        on_minutes = defaultdict(float)  # minutes "on" per local hour of day
        for ev in c["events"]:
            t = ev["start"]
            while t < ev["end"]:
                nxt = min(ev["end"], (math.floor(t / 3600) + 1) * 3600)
                on_minutes[datetime.fromtimestamp(t, TZ).hour] += (nxt - t) / 60
                t = nxt
        out.append({
            "kw": round(c["kw"], 2),
            "occurrences": len(c["events"]),
            "avg_duration_min": round(sum(e["end"] - e["start"] for e in c["events"]) / len(c["events"]) / 60),
            # expected fraction of each hour the load is on
            "hour_share": {h: min(m / (60 * max(days, 1)), 1.0) for h, m in on_minutes.items()},
        })
    return out


def hours_label(hours: list[int]) -> str:
    """[21, 22, 23, 0] -> '21:00-01:00' (longest run, wrapping midnight)."""
    if not hours:
        return ""
    hs = sorted(set(hours))
    runs, run = [], [hs[0]]
    for h in hs[1:]:
        if h == run[-1] + 1:
            run.append(h)
        else:
            runs.append(run)
            run = [h]
    runs.append(run)
    if len(runs) > 1 and runs[0][0] == 0 and runs[-1][-1] == 23:
        runs[0] = runs.pop() + runs[0]
    best = max(runs, key=len)
    return f"{best[0]:02d}:00-{(best[-1] + 1) % 24:02d}:00"


# ---------------------------------------------------------------------- analysis
def hourly_profile(device_id: str, days: int) -> tuple[dict[int, dict[str, float]], float]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    series = get_store().series(device_id, start, end, ["current_rms", "power_watt"], None, 3600)
    sums = defaultdict(lambda: defaultdict(float))
    counts = defaultdict(lambda: defaultdict(int))
    first = None
    for p in (*PHASES, "Neutral"):
        for row in series.get(p, []):
            t = datetime.fromisoformat(row["timestamp"])
            first = t if first is None or t < first else first
            h = t.astimezone(TZ).hour
            sums[h][p] += row["current_rms"] or 0.0
            counts[h][p] += 1
    profile = {h: {p: sums[h][p] / counts[h][p] for p in counts[h]} for h in sums}
    span_days = (end - first).total_seconds() / 86400 if first else 0.0
    return profile, span_days


def movable_loads(device_id: str, days: int) -> dict[str, list[dict]]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=min(days, settings.raw_retention_days))
    series = get_store().series(device_id, start, end, ["power_watt"], None, STEP_RESOLUTION_S)
    out = {}
    for p in PHASES:
        pts = [(datetime.fromisoformat(r["timestamp"]).timestamp(), r["power_watt"] or 0.0) for r in series.get(p, [])]
        span = (pts[-1][0] - pts[0][0]) / 86400 if len(pts) > 1 else 0
        out[p] = cluster_events(pair_events(detect_steps(pts)), span)
    return out


def balance_report(device_id: str, days: int = 14) -> dict:
    profile, span = hourly_profile(device_id, days)
    by_hour = {h: unbalance_pct(c) for h, c in profile.items()}
    valid = {h: u for h, u in by_hour.items() if u is not None}
    totals = {p: sum(profile[h].get(p, 0.0) for h in profile) for p in PHASES}
    total = sum(totals.values()) or 1.0
    report = {
        "days_of_data": round(span, 1),
        "average_unbalance_pct": round(sum(valid.values()) / len(valid), 1) if valid else None,
        "worst_hour": (f"{max(valid, key=valid.get):02d}:00" if valid else None),
        "worst_hour_unbalance_pct": round(max(valid.values()), 1) if valid else None,
        "phase_share_pct": {p: round(100 * totals[p] / total, 1) for p in PHASES},
        "average_neutral_a": round(sum(profile[h].get("Neutral", 0.0) for h in profile) / max(len(profile), 1), 2),
        "unbalance_by_hour": {f"{h:02d}": round(u, 1) for h, u in sorted(valid.items())},
        "recommendations": [],
        "loads": [],
    }
    if not profile:
        return report

    candidates = []
    for phase, clusters in movable_loads(device_id, days).items():
        for c in clusters:
            hours = [h for h, w in c["hour_share"].items() if w >= 0.05 and h in profile]
            report["loads"].append({"phase": phase, "kw": c["kw"], "occurrences": c["occurrences"],
                                    "avg_duration_min": c["avg_duration_min"], "usual_hours": hours_label(hours)})
            if hours:
                candidates.append({"phase": phase, "cluster": c, "hours": hours})

    # Greedy: pick the single best move, apply it to the profile, then re-evaluate the rest.
    # (Judging moves independently could recommend two moves that together overload a phase.)
    profile = {h: dict(v) for h, v in profile.items()}
    for _ in range(3):
        heaviest = max(PHASES, key=lambda p: sum(profile[h].get(p, 0.0) for h in profile))
        best = None
        for cand in candidates:
            for target in PHASES:
                # A circuit is rewired once and for all: never pile load onto the heaviest phase.
                if target in (cand["phase"], heaviest):
                    continue
                move = evaluate_move(profile, cand, target)
                if move and (best is None or move["gain"] > best["gain"]):
                    best = move | {"cand": cand, "target": target}
        if best is None or best["gain"] < MIN_IMPROVEMENT_PTS:
            break
        cand, c = best["cand"], best["cand"]["cluster"]
        apply_move(profile, cand, best["target"])
        candidates.remove(cand)
        report["recommendations"].append({
            "phase": cand["phase"], "target": best["target"], "kw": c["kw"], "usual_hours": hours_label(cand["hours"]),
            "occurrences": c["occurrences"],
            "unbalance_before_pct": round(best["before"]), "unbalance_after_pct": round(best["after"]),
            "neutral_before_a": round(best["neutral_before"], 1), "neutral_after_a": round(best["neutral_after"], 1),
            "text": (f"Move the ~{c['kw']:.1f} kW load on phase {cand['phase']} that usually runs "
                     f"{hours_label(cand['hours'])} to phase {best['target']}: unbalance while it runs "
                     f"{best['before']:.0f}% -> {best['after']:.0f}%, neutral current "
                     f"{best['neutral_before']:.1f} A -> {best['neutral_after']:.1f} A."),
        })
    report["overall_unbalance_after_moves_pct"] = (
        round(sum(u for u in (unbalance_pct(c) for c in profile.values()) if u is not None)
              / max(sum(1 for c in profile.values() if unbalance_pct(c) is not None), 1), 1)
        if report["recommendations"] else None)
    return report


def evaluate_move(profile: dict, cand: dict, target: str) -> dict | None:
    """Unbalance and neutral current while the load runs, before vs after moving it."""
    phase, c = cand["phase"], cand["cluster"]
    amps = c["kw"] * 1000 / NOMINAL_V
    before_u = after_u = before_n = after_n = weight = 0.0
    for h in cand["hours"]:
        w = c["hour_share"][h]
        base = dict(profile[h])
        base[phase] = max(base.get(phase, 0.0) - w * amps, 0.0)  # the hour without this load
        with_here = dict(base)
        with_here[phase] += amps  # while it runs, where it is now
        moved = dict(base)
        moved[target] = moved.get(target, 0.0) + amps  # while it runs, on the other phase
        ub, ua = unbalance_pct(with_here), unbalance_pct(moved)
        if ub is None or ua is None:
            continue
        before_u += w * ub
        after_u += w * ua
        before_n += w * neutral_estimate(with_here)
        after_n += w * neutral_estimate(moved)
        weight += w
    if weight == 0:
        return None
    return {"before": before_u / weight, "after": after_u / weight, "gain": (before_u - after_u) / weight,
            "neutral_before": before_n / weight, "neutral_after": after_n / weight}


def apply_move(profile: dict, cand: dict, target: str) -> None:
    """Shift the load's average contribution from its phase to the target in every hour."""
    amps = cand["cluster"]["kw"] * 1000 / NOMINAL_V
    for h, w in cand["cluster"]["hour_share"].items():
        if h in profile:
            profile[h][cand["phase"]] = max(profile[h].get(cand["phase"], 0.0) - w * amps, 0.0)
            profile[h][target] = profile[h].get(target, 0.0) + w * amps
