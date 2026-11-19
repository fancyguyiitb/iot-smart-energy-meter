"""Store-and-forward: pushes unsynced local rows to the server.

Fixes compared with the original version:
* Rows go out oldest-first in bounded batches (``SYNC_BATCH_SIZE``) instead of one
  request containing *every* unsynced row, which failed forever after a long outage.
* Every request has a timeout and authenticates the device (``X-Device-Id/Key``).
* Rows are marked synced only after the server confirms it committed them (201).
* Failures back off exponentially (with jitter) instead of hammering the server.
* After a long outage, the backlog drains back-to-back instead of one batch per 10 s.

Two lanes:
* Durable lane (main loop): every reading, batched, acknowledged, retried, idempotent.
* Live lane (LiveLane thread): the newest sample every second, best effort, so the app
  is real-time without weakening any of the durable lane's guarantees. After an outage
  the live lane shows now immediately while the durable lane drains the backlog.
"""

from __future__ import annotations

import random
import threading
import time
from datetime import datetime, timezone

import requests

from config import (
    HTTP_TIMEOUT_S,
    LIVE_ENABLED,
    LIVE_INTERVAL_S,
    LIVE_MAX_AGE_S,
    SERVER_URL,
    SYNC_BATCH_SIZE,
    SYNC_INTERVAL_S,
    device_headers,
    require_identity,
)
from db import (
    count_rejected,
    count_unsynced,
    get_latest_sample,
    get_unsynced_data,
    get_unsynced_events,
    init_db,
    mark_events_synced,
    store_rejected,
    update_row_sync_status,
)
from sprint import Logger

BASE_URL = f"{SERVER_URL}/api/write-data"
EVENTS_URL = f"{SERVER_URL}/api/write-events"
LIVE_URL = f"{SERVER_URL}/api/live"
# Set by the live lane when the server becomes reachable again, so the durable lane stops
# backing off and drains the backlog at once (backoff could otherwise wait up to 5 min).
network_back = threading.Event()
MAX_BACKOFF_S = 300

l = Logger.get_instance(debug=True)


def _post(url: str, payload: list[dict]) -> dict | None:
    """POST a batch. Returns the server's JSON reply if it committed the batch, else None."""
    try:
        response = requests.post(url, json=payload, headers=device_headers(), timeout=HTTP_TIMEOUT_S)
    except requests.exceptions.RequestException as e:
        l.eprint(f"Error sending data to server: {e}")
        return None
    if response.status_code == 201:
        try:
            return response.json()
        except ValueError:
            return {}
    l.eprint(f"Server rejected batch: HTTP {response.status_code} {response.text[:300]}")
    return None


def send_data_to_server(data: list[dict]) -> bool:
    """Kept for compatibility: True only if the server committed the batch."""
    return _post(BASE_URL, data) is not None


def sync_events() -> bool:
    """Upload power-failure events (start, and end once the supply is back)."""
    events = get_unsynced_events()
    if not events:
        return True
    ids = [e.pop("id") for e in events]
    if _post(EVENTS_URL, events) is None:
        return False
    mark_events_synced(ids, events)
    l.iprint(f"Synced {len(events)} power event(s)")
    return True


def proc() -> bool | None:
    """Sync one batch. Returns True if a batch was sent, None if nothing to send, False on failure."""
    events_ok = sync_events()
    data = get_unsynced_data(limit=SYNC_BATCH_SIZE)
    if not data:
        return None if events_ok else False
    row_ids = [row.pop("id") for row in data]
    reply = _post(BASE_URL, data)
    if reply is None:
        return False
    rejected = {r["index"]: r.get("error", "") for r in reply.get("rejected", []) if 0 <= r.get("index", -1) < len(data)}
    if rejected:
        # Retrying a malformed row can never succeed; keep it locally instead of losing it.
        for i in rejected:
            data[i]["id"] = row_ids[i]
        store_rejected(data, rejected)
        l.eprint(f"Server rejected {len(rejected)} row(s); kept in rejected_data "
                 f"({count_rejected()} total). First error: {next(iter(rejected.values()))}")
    update_row_sync_status(row_ids)
    l.iprint(f"Synced {len(row_ids) - len(rejected)} rows ({data[0]['time']} .. {data[-1]['time']})")
    return events_ok  # readings went through; a failed event upload still triggers backoff


class LiveLane:
    """Best-effort push of the newest sample every LIVE_INTERVAL_S, on its own thread.

    Independent of the durable lane by design: its own HTTP session, short timeout, no
    retries of old samples, no buffering. When the server is unreachable it slows down
    (and logs once) instead of piling up requests; the durable lane is never blocked or
    backed off by it. Samples older than LIVE_MAX_AGE_S (sampler stopped, clock jump)
    aren't pushed, so the app never shows stale data as "live".
    """

    def __init__(self) -> None:
        self.session = requests.Session()
        self.last_sent_id: int | None = None
        self.failing = False
        self.stop = threading.Event()

    def push_once(self) -> bool | None:
        """True = pushed, False = failed, None = nothing new to push."""
        latest = get_latest_sample()
        if not latest or latest[0] == self.last_sent_id:
            return None
        newest_id, rows = latest
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(rows[0]["time"])).total_seconds()
        if age > LIVE_MAX_AGE_S:
            return None
        for r in rows:
            r.pop("id", None)
        try:
            response = self.session.post(LIVE_URL, json=rows, headers=device_headers(), timeout=2)
            ok = response.status_code == 200
        except requests.RequestException:
            ok = False
        if ok:
            self.last_sent_id = newest_id
            if self.failing:
                l.iprint("Live lane restored")
                network_back.set()
            self.failing = False
        elif not self.failing:
            l.eprint("Live lane unavailable; readings still go through the durable sync")
            self.failing = True
        return ok

    def run(self) -> None:
        while not self.stop.is_set():
            self.push_once()
            self.stop.wait(LIVE_INTERVAL_S * (5 if self.failing else 1))


def main() -> None:
    require_identity()
    init_db()
    l.iprint(f"Sync started -> {BASE_URL} ({count_unsynced()} rows pending)")
    if LIVE_ENABLED:
        threading.Thread(target=LiveLane().run, name="live-lane", daemon=True).start()
        l.iprint(f"Live lane started -> {LIVE_URL} (every {LIVE_INTERVAL_S:g} s)")
    failures = 0
    while True:
        result = proc()
        if result is False:
            failures += 1
            delay = min(SYNC_INTERVAL_S * 2 ** (failures - 1), MAX_BACKOFF_S) * random.uniform(0.8, 1.2)
            l.eprint(f"Sync failed ({failures} in a row); retrying in {delay:.0f} s")
            if network_back.wait(delay):  # the live lane saw the server again: retry now
                network_back.clear()
                l.iprint("Server reachable again; retrying sync now")
            continue
        failures = 0
        if result is True and count_unsynced() >= SYNC_BATCH_SIZE:
            continue  # backlog: drain it without waiting
        time.sleep(SYNC_INTERVAL_S)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
