"""Live lane and rollups/retention."""

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from conftest import DEVICE_HEADERS


def sample(t: datetime, watts=500.0):
    return [{"phase": p, "time": t.isoformat(), "voltage_rms": 231.0, "current_rms": 2.2, "power_watt": watts}
            for p in ("R", "Y", "B")]


# ------------------------------------------------------------------ live lane
def test_live_push_shows_up_immediately(client, auth):
    from api.live import live_hub

    live_hub.received_at.clear()
    t = datetime.now(timezone.utc)
    assert client.post("/api/live", json=sample(t, 777.0)).status_code == 401  # device auth required
    r = client.post("/api/live", json=sample(t, 777.0), headers=DEVICE_HEADERS)
    assert r.json() == {"accepted": True}
    latest = client.get("/api/latest-values", headers=auth).json()
    assert latest["R"]["power_watt"] == 777.0 and latest["R"]["age_s"] < 5  # without waiting for a sync batch


def test_live_ignores_stale_and_too_fast_pushes(client):
    from api.live import live_hub

    live_hub.received_at.clear()
    t = datetime.now(timezone.utc)
    assert client.post("/api/live", json=sample(t), headers=DEVICE_HEADERS).json()["accepted"]
    assert not client.post("/api/live", json=sample(t + timedelta(seconds=1)), headers=DEVICE_HEADERS).json()["accepted"]
    time.sleep(0.6)
    assert not client.post("/api/live", json=sample(t - timedelta(seconds=5)), headers=DEVICE_HEADERS).json()["accepted"]


def test_live_websocket_streams_to_owner_only(client, user_token):
    from api.live import live_hub
    from starlette.websockets import WebSocketDisconnect

    with client.websocket_connect("/ws/live") as ws:
        ws.send_json({"token": "forged"})
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_json()
        assert e.value.code == 4401

    live_hub.received_at.clear()
    with client.websocket_connect("/ws/live") as ws:
        ws.send_json({"token": user_token})
        assert ws.receive_json()["type"] == "hello"
        if live_hub.latest:
            ws.receive_json()  # current sample sent on connect
        client.post("/api/live", json=sample(datetime.now(timezone.utc) + timedelta(seconds=2), 123.0),
                    headers=DEVICE_HEADERS)
        msg = ws.receive_json()
        assert msg["type"] == "sample" and msg["phases"]["Y"]["power_watt"] == 123.0


# ------------------------------------------------------------------ rollups / retention
@pytest.fixture()
def store(tmp_path: Path):
    from storage.sqlite_store import SQLiteStore

    return SQLiteStore(tmp_path / "ts.db", "Asia/Kolkata", raw_retention_days=30, hourly_retention_days=400)


def readings(start: datetime, n: int, step_s: int, kwh0=0.0, kwh_step=0.001, watts=1000.0):
    from utils.models import Reading

    return [Reading.model_validate({"phase": "R", "time": (start + timedelta(seconds=i * step_s)).isoformat(),
                                    "power_watt": watts + i, "voltage_rms": 230.0,
                                    "energy_kwh": kwh0 + i * kwh_step}) for i in range(n)]


def test_hourly_and_daily_rollups(store):
    ist = timezone(timedelta(hours=5, minutes=30))
    day = (datetime.now(ist) - timedelta(days=2)).replace(hour=10, minute=0, second=0, microsecond=0)
    store.write_readings("d1", readings(day, 120, 60))  # 2 h of 1-min data, 0.001 kWh per minute
    hours, days = store.refresh_rollups()
    assert (hours, days) == (2, 1)
    hourly = store.energy_buckets("d1", day, day + timedelta(hours=2), 3600, 0)["R"]
    assert [round(h["kwh"], 6) for h in hourly] == [0.059, 0.060]  # 2nd hour includes the step across :00
    daily = store.energy_buckets("d1", day.replace(hour=0), day.replace(hour=0) + timedelta(days=1), 86400, 0)["R"]
    assert round(daily[0]["kwh"], 6) == 0.119
    assert datetime.fromisoformat(daily[0]["start"]).astimezone(ist).hour == 0  # IST midnight, not UTC


def test_late_data_rerolls_its_hour(store):
    ist = timezone(timedelta(hours=5, minutes=30))
    hour = (datetime.now(ist) - timedelta(days=1)).replace(minute=0, second=0, microsecond=0)
    store.write_readings("d1", readings(hour, 30, 60))
    store.refresh_rollups()
    store.write_readings("d1", readings(hour + timedelta(minutes=30), 30, 60, kwh0=0.030))  # backlog arrives later
    store.refresh_rollups()
    s = store.series("d1", hour, hour + timedelta(hours=1), ["power_watt"], "R", 3600)["R"]
    assert len(s) == 1
    row = store._conn().execute("SELECT samples FROM readings_hourly WHERE device_id='d1'").fetchone()
    assert row[0] == 60


def test_resend_does_not_double_count(store):
    t = datetime.now(timezone.utc) - timedelta(days=1)
    batch = readings(t, 30, 60)
    store.write_readings("d1", batch)
    store.write_readings("d1", batch)  # the device re-sent after a lost acknowledgement
    store.refresh_rollups()
    total = store._conn().execute("SELECT SUM(samples), SUM(consumed_kwh) FROM readings_hourly").fetchone()
    assert total[0] == 30 and round(total[1], 6) == 0.029


def test_retention_deletes_raw_only_after_rollup(store):
    old = datetime.now(timezone.utc) - timedelta(days=40)
    store.write_readings("d1", readings(old, 60, 60))
    raw, _ = store.apply_retention()
    assert raw == 0  # not rolled up yet -> kept
    store.refresh_rollups()
    raw, _ = store.apply_retention()
    assert raw == 60
    # Old ranges are still answerable, from the hourly rollups.
    s = store.series("d1", old - timedelta(hours=1), old + timedelta(hours=2), ["power_watt"], "R", 60)["R"]
    assert s and s[0]["power_watt"] > 0
    st = store.stats("d1", old - timedelta(hours=1), old + timedelta(hours=2), "power_watt", "R")
    assert st["count"] == 60 and st["max"] == 1059


def test_hourly_retention_keeps_daily(store):
    store.hourly_retention_s = 0  # expire hourly rollups immediately
    old = datetime.now(timezone.utc) - timedelta(days=3)
    store.write_readings("d1", readings(old, 10, 60))
    store.refresh_rollups()
    store.apply_retention()
    conn = store._conn()
    assert conn.execute("SELECT COUNT(*) FROM readings_hourly").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM readings_daily").fetchone()[0] == 1
