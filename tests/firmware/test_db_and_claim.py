"""Local store-and-forward DB, timestamps, energy reset and claim codes."""

from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet

import db
from config import TZ


@pytest.fixture(autouse=True)
def fresh_db():
    with db.connect() as conn:
        conn.executescript("DROP TABLE IF EXISTS power_data; DROP TABLE IF EXISTS daily_energy; "
                           "DROP TABLE IF EXISTS meter_state; DROP TABLE IF EXISTS power_events;")
    db.init_db()


def row(phase, ts, energy=0.0, **kw):
    return {"phase": phase, "voltage_rms": 230.0, "current_rms": 1.0, "active_power": 230.0,
            "reactive_power": 0.0, "apparent_power": 230.0, "energy_kwh": energy, "voltage_thd": 2.0,
            "current_thd": 5.0, "power_factor": 1.0, "voltage_freq": 50.0, "timestamp": ts, **kw}


def test_unsynced_rows_leave_as_utc():
    db.insert_samples([row("R", "2025-04-01T10:00:00.123+05:30")])
    out = db.get_unsynced_data()
    # Regression: was "...+05:30Z", which the server could never parse.
    assert out[0]["time"] == "2025-04-01T04:30:00.123+00:00"
    assert datetime.fromisoformat(out[0]["time"]) == datetime(2025, 4, 1, 4, 30, 0, 123000, tzinfo=timezone.utc)


def test_batches_are_bounded_and_oldest_first():
    base = datetime.now(TZ)
    db.insert_samples([row("R", (base + timedelta(seconds=i)).isoformat()) for i in range(30)])
    batch = db.get_unsynced_data(limit=10)
    assert len(batch) == 10
    assert [b["id"] for b in batch] == sorted(b["id"] for b in batch)


def test_prune_never_deletes_unsynced_rows():
    old = (datetime.now(TZ) - timedelta(days=10)).isoformat(timespec="milliseconds")
    db.insert_samples([row("R", old), row("Y", old)])
    first_id = db.get_unsynced_data()[0]["id"]
    db.update_row_sync_status([first_id])
    assert db.prune_synced(retention_days=3) == 1  # only the synced one
    remaining = db.get_unsynced_data()
    assert len(remaining) == 1 and remaining[0]["phase"] == "Y"


def test_last_energy_is_latest_not_max():
    db.insert_samples([row("R", "2025-04-01T10:00:00+05:30", energy=5.0)])
    db.insert_samples([row("R", "2025-04-01T10:00:01+05:30", energy=0.1)])  # after a reset
    assert db.get_last_energy("R")[0] == 0.1


def test_daily_energy_accumulates_per_day_and_phase():
    db.insert_samples([row("R", "2025-04-01T10:00:00+05:30")], {"R": 0.5, "Y": 0.0}, day="2025-04-01")
    db.insert_samples([row("R", "2025-04-01T10:00:01+05:30")], {"R": 0.25}, day="2025-04-01")
    assert db.get_daily_energy("2025-04-01", "2025-04-30")["R"] == {"2025-04-01": 0.75}


def test_energy_reset_request_is_seen_once():
    assert db.pending_energy_reset() is None
    token = db.request_energy_reset()
    assert db.pending_energy_reset() == token
    db.ack_energy_reset(token)
    assert db.pending_energy_reset() is None


def test_failure_log_keeps_last_five_per_phase():
    for i in range(8):
        db.insert_failure("R", f"2025-04-01T10:00:0{i}+05:30")
    db.insert_failure("Y", "2025-04-01T11:00:00+05:30")
    rows = db.get_failures()
    assert sum(1 for p, _ in rows if p == "R") == 5
    assert sum(1 for p, _ in rows if p == "Y") == 1


def test_claim_code_is_signed_with_device_key(monkeypatch):
    import claim

    key = Fernet.generate_key().decode()
    monkeypatch.setattr(claim, "CLAIM_KEY", key)
    code = claim.make_claim_code()
    prefix, device_id, token = code.split(":", 2)
    assert (prefix, device_id) == ("VOLTIX1", "test-meter")
    payload = Fernet(key.encode()).decrypt(token.encode(), ttl=600).decode()
    assert payload.startswith("test-meter::")
    assert claim.make_claim_code() != code  # fresh nonce every time
