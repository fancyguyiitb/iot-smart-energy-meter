"""Regression tests for the server-side bug fixes (IDs refer to docs/BUGFIXES.md)."""

import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from conftest import DEVICE_HEADERS, DEVICE_ID, claim_code


def reading(t: datetime, phase="R", energy=0.0, **kw):
    return {"phase": phase, "time": t.isoformat(), "voltage_rms": 230.0, "current_rms": 2.0, "power_watt": 460.0,
            "energy_kwh": energy, **kw}


def now():
    return datetime.now(timezone.utc).replace(microsecond=0)


# ------------------------------------------------------------------ security
def test_fetch_all_is_gone(client):  # C3
    assert client.get("/api/fetch-all").status_code == 404


def test_ingest_requires_valid_device_key(client):  # C4
    assert client.post("/api/write-data", json=[reading(now())]).status_code == 401
    bad = {"X-Device-Id": DEVICE_ID, "X-Device-Key": "wrong"}
    assert client.post("/api/write-data", json=[reading(now())], headers=bad).status_code == 401


def test_user_endpoints_require_login(client):  # C4
    for path in ("/api/latest-values", "/api/devices", "/analytics/energy", "/remote-control/status"):
        assert client.get(path).status_code == 401, path
    assert client.post("/remote-control", json={"phase": "R", "command": "off"}).status_code == 401


def test_passwords_are_hashed(client, user_token):  # C7
    import config

    with sqlite3.connect(config.settings.metadata_db) as conn:
        stored = conn.execute("SELECT password_hash FROM users WHERE username = 'alice'").fetchone()[0]
    assert stored.startswith("pbkdf2_sha256$") and "correct-horse" not in stored


def test_claim_codes_expire_and_are_single_use(client, user_token):  # C6
    # The meter is already owned by alice -> a new valid code can't take it over.
    r = client.post("/auth/sign-up", json={"username": "mallory", "password": "password123", "claim_code": claim_code("n2")})
    assert r.status_code == 409
    # Replaying alice's code fails (nonce burnt) - checked before ownership.
    r = client.post("/auth/sign-up", json={"username": "mallory", "password": "password123", "claim_code": claim_code("n-alice")})
    assert r.status_code == 400
    # Expired code.
    r = client.post("/auth/sign-up", json={"username": "mallory", "password": "password123",
                                            "claim_code": claim_code("n3", age_s=3600)})
    assert r.status_code == 400 and "expired" in r.json()["detail"]
    # Garbage is a 400, not a 500.
    r = client.post("/auth/sign-up", json={"username": "mallory", "password": "password123",
                                            "claim_code": f"VOLTIX1:{DEVICE_ID}:not-a-token"})
    assert r.status_code == 400


def test_cannot_read_another_users_device(client, auth):  # IDOR
    assert client.get("/api/latest-values?device_id=someone-elses", headers=auth).status_code == 404


def test_login(client, user_token):
    assert client.post("/auth/login", json={"username": "alice", "password": "correct-horse"}).status_code == 200
    assert client.post("/auth/login", json={"username": "alice", "password": "wrong-pass"}).status_code == 401
    assert client.post("/auth/login", json={"username": "nobody", "password": "wrong-pass"}).status_code == 401


# ------------------------------------------------------------------ data correctness
def test_batch_keeps_every_timestamp(client, auth):  # C1
    t0 = now() - timedelta(minutes=30)
    batch = [reading(t0 + timedelta(seconds=i), energy=i / 1000) for i in range(10)]
    r = client.post("/api/write-data", json=batch, headers=DEVICE_HEADERS)
    assert r.status_code == 201 and r.json()["accepted"] == 10
    day = (t0 + timedelta(hours=5, minutes=30)).date()  # the API's days are IST days
    s = client.get(f"/api/series?fields=power_watt&phase=R&every=1&date_str={day}", headers=auth)
    # The old server stamped all 10 with now() -> one point survived.
    stamps = {p["timestamp"] for p in s.json()["R"]
              if t0 <= datetime.fromisoformat(p["timestamp"]) < t0 + timedelta(seconds=10)}
    assert len(stamps) == 10


def test_bad_rows_are_rejected_individually(client):  # C1 + poison-pill
    t = now()
    batch = [reading(t), {"phase": "R", "time": "2025-04-01T10:00:00.123+05:30Z"},  # the old device format
             {"phase": "R", "time": "2025-04-01T10:00:00"},  # naive
             reading(t + timedelta(days=2))]  # future
    r = client.post("/api/write-data", json=batch, headers=DEVICE_HEADERS)
    assert r.status_code == 201
    assert r.json()["accepted"] == 1 and [x["index"] for x in r.json()["rejected"]] == [1, 2, 3]


def test_ist_timestamps_are_normalised(client, auth):
    ist = timezone(timedelta(hours=5, minutes=30))
    t = (now() - timedelta(minutes=5)).astimezone(ist)
    client.post("/api/write-data", json=[reading(t, phase="Y")], headers=DEVICE_HEADERS)
    latest = client.get("/api/latest-values", headers=auth).json()
    assert datetime.fromisoformat(latest["Y"]["timestamp"]) == t


def test_energy_consumption_survives_counter_reset(client, auth):  # M1 / H6
    t0 = now() - timedelta(minutes=20)
    counter = [0.0, 0.4, 1.0, 0.0, 0.2, 0.5]  # reset after 1.0 kWh, then 0.5 kWh more
    batch = [reading(t0 + timedelta(seconds=i), phase="B", energy=e) for i, e in enumerate(counter)]
    client.post("/api/write-data", json=batch, headers=DEVICE_HEADERS)
    day = (t0 + timedelta(hours=5, minutes=30)).date()
    a = client.get(f"/analytics/energy?phase=B&date_str={day}", headers=auth).json()
    assert abs(a["analytics_data"]["consumed_kwh"] - 1.5) < 1e-9


def test_last_energy_for_device(client):
    r = client.get("/api/last-energy-data", headers=DEVICE_HEADERS)
    assert r.status_code == 200 and "R" in r.json()


# ------------------------------------------------------------------ relay control
def test_remote_control_offline_device(client, auth):
    r = client.post("/remote-control", headers=auth, json={"phase": "R", "command": "off"})
    assert r.status_code == 409


def test_forged_device_websocket_is_rejected(client):  # C5
    import pytest
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={"X-Device-Id": DEVICE_ID, "X-Device-Key": "forged"}) as ws:
            ws.receive_text()


def test_command_waits_for_device_ack(client, auth):  # M7
    with client.websocket_connect("/ws", headers=DEVICE_HEADERS) as ws:
        ws.send_json({"type": "status", "relays": {"R": "on", "Y": "on", "B": "on"}})
        result = {}
        t = threading.Thread(target=lambda: result.update(
            r=client.post("/remote-control", headers=auth, json={"phase": "Y", "command": "off"})))
        t.start()
        cmd = ws.receive_json()
        assert cmd["type"] == "command" and cmd["phase"] == "Y" and cmd["command"] == "off"
        ws.send_json({"type": "ack", "id": cmd["id"], "ok": True, "relays": {"R": "on", "Y": "off", "B": "on"}})
        t.join(5)
    assert result["r"].status_code == 200
    assert result["r"].json() == {"status": "confirmed", "relays": {"R": "on", "Y": "off", "B": "on"}}
    hist = client.get("/remote-control/history", headers=auth).json()
    assert hist[0]["command"] == "off" and hist[0]["ok"] == 1


def test_old_socket_disconnect_does_not_drop_new_one():  # H9
    import asyncio

    from api.services import DeviceHub

    class FakeWS:
        async def close(self, code=1000):
            pass

    hub = DeviceHub()
    old, new = FakeWS(), FakeWS()
    asyncio.run(hub.register("d1", old))
    asyncio.run(hub.register("d1", new))  # device reconnected
    hub.unregister("d1", old)  # the old socket's disconnect handler fires late
    assert hub.is_online("d1")
    hub.unregister("d1", new)
    assert not hub.is_online("d1")
