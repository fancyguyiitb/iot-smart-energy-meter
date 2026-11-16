"""B3 energy restore, B4 clock trust, B5 dead-letter, B6 outage events."""

from datetime import datetime, timedelta, timezone

import pytest

import api
import db
from clock import CLOCK_FLOOR, clock_plausible, wait_for_trusted_clock
from config import ENERGY_STATE_PATH


@pytest.fixture(autouse=True)
def fresh():
    with db.connect() as conn:
        conn.executescript("DROP TABLE IF EXISTS power_data; DROP TABLE IF EXISTS power_events; "
                           "DROP TABLE IF EXISTS rejected_data; DROP TABLE IF EXISTS daily_energy;")
    db.init_db()
    ENERGY_STATE_PATH.unlink(missing_ok=True)


def row(phase, ts, energy):
    return {"phase": phase, "voltage_rms": 230.0, "current_rms": 1.0, "active_power": 230.0,
            "apparent_power": 230.0, "energy_kwh": energy, "timestamp": ts}


# ------------------------------------------------------------------ B3 energy restore
def remote(values, ts="2025-01-01T00:00:00+00:00"):
    return {p: {"energy_kwh": v, "timestamp": ts} for p, v in zip("RYB", values)}


def test_restore_waits_for_server_when_nothing_local(monkeypatch):
    answers = [None, None, remote([5.0, 6.0, 7.0])]  # offline twice, then reachable
    monkeypatch.setattr(api, "get_remote_last_energy", lambda: answers.pop(0))
    slept = []
    restored = api.restore_energy(retry_s=60, sleep=slept.append)
    assert restored == {"R": 5.0, "Y": 6.0, "B": 7.0}  # used to be 0, 0, 0
    assert len(slept) == 2


def test_restore_gives_up_after_retry_window(monkeypatch):
    monkeypatch.setattr(api, "get_remote_last_energy", lambda: None)
    restored = api.restore_energy(retry_s=5, sleep=lambda s: None)
    assert restored == {"R": 0.0, "Y": 0.0, "B": 0.0}


def test_state_file_survives_a_lost_database(monkeypatch):
    api.save_energy_state({"R": 1.5, "Y": 2.5, "B": 3.5}, "2025-06-01T10:00:00+05:30")
    monkeypatch.setattr(api, "get_remote_last_energy", lambda: None)  # and the server is down
    assert api.restore_energy(retry_s=0, sleep=lambda s: None) == {"R": 1.5, "Y": 2.5, "B": 3.5}


def test_restore_prefers_the_newest_source(monkeypatch):
    db.insert_samples([row("R", "2025-06-01T10:00:00+05:30", 9.0)])  # local, newest
    api.save_energy_state({"R": 1.0, "Y": 2.0, "B": 3.0}, "2025-05-01T10:00:00+05:30")
    monkeypatch.setattr(api, "get_remote_last_energy", lambda: remote([4.0, 5.0, 6.0]))
    restored = api.restore_energy(retry_s=0, sleep=lambda s: None)
    assert restored["R"] == 9.0  # local DB is newest for R
    assert restored["Y"] == 2.0  # state file (May) beats server (Jan) for Y


# ------------------------------------------------------------------ B4 clock trust
def test_clock_plausibility():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert clock_plausible(now, None)
    assert not clock_plausible(CLOCK_FLOOR - timedelta(days=1), None)  # booted at 1970
    assert not clock_plausible(now, now + timedelta(hours=1))  # behind stored data
    assert clock_plausible(now, now + timedelta(seconds=2))  # within tolerance


def test_waits_until_ntp_syncs():
    states = iter([False, False, True])
    slept = []
    ok = wait_for_trusted_clock(lambda: None, timeout_s=60, log=lambda m: None,
                                synced=lambda: next(states), sleep=slept.append, poll_s=1)
    assert ok and len(slept) == 2


def test_starts_without_ntp_after_timeout_if_plausible():
    ok = wait_for_trusted_clock(lambda: None, timeout_s=3, log=lambda m: None,
                                synced=lambda: False, sleep=lambda s: None, poll_s=1)
    assert ok is False  # started anyway, flagged as not NTP-confirmed


def test_keeps_waiting_while_clock_is_behind_stored_data():
    t = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    stored = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)

    def tick(s):
        t[0] += timedelta(minutes=30)  # NTP eventually steps the clock forward

    wait_for_trusted_clock(lambda: stored, timeout_s=1, log=lambda m: None, now=lambda: t[0],
                           synced=lambda: None, sleep=tick, poll_s=1)
    assert t[0] >= stored - timedelta(seconds=5)  # never returned while behind, despite timeout


# ------------------------------------------------------------------ B5 dead letter
def test_rejected_rows_are_kept():
    rows = [{"id": 1, "phase": "R", "time": "x"}, {"id": 2, "phase": "R", "time": "y"}]
    db.store_rejected(rows, {1: "timestamp is in the future"})
    assert db.count_rejected() == 1
    with db.connect() as conn:
        src, err = conn.execute("SELECT source_id, error FROM rejected_data").fetchone()
    assert (src, err) == (2, "timestamp is in the future")


# ------------------------------------------------------------------ B6 outage events
def test_outage_event_lifecycle():
    db.insert_failure("Y", "2025-06-01T10:00:00+05:30")
    ev = db.get_unsynced_events()
    assert ev == [{"id": ev[0]["id"], "phase": "Y", "start": "2025-06-01T04:30:00.000+00:00", "end": None}]
    ids = [e.pop("id") for e in ev]
    db.mark_events_synced(ids, ev)
    assert db.get_unsynced_events() == []
    db.mark_restored("Y", "2025-06-01T10:05:00+05:30")  # supply back: re-send with an end time
    again = db.get_unsynced_events()
    assert again[0]["end"] == "2025-06-01T04:35:00.000+00:00"


def test_event_restored_while_uploading_is_resent():
    db.insert_failure("R", "2025-06-01T10:00:00+05:30")
    ev = db.get_unsynced_events()
    ids = [e.pop("id") for e in ev]
    db.mark_restored("R", "2025-06-01T10:00:30+05:30")  # happens while the upload is in flight
    db.mark_events_synced(ids, ev)
    assert len(db.get_unsynced_events()) == 1


def test_unsynced_events_are_never_pruned():
    for i in range(8):
        db.insert_failure("B", f"2025-06-01T10:00:0{i}+05:30")
    assert len(db.get_unsynced_events()) == 8  # the keep-5 rule only applies to synced events
