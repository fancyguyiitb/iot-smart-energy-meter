"""End-to-end check against a running local stack (python scripts/run_local.py).

Signs up with a fresh claim code, reads live data, switches a relay through the cloud
path and confirms the *physical* (virtual) relay and the measured current respond, and
probes the security fixes. Exit code 0 = all checks passed.

    python scripts/e2e_check.py
"""

from __future__ import annotations

import asyncio
import os
import secrets
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import websockets

ROOT = Path(__file__).resolve().parents[1]
SERVER = "http://127.0.0.1:8000"
BOARD = "http://127.0.0.1:9000"
failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    failures += not ok
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + detail if detail else ''}")


def claim_code() -> str:
    out = subprocess.run([sys.executable, "claim.py"], cwd=ROOT / "src" / "RPi", capture_output=True, text=True, check=True)
    return out.stdout.splitlines()[0]


def main() -> None:
    s = requests.Session()
    # ---- security probes (no credentials)
    check("fetch-all endpoint removed", s.get(f"{SERVER}/api/fetch-all").status_code == 404)
    check("ingest rejects missing device key", s.post(f"{SERVER}/api/write-data", json=[{}]).status_code == 401)
    check("remote-control requires login",
          s.post(f"{SERVER}/remote-control", json={"phase": "R", "command": "off"}).status_code == 401)
    check("latest-values requires login", s.get(f"{SERVER}/api/latest-values").status_code == 401)

    async def ws_bad_key() -> bool:
        try:
            async with websockets.connect(f"ws://127.0.0.1:8000/ws",
                                          additional_headers={"X-Device-Id": "meter-001", "X-Device-Key": "wrong"}):
                return False
        except Exception:
            return True
    check("WebSocket rejects a forged device", asyncio.run(ws_bad_key()))

    # ---- sign-up with a one-time code (or log in if the meter is already claimed)
    code = claim_code()
    user, pw = f"e2e_{secrets.token_hex(3)}", "correct-horse-battery"
    r = s.post(f"{SERVER}/auth/sign-up", json={"username": user, "password": pw, "claim_code": code})
    claimed_here = r.status_code == 201
    if r.status_code == 409 and "already registered" in r.text:
        check("re-registering a claimed meter is refused", True)
        user, pw = os.getenv("E2E_USER", ""), os.getenv("E2E_PASS", "")
        if not user:
            print("The meter already has an owner. Re-run with E2E_USER / E2E_PASS of that account.")
            sys.exit(2)
        r = s.post(f"{SERVER}/auth/login", json={"username": user, "password": pw})
    else:
        check("sign-up with claim code", claimed_here, r.text[:200])
        r2 = s.post(f"{SERVER}/auth/sign-up", json={"username": user + "x", "password": pw, "claim_code": code})
        check("claim code is single-use", r2.status_code == 400, r2.text[:120])
    token = r.json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}
    try:
        run_authenticated(s, auth, user, pw)
    finally:
        if claimed_here:  # leave the meter unclaimed so a person can register it
            s.post(f"{SERVER}/auth/release-device/meter-001", headers=auth)

    print(f"\n{'ALL CHECKS PASSED' if not failures else f'{failures} CHECK(S) FAILED'}")
    sys.exit(1 if failures else 0)


def run_authenticated(s: requests.Session, auth: dict, user: str, pw: str) -> None:
    check("login works", s.post(f"{SERVER}/auth/login", json={"username": user, "password": pw}).status_code == 200)
    check("wrong password rejected",
          s.post(f"{SERVER}/auth/login", json={"username": user, "password": "nope-nope-nope"}).status_code == 401)
    check("cannot read someone else's device",
          s.get(f"{SERVER}/api/latest-values?device_id=other-meter", headers=auth).status_code == 404)

    # ---- data path
    latest = s.get(f"{SERVER}/api/latest-values", headers=auth).json()
    check("latest values for R/Y/B/Neutral", all(p in latest for p in ("R", "Y", "B", "Neutral")), str(list(latest)))
    check("data is fresh (< 15 s)", latest.get("R", {}).get("age_s", 999) < 15, str(latest.get("R", {}).get("age_s")))
    truth = s.get(f"{BOARD}/api/state").json()["phases"]
    for p in ("R", "Y", "B"):
        tv, mv = truth[p]["voltage"], latest[p]["voltage_rms"]
        check(f"phase {p} voltage matches the wires (±3 V)", abs(tv - mv) < 3, f"true {tv:.1f} V, measured {mv:.1f} V")
    series = s.get(f"{SERVER}/api/series?fields=power_watt,voltage_rms&every=10", headers=auth).json()
    pts = len(series.get("R", []))
    check("series has distinct timestamps (no batch collapse)", pts >= 2, f"{pts} buckets for R")
    en = s.get(f"{SERVER}/analytics/energy?phase=R", headers=auth).json()
    check("energy analytics returns consumption", en["analytics_data"]["consumed_kwh"] >= 0,
          f"{en['analytics_data']['consumed_kwh']:.5f} kWh")

    # ---- relay round trip: app -> server -> WebSocket -> firmware -> GPIO -> board
    switched_at = datetime.now(timezone.utc)
    r = s.post(f"{SERVER}/remote-control", headers=auth, json={"phase": "Y", "command": "off"})
    check("relay OFF confirmed by device", r.status_code == 200 and r.json()["relays"]["Y"] == "off", r.text[:200])
    time.sleep(0.5)
    check("board relay Y is open", s.get(f"{BOARD}/api/state").json()["relays"]["Y"] is False)
    # The cloud sees readings one sync batch later (SYNC_INTERVAL_S, 10 s by default).
    deadline = time.time() + 30
    y = {}
    while time.time() < deadline:
        y = s.get(f"{SERVER}/api/latest-values", headers=auth).json()["Y"]
        if datetime.fromisoformat(y["timestamp"]) > switched_at + timedelta(seconds=1.5):
            break
        time.sleep(1)
    check("measured current on Y drops to ~0", y.get("current_rms", 1) < 0.05, f"{y.get('current_rms', -1):.3f} A")
    r = s.post(f"{SERVER}/remote-control", headers=auth, json={"phase": "Y", "command": "on"})
    check("relay ON confirmed by device", r.status_code == 200 and r.json()["relays"]["Y"] == "on", r.text[:200])
    hist = s.get(f"{SERVER}/remote-control/history", headers=auth).json()
    check("relay commands are audit-logged", len(hist) >= 2 and hist[0]["username"] == user)


if __name__ == "__main__":
    main()
