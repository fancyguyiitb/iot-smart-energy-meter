"""Feature 5: load-balancing advisor and bill forecast; feature 1/4 server plumbing."""

from datetime import date, datetime, timedelta

import pytest

from conftest import claim_code


# ------------------------------------------------------------------ billing maths
def test_slab_cost_is_telescopic():
    from analytics.billing import DEFAULT_TARIFF, bill_cost

    # 100 x 3.5 + 200 x 5.5 + 50 x 7.5 = 350 + 1100 + 375, plus 50 fixed
    assert bill_cost(350, DEFAULT_TARIFF)["total"] == 1875.0
    assert bill_cost(0, DEFAULT_TARIFF)["total"] == 50.0
    assert bill_cost(600, DEFAULT_TARIFF)["slabs"][-1] == {"from": 500, "to": None, "units": 100.0, "rate": 8.5, "cost": 850.0}


def test_tariff_validation():
    from analytics.billing import Tariff

    with pytest.raises(ValueError):
        Tariff(slabs=[{"upto": 100, "rate": 3}, {"upto": 50, "rate": 4}, {"upto": None, "rate": 5}])
    with pytest.raises(ValueError):
        Tariff(slabs=[{"upto": 100, "rate": 3}])  # last slab must be unlimited


def test_cycle_bounds():
    from analytics.billing import cycle_bounds

    assert cycle_bounds(date(2026, 11, 16), 1) == (date(2026, 11, 1), date(2026, 12, 1))
    assert cycle_bounds(date(2026, 11, 3), 10) == (date(2026, 10, 10), date(2026, 11, 10))
    assert cycle_bounds(date(2026, 12, 20), 15) == (date(2026, 12, 15), date(2027, 1, 15))


def test_forecast_warns_before_a_slab_is_crossed(monkeypatch):
    from analytics import billing
    from analytics.helpers import TZ

    now = datetime(2026, 11, 16, 12, 0, tzinfo=TZ)
    history = {date(2026, 11, d): 12.0 for d in range(1, 16)}  # 12 kWh a day
    history[date(2026, 11, 16)] = 6.0
    for d in range(1, 16):  # some October days for a fuller picture
        history[date(2026, 10, 15 + d)] = 12.0
    monkeypatch.setattr(billing, "daily_units", lambda device, a, b: history)
    f = billing.forecast("d", billing.DEFAULT_TARIFF, now)
    assert f["so_far"]["units"] == 186.0  # 15 x 12 + 6
    assert 350 < f["projected"]["units"] < 365  # ~12/day to the 30th
    crossing = f["warnings"][0]
    assert crossing["boundary_units"] == 300 and crossing["expected_date"] == "2026-11-25"
    assert crossing["rate_after"] == 7.5 and "26 units" not in crossing["text"]
    assert "kWh per day" in f["tip"] and f["confidence"] == "high"


# ------------------------------------------------------------------ advisor on seeded history
@pytest.fixture(scope="module")
def seeded(client):
    from cryptography.fernet import Fernet

    from seed_history import seed
    from utils.database import get_metadata_db
    from utils.security import hash_device_key

    key = Fernet.generate_key().decode()
    get_metadata_db().upsert_device("seeded-meter", hash_device_key("k"), key)
    r = client.post("/auth/sign-up", json={"username": "insight_user", "password": "insight-pass-1",
                                           "claim_code": claim_code("n-seed", key=key, device_id="seeded-meter")})
    assert r.status_code == 201
    seed("seeded-meter", days=8, step_s=30)
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_balance_finds_the_overloaded_phase(client, seeded):
    rep = client.get("/analytics/balance?days=8", headers=seeded).json()
    assert rep["days_of_data"] >= 7
    assert rep["phase_share_pct"]["Y"] == max(rep["phase_share_pct"].values())  # AC + geyser + TV on Y
    sizes = sorted(round(l["kw"], 1) for l in rep["loads"] if l["phase"] == "Y")
    assert any(1.3 <= s <= 1.7 for s in sizes) and any(1.8 <= s <= 2.2 for s in sizes)  # AC, water heater found
    rec = rep["recommendations"][0]
    assert rec["phase"] == "Y" and rec["target"] in ("R", "B")
    assert rec["unbalance_before_pct"] - rec["unbalance_after_pct"] >= 5
    assert rec["neutral_after_a"] < rec["neutral_before_a"]
    assert rec["text"].startswith("Move the ~")


def test_bill_forecast_endpoint_and_custom_tariff(client, seeded):
    f = client.get("/analytics/bill-forecast", headers=seeded).json()
    assert f["tariff_is_default"] and f["projected"]["units"] >= f["so_far"]["units"]
    tariff = {"name": "Flat", "currency": "₹", "fixed_charge": 0, "cycle_start_day": 1,
              "slabs": [{"upto": None, "rate": 10}]}
    assert client.put("/analytics/tariff", json=tariff, headers=seeded).status_code == 200
    f2 = client.get("/analytics/bill-forecast", headers=seeded).json()
    assert not f2["tariff_is_default"]
    assert f2["projected"]["total"] == pytest.approx(f2["projected"]["units"] * 10, abs=0.05)
    bad = dict(tariff, slabs=[{"upto": 100, "rate": 3}])
    assert client.put("/analytics/tariff", json=bad, headers=seeded).status_code == 422


def test_energy_analytics_report_chip_software_and_export(client, seeded):
    day = (datetime.now() - timedelta(days=3)).date()
    a = client.get(f"/analytics/energy?date_str={day}&phase=Y", headers=seeded).json()["analytics_data"]
    assert a["consumed_kwh"] > 0
    assert a["chip_vs_software_pct"] == pytest.approx(-0.2, abs=0.05)  # the seeder's software counter reads 0.2 % low
    assert a["exported_kwh"] == 0


# ------------------------------------------------------------------ feature 4 server plumbing
def test_meter_refusal_is_reported_and_trip_is_audited(client, new_user):
    import threading

    from utils.database import get_metadata_db
    from utils.security import hash_device_key

    u = new_user()
    get_metadata_db().upsert_device(u["device_id"], hash_device_key("dev-key"), "unused")
    headers = {"X-Device-Id": u["device_id"], "X-Device-Key": "dev-key"}
    with client.websocket_connect("/ws", headers=headers) as ws:
        result = {}
        t = threading.Thread(target=lambda: result.update(r=client.post(
            "/remote-control", headers=u["headers"], json={"phase": "B", "command": "on"})))
        t.start()
        cmd = ws.receive_json()
        ws.send_json({"type": "ack", "id": cmd["id"], "ok": False, "results": {"B": {"ok": False}},
                      "error": "Phase B was switched off 20 s ago. Wait 160 s", "relays": {"R": "on", "Y": "on", "B": "off"}})
        t.join(5)
        assert result["r"].status_code == 409 and "Wait 160 s" in result["r"].json()["detail"]

        ws.send_json({"type": "event", "phase": "Y", "action": "trip", "reason": "overcurrent trip: 37.0 A (limit 32 A)"})
        ws.send_json({"type": "status", "relays": {"R": "on", "Y": "off", "B": "off"},
                      "details": {"Y": {"reason": "overcurrent trip: 37.0 A (limit 32 A)", "lockout_s": 170}}})
        import time
        time.sleep(0.3)
        hist = client.get("/remote-control/history", headers=u["headers"]).json()
        assert hist[0]["command"] == "auto:trip" and "37.0 A" in hist[0]["detail"]
