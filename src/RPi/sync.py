"""Store-and-forward: pushes unsynced local rows to the server.

Fixes compared with the original version:
* Rows go out oldest-first in bounded batches (``SYNC_BATCH_SIZE``) instead of one
  request containing *every* unsynced row, which failed forever after a long outage.
* Every request has a timeout and authenticates the device (``X-Device-Id/Key``).
* Rows are marked synced only after the server confirms it committed them (201).
* Failures back off exponentially (with jitter) instead of hammering the server.
* After a long outage, the backlog drains back-to-back instead of one batch per 10 s.
"""

from __future__ import annotations

import random
import time

import requests

from config import HTTP_TIMEOUT_S, SERVER_URL, SYNC_BATCH_SIZE, SYNC_INTERVAL_S, device_headers, require_identity
from db import count_unsynced, get_unsynced_data, init_db, update_row_sync_status
from sprint import Logger

BASE_URL = f"{SERVER_URL}/api/write-data"
MAX_BACKOFF_S = 300

l = Logger.get_instance(debug=True)


def send_data_to_server(data: list[dict]) -> bool:
    """POST one batch. True only if the server committed it."""
    try:
        response = requests.post(BASE_URL, json=data, headers=device_headers(), timeout=HTTP_TIMEOUT_S)
    except requests.exceptions.RequestException as e:
        l.eprint(f"Error sending data to server: {e}")
        return False
    if response.status_code == 201:
        return True
    l.eprint(f"Server rejected batch: HTTP {response.status_code} {response.text[:300]}")
    return False


def proc() -> bool | None:
    """Sync one batch. Returns True if a batch was sent, None if nothing to send, False on failure."""
    data = get_unsynced_data(limit=SYNC_BATCH_SIZE)
    if not data:
        return None
    row_ids = [row.pop("id") for row in data]
    if send_data_to_server(data):
        update_row_sync_status(row_ids)
        l.iprint(f"Synced {len(row_ids)} rows ({data[0]['time']} .. {data[-1]['time']})")
        return True
    return False


def main() -> None:
    require_identity()
    init_db()
    l.iprint(f"Sync started -> {BASE_URL} ({count_unsynced()} rows pending)")
    failures = 0
    while True:
        result = proc()
        if result is False:
            failures += 1
            delay = min(SYNC_INTERVAL_S * 2 ** (failures - 1), MAX_BACKOFF_S) * random.uniform(0.8, 1.2)
            l.eprint(f"Sync failed ({failures} in a row); retrying in {delay:.0f} s")
            time.sleep(delay)
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
