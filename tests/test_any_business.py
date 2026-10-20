"""Atithi works for any business that takes bookings, not just clinics."""

import pytest
from fastapi.testclient import TestClient

import server
import storage
from agent import ReceptionistAgent
from conftest import FakeLLM


def test_the_prompt_names_the_business_type_and_what_customers_book(tmp_storage, monkeypatch):
    real = storage.read_client_config
    monkeypatch.setattr(storage, "read_client_config", lambda cid: {
        **(real(cid) or {}), "business_type": "restaurant", "booking_word": "table"})
    prompt = ReceptionistAgent("demo_clinic", llm=FakeLLM([])).system_prompt
    assert "restaurant" in prompt and "book tables" in prompt
    assert "diagnose" not in prompt and "the doctor does that" not in prompt


def test_old_configs_without_a_type_still_work(tmp_storage):
    prompt = ReceptionistAgent("demo_clinic", llm=FakeLLM([])).system_prompt
    assert "{" not in prompt.split("Today's date")[0]        # every slot filled
    assert "appointments" in prompt


def test_settings_save_the_type_and_refuse_odd_booking_words(tmp_storage, monkeypatch):
    import shutil
    import auth
    clients = tmp_storage / "clients"
    shutil.copytree(storage.CLIENTS_DIR, clients)          # writes go to a copy
    monkeypatch.setattr(storage, "CLIENTS_DIR", clients)
    storage.clear_caches()
    monkeypatch.setattr(auth, "DB_FILE", tmp_storage / "voxagent.db")
    monkeypatch.setattr(auth, "LEGACY_USERS", tmp_storage / "no_users.json")
    monkeypatch.setattr(auth, "LEGACY_TOKENS", tmp_storage / "no_tokens.json")
    client, key = TestClient(server.app), {"X-Client-Key": "VX-84KQ2N"}
    s = client.get("/api/business/demo_clinic/settings", headers=key).json()
    assert s["booking_word"] == "appointment"
    body = {k: v for k, v in s.items() if k in server.BusinessRequest.model_fields}
    body.update(business_type="gym", booking_word="session")
    assert client.put("/api/business/demo_clinic/settings", json=body, headers=key).status_code == 200
    s = client.get("/api/business/demo_clinic/settings", headers=key).json()
    assert (s["business_type"], s["booking_word"]) == ("gym", "session")
    body["booking_word"] = "kidney"
    assert client.put("/api/business/demo_clinic/settings", json=body, headers=key).status_code == 422
