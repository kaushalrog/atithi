"""Holidays and closed dates: never offered, never bookable, explained."""

import datetime as dt
import shutil

import pytest
from fastapi.testclient import TestClient

import scheduling
import server
import storage
from agent import ReceptionistAgent
from conftest import FakeLLM, open_day, open_times, DEMO_CODE

DEMO_KEY = DEMO_CODE


_REAL_READ = storage.read_client_config


def config_with(closed):
    cfg = dict(_REAL_READ("demo_clinic"))
    cfg["schedule"] = {**cfg["schedule"], "closed": closed}
    return cfg


def test_a_closed_day_offers_nothing_and_is_explained(tmp_storage, monkeypatch):
    day = open_day(); usual_time = open_times(date=day)[0]
    monkeypatch.setattr(storage, "read_client_config",
                        lambda cid: config_with([{"date": day, "reason": "Diwali"}]))
    agent = ReceptionistAgent("demo_clinic", llm=FakeLLM([]))
    res = agent.run_tool({"name": "check_availability", "args": {"date": day}})["result"]
    assert res["available_slots"] == [] and "closed" in res["note"] and "Diwali" in res["note"]
    booked = agent.run_tool({"name": "book_appointment", "args": {
        "customer_name": "Ravi", "phone": "9876543210", "service": "x",
        "date": day, "time": usual_time}})["result"]
    assert booked["status"] == "failed"                   # not bookable by any path


def test_closed_hours_remove_only_those_slots(tmp_storage):
    day = open_day(); times = open_times(date=day)
    cfg = config_with([{"date": day, "from": times[0], "to": times[2]}])
    free = scheduling.available_slots(cfg, set())[day]
    assert times[0] not in free and times[1] not in free and times[2] in free


def test_bad_closed_entries_are_refused():
    with pytest.raises(ValueError):
        scheduling.clean_closed([{"date": "21/10/2026"}])
    with pytest.raises(ValueError):
        scheduling.clean_closed([{"date": "2026-10-21", "from": "18:00", "to": "10:00"}])
    assert scheduling.clean_closed([{"date": "2026-10-21", "from": "4 PM", "to": "8 PM", "reason": " x "}]) == \
        [{"date": "2026-10-21", "from": "16:00", "to": "20:00", "reason": "x"}]


@pytest.fixture
def client(tmp_storage, monkeypatch):
    import auth
    clients = tmp_storage / "clients"
    shutil.copytree(storage.CLIENTS_DIR, clients)
    monkeypatch.setattr(storage, "CLIENTS_DIR", clients)
    monkeypatch.setattr(auth, "DB_FILE", tmp_storage / "voxagent.db")
    monkeypatch.setattr(auth, "LEGACY_USERS", tmp_storage / "no_users.json")
    monkeypatch.setattr(auth, "LEGACY_TOKENS", tmp_storage / "no_tokens.json")
    storage.clear_caches()
    return TestClient(server.app)


def test_settings_save_closed_dates_and_drop_past_ones(client):
    h = {"X-Client-Key": DEMO_KEY}
    body = client.get("/api/business/demo_clinic/settings", headers=h).json()
    future = (dt.date.today() + dt.timedelta(days=10)).isoformat()
    past = (dt.date.today() - dt.timedelta(days=3)).isoformat()
    body["closed_dates"] = [{"date": future, "reason": "Diwali"}, {"date": past}]
    res = client.put("/api/business/demo_clinic/settings", json=body, headers=h)
    assert res.status_code == 200 and res.json()["closed_dates"] == [{"date": future, "reason": "Diwali"}]
    body["closed_dates"] = [{"date": future, "from": "18:00", "to": "09:00"}]
    bad = client.put("/api/business/demo_clinic/settings", json=body, headers=h)
    assert bad.status_code == 422 and "Closed dates" in bad.json()["detail"]
