"""Lead follow-ups and CSV exports."""

import csv
import io

import pytest
from fastapi.testclient import TestClient

import server
import storage

DEMO_KEY = {"X-Client-Key": "VX-84KQ2N"}
SALON_KEY = {"X-Client-Key": "VX-7TPX3R"}


@pytest.fixture
def client(tmp_storage, monkeypatch):
    import auth
    monkeypatch.setattr(auth, "DB_FILE", tmp_storage / "voxagent.db")
    monkeypatch.setattr(auth, "LEGACY_USERS", tmp_storage / "no_users.json")
    monkeypatch.setattr(auth, "LEGACY_TOKENS", tmp_storage / "no_tokens.json")
    storage.save_lead("demo_clinic", "Kiran", "9998887776", "braces", "wants a price")
    storage.save_lead("demo_clinic", "=HYPERLINK(\"x\")", "+91 98765 43210", "cleaning", "")
    return TestClient(server.app)


def leads(client):
    return client.get("/api/dashboard?client_id=demo_clinic", headers=DEMO_KEY).json()["leads"]


def test_new_leads_start_as_new_and_follow_ups_are_saved(client):
    lead = next(l for l in leads(client) if l["name"] == "Kiran")
    assert (lead["status"], lead["callback_on"], lead["has_booked"]) == ("new", "", False)
    res = client.post("/api/leads/update", json={
        "client_id": "demo_clinic", "timestamp": lead["timestamp"], "phone": lead["phone"],
        "status": "called", "note": "Call after 6 pm", "callback_on": "2026-11-02"}, headers=DEMO_KEY)
    assert res.status_code == 200
    lead = next(l for l in leads(client) if l["name"] == "Kiran")
    assert (lead["status"], lead["followup_note"], lead["callback_on"]) == ("called", "Call after 6 pm", "2026-11-02")
    # Saving again updates, never duplicates.
    client.post("/api/leads/update", json={"client_id": "demo_clinic", "timestamp": lead["timestamp"],
                                           "phone": lead["phone"], "status": "booked"}, headers=DEMO_KEY)
    assert [l["status"] for l in leads(client) if l["name"] == "Kiran"] == ["booked"]


def test_bad_updates_are_refused(client):
    lead = leads(client)[0]
    base = {"client_id": "demo_clinic", "timestamp": lead["timestamp"], "phone": lead["phone"]}
    assert client.post("/api/leads/update", json={**base, "status": "maybe"}, headers=DEMO_KEY).status_code == 422
    assert client.post("/api/leads/update", json={**base, "status": "new", "callback_on": "tomorrow"},
                       headers=DEMO_KEY).status_code == 422
    assert client.post("/api/leads/update", json={**base, "phone": "000", "status": "new"},
                       headers=DEMO_KEY).status_code == 404
    assert client.post("/api/leads/update", json={**base, "status": "new"}, headers=SALON_KEY).status_code == 401


def test_a_lead_that_later_booked_is_marked(client):
    storage.reserve_booking(["2026-10-20T10:00:00", "demo_clinic", "Kiran", "+91 99988 87776",
                             "Braces consult", "2099-01-05", "10:30", "confirmed"])
    lead = next(l for l in leads(client) if l["name"] == "Kiran")
    assert lead["has_booked"] is True


def test_csv_exports_open_cleanly_in_excel(client):
    res = client.get("/api/export/leads.csv?client_id=demo_clinic", headers=DEMO_KEY)
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/csv")
    assert "attachment" in res.headers["content-disposition"]
    text = res.content.decode("utf-8-sig")                       # BOM for Excel
    rows = list(csv.DictReader(io.StringIO(text)))
    assert {r["name"] for r in rows} == {"Kiran", "'=HYPERLINK(\"x\")"}   # formula neutralised
    assert "+91 98765 43210" in {r["phone"] for r in rows}             # phone numbers untouched
    assert client.get("/api/export/bookings.csv?client_id=demo_clinic", headers=DEMO_KEY).status_code == 200
    assert client.get("/api/export/passwords.csv?client_id=demo_clinic", headers=DEMO_KEY).status_code == 404
    assert client.get("/api/export/leads.csv?client_id=demo_clinic", headers=SALON_KEY).status_code == 401
