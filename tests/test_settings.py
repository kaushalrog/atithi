"""Owner settings: the owner edits what onboarding created, and nothing else."""

import shutil

import pytest
import yaml
from fastapi.testclient import TestClient

import server
import storage

DEMO_KEY = "VX-84KQ2N"      # demo_clinic's code (from its YAML)
SALON_KEY = "VX-7TPX3R"     # lakshmi_beauty_salon's code


@pytest.fixture
def client(tmp_storage, monkeypatch):
    import auth
    clients = tmp_storage / "clients"
    shutil.copytree(storage.CLIENTS_DIR, clients)          # writes go to a copy
    monkeypatch.setattr(storage, "CLIENTS_DIR", clients)
    monkeypatch.setattr(auth, "DB_FILE", tmp_storage / "voxagent.db")
    monkeypatch.setattr(auth, "LEGACY_USERS", tmp_storage / "no_users.json")
    monkeypatch.setattr(auth, "LEGACY_TOKENS", tmp_storage / "no_tokens.json")
    storage.clear_caches()
    return TestClient(server.app)


def settings(client, key=DEMO_KEY, cid="demo_clinic"):
    return client.get(f"/api/business/{cid}/settings", headers={"X-Client-Key": key})


def test_settings_show_the_business_in_the_form_shape(client):
    res = settings(client)
    assert res.status_code == 200
    s = res.json()
    assert s["business_name"] and s["services"] and s["slot_days"]
    assert all(len(r) == 2 for r in s["slot_ranges"])


def test_an_owner_cannot_read_or_change_another_business(client):
    assert settings(client, key=SALON_KEY).status_code == 401
    body = settings(client).json()
    assert client.put("/api/business/demo_clinic/settings", json=body,
                      headers={"X-Client-Key": SALON_KEY}).status_code == 401


def test_saving_updates_what_the_agent_knows_and_keeps_everything_else(client):
    before = yaml.safe_load((storage.CLIENTS_DIR / "demo_clinic.yaml").read_text(encoding="utf-8"))
    body = settings(client).json()
    body["services"].append({"name": "Teeth whitening", "price": "₹4,000"})
    body["timings"] = "Mon–Sat 10 AM – 7 PM"
    body["slot_days"] = ["Mon", "Wed", "Fri"]
    body["slot_ranges"] = [["10:00", "12:00"]]
    body["slot_gap_min"] = 45
    res = client.put("/api/business/demo_clinic/settings", json=body,
                     headers={"X-Client-Key": DEMO_KEY})
    assert res.status_code == 200
    after = yaml.safe_load((storage.CLIENTS_DIR / "demo_clinic.yaml").read_text(encoding="utf-8"))
    assert {"name": "Teeth whitening", "price": "₹4,000"} in after["services"]
    assert after["timings"] == "Mon–Sat 10 AM – 7 PM"
    assert after["schedule"]["days"] == ["Mon", "Wed", "Fri"]
    assert after["schedule"]["ranges"] == [["10:00", "12:00"]]
    assert after["schedule"]["gap_min"] == 45
    for kept in ("access_key", "billing", "client_id"):
        assert after.get(kept) == before.get(kept)
    # The receptionist's next conversation uses the new details.
    from agent import ReceptionistAgent
    from conftest import FakeLLM
    assert "Teeth whitening" in ReceptionistAgent("demo_clinic", llm=FakeLLM([])).system_prompt


def test_invalid_settings_are_refused_and_nothing_is_written(client):
    path = storage.CLIENTS_DIR / "demo_clinic.yaml"
    original = path.read_text(encoding="utf-8")
    body = settings(client).json()
    for broken in ({"services": []}, {"business_name": "  "}, {"slot_days": []},
                   {"slot_ranges": [["13:00", "10:00"]]}):
        res = client.put("/api/business/demo_clinic/settings", json={**body, **broken},
                         headers={"X-Client-Key": DEMO_KEY})
        assert res.status_code == 422, broken
    assert path.read_text(encoding="utf-8") == original


def test_saving_never_mutates_the_shared_cached_config(client):
    cached = storage.read_client_config("demo_clinic")
    snapshot = yaml.safe_dump(cached)
    body = settings(client).json()
    body["timings"] = "changed"
    client.put("/api/business/demo_clinic/settings", json=body, headers={"X-Client-Key": DEMO_KEY})
    assert yaml.safe_dump(cached) == snapshot
