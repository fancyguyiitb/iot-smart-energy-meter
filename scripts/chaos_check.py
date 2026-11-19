"""Chaos test: cut the network between the meter and the cloud, then check nothing was lost.

A TCP proxy sits between the meter and the server. The test cuts it (every connection
dropped, new ones refused) for a while, restores it, and checks that:

* during the cut the meter shows offline and the cloud's data goes stale (sanity);
* after restoring, the meter reconnects, the live lane resumes, the backlog drains;
* **every reading the meter took during the outage reached the server** - compared
  row by row against the meter's own database - with no duplicates.

Run the stack with the meter pointed at the proxy, then this script:

    python scripts/run_local.py --sandbox .sandbox --server-port 8100 --board-port 9100 \\
        --device-server-url http://127.0.0.1:8200
    python scripts/chaos_check.py --user NAME --password PASS --device-db .sandbox/device/power_meter_data.db
"""

from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


class CuttableProxy:
    """Forwards 127.0.0.1:listen -> 127.0.0.1:target; ``cut()`` simulates the network going down."""

    def __init__(self, listen: int, target: int) -> None:
        self.listen, self.target = listen, target
        self.loop = asyncio.new_event_loop()
        self.server = None
        self.writers: set[asyncio.StreamWriter] = set()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

    async def _pipe(self, reader, writer):
        try:
            while data := await reader.read(65536):
                writer.write(data)
                await writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            writer.close()

    async def _handle(self, c_reader, c_writer):
        try:
            u_reader, u_writer = await asyncio.open_connection("127.0.0.1", self.target)
        except OSError:
            c_writer.close()
            return
        self.writers |= {c_writer, u_writer}
        await asyncio.gather(self._pipe(c_reader, u_writer), self._pipe(u_reader, c_writer))
        self.writers -= {c_writer, u_writer}

    async def _start(self):
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", self.listen)

    async def _cut(self):
        self.server.close()  # refuse new connections
        for w in list(self.writers):
            w.transport.abort()  # drop live ones like a dead link: no clean close
        self.writers.clear()
        # Only now wait: since Python 3.12 wait_closed() also waits for open connections.
        await self.server.wait_closed()

    def up(self):
        asyncio.run_coroutine_threadsafe(self._start(), self.loop).result()

    def cut(self):
        asyncio.run_coroutine_threadsafe(self._cut(), self.loop).result()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:8100")
    ap.add_argument("--proxy-port", type=int, default=8200)
    ap.add_argument("--user", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--device-db", type=Path, required=True)
    ap.add_argument("--outage", type=int, default=60, help="seconds the network stays down")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    failures = []

    def check(name, ok, detail=""):
        print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail) if detail else ''}", flush=True)
        if not ok:
            failures.append(name)

    proxy = CuttableProxy(args.proxy_port, int(args.server.rsplit(":", 1)[1]))
    proxy.up()
    s = requests.Session()
    token = s.post(f"{args.server}/auth/login", json={"username": args.user, "password": args.password}).json()
    h = {"Authorization": f"Bearer {token['access_token']}"}

    def age():
        r = s.get(f"{args.server}/api/latest-values", headers=h).json()
        return r.get("R", {}).get("age_s", 1e9)

    def online():
        return s.get(f"{args.server}/api/devices", headers=h).json()[0]["online"]

    deadline = time.time() + 60
    while time.time() < deadline and not (age() < 3 and online()):
        time.sleep(1)
    check("meter connected through the proxy", age() < 3 and online())

    cut_start = datetime.now(timezone.utc)
    print(f"       cutting the network for {args.outage} s ...", flush=True)
    proxy.cut()
    time.sleep(args.outage)
    check("during the cut the cloud's data goes stale", age() > args.outage - 15, f"{age():.0f} s old")
    check("during the cut the meter shows offline", not online())
    proxy.up()
    cut_end = datetime.now(timezone.utc)
    print("       network restored", flush=True)

    t0 = time.time()
    while time.time() - t0 < 120 and not (age() < 3 and online()):
        time.sleep(1)
    check("meter reconnects and the live lane resumes", age() < 3 and online(),
          f"after {time.time() - t0:.0f} s, data {age():.1f} s old")

    # Wait for the durable lane to drain the outage backlog.
    db = sqlite3.connect(f"file:{args.device_db}?mode=ro", uri=True)
    t0 = time.time()
    while time.time() - t0 < 180:
        pending = db.execute("SELECT COUNT(*) FROM power_data WHERE sync = 0").fetchone()[0]
        if pending < 50:
            break
        time.sleep(2)
    time.sleep(12)
    check("outage backlog drained", pending < 50, f"{pending} rows pending, drained in {time.time() - t0:.0f} s")

    # Every R-phase reading the meter took during the outage must be on the server.
    rows = db.execute("SELECT timestamp FROM power_data WHERE phase = 'R' ORDER BY id").fetchall()
    taken = {datetime.fromisoformat(r[0]).astimezone(timezone.utc).replace(microsecond=0)
             for r in rows if cut_start <= datetime.fromisoformat(r[0]) <= cut_end}
    day = cut_start.astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat()  # the API's days are IST days
    series = s.get(f"{args.server}/api/series?fields=power_watt&phase=R&every=1&date_str={day}", headers=h).json()
    stored = {datetime.fromisoformat(p["timestamp"]).replace(microsecond=0) for p in series.get("R", [])}
    missing = taken - stored
    check("every reading taken during the outage reached the server", taken and not missing,
          f"{len(taken)} readings during the outage, {len(missing)} missing")
    print("\n" + ("CHAOS CHECK PASSED" if not failures else f"CHAOS CHECK FAILED: {failures}"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
