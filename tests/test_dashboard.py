"""The single dashboard endpoint and its ETag (replaced 6 requests with 1)."""

import pytest
from fastapi.testclient import TestClient

import auth
import server
import storage


@pytest.fixture
def client(tmp_path, tmp_storage, monkeypatch):
    monkeypatch.setattr(auth, "DB_FILE", tmp_path / "voxagent.db")
    monkeypatch.setattr(auth, "LEGACY_USERS", tmp_path / "no_users.json")
    monkeypatch.setattr(auth, "LEGACY_TOKENS", tmp_path / "no_tokens.json")
    monkeypatch.setenv("ADMIN_EMAIL", "sai@test.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin-pw-123")
    auth._invalidate_cache()
    return TestClient(server.app)


def admin_headers(client):
    token = client.post("/api/auth/login",
                        json={"email": "sai@test.com", "password": "admin-pw-123"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_dashboard_returns_everything_in_one_call(client):
    res = client.get("/api/dashboard?client_id=demo_clinic", headers=admin_headers(client))
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"stats", "calls", "bookings", "leads", "billing", "phone", "open_questions"}
    assert set(body["stats"]) == {"calls", "minutes", "bookings", "leads", "conversion"}
    assert res.headers.get("ETag")


def test_unchanged_data_answers_304_with_no_body(client):
    headers = admin_headers(client)
    first = client.get("/api/dashboard?client_id=demo_clinic", headers=headers)
    etag = first.headers["ETag"]

    again = client.get("/api/dashboard?client_id=demo_clinic",
                       headers={**headers, "If-None-Match": etag})
    assert again.status_code == 304
    assert not again.content


def test_etag_changes_when_data_changes(client):
    headers = admin_headers(client)
    etag = client.get("/api/dashboard?client_id=demo_clinic", headers=headers).headers["ETag"]

    storage.save_lead("demo_clinic", "Kiran", "9998887776", "braces", "")

    res = client.get("/api/dashboard?client_id=demo_clinic",
                     headers={**headers, "If-None-Match": etag})
    assert res.status_code == 200          # stale ETag must not serve a 304
    assert res.headers["ETag"] != etag
    assert len(res.json()["leads"]) == 1


def test_dashboard_requires_authorisation(client):
    assert client.get("/api/dashboard?client_id=demo_clinic").status_code == 401


def test_dashboard_matches_the_individual_endpoints(client):
    """The fast path must agree with the endpoints it replaced."""
    headers = admin_headers(client)
    combined = client.get("/api/dashboard?client_id=demo_clinic", headers=headers).json()
    assert combined["stats"] == client.get("/api/stats?client_id=demo_clinic",
                                           headers=headers).json()
    assert combined["billing"] == client.get("/api/billing_status?client_id=demo_clinic",
                                             headers=headers).json()
    assert combined["phone"] == client.get("/api/phone_status?client_id=demo_clinic",
                                           headers=headers).json()
    assert combined["calls"] == client.get("/api/calls?client_id=demo_clinic",
                                           headers=headers).json()[:server.DASHBOARD_CALL_LIMIT]


# ---- conversion counts bookings that SUCCEEDED (audit M1, eng review D3/D10) --------

from agent import ReceptionistAgent  # noqa: E402
from conftest import FakeLLM, open_day, open_times  # noqa: E402


def _call_with_tool(name, args, call_id):
    """Log one call in which the agent ran a single tool."""
    agent = ReceptionistAgent("demo_clinic", llm=FakeLLM([]))
    agent.history = [{"role": "user", "text": "hi", "at": agent.now()},
                     agent.tool_call_entry([{"name": name, "args": args}]),
                     agent.run_tool({"name": name, "args": args})]
    storage.log_call_from_agent(agent, "web-test", server.dt.datetime.now(), call_id=call_id)
    return agent.history[-1]["result"]


def test_a_failed_booking_is_not_a_booked_call(client):
    day = open_day()
    ok = _call_with_tool("book_appointment", {
        "customer_name": "Ravi", "phone": "9876543210", "service": "Cleaning",
        "date": day, "time": open_times(date=day)[0]}, "good")
    bad = _call_with_tool("book_appointment", {
        "customer_name": "Asha", "phone": "123", "service": "Cleaning",
        "date": day, "time": open_times(date=day)[1]}, "bad")    # phone too short
    assert ok["status"] == "confirmed" and bad["status"] == "failed"
    body = client.get("/api/dashboard?client_id=demo_clinic", headers=admin_headers(client)).json()
    assert body["stats"]["conversion"] == 50            # used to say 100
    by_id = {c["call_id"]: c["outcome"] for c in body["calls"]}
    assert by_id == {"good": {"booked": True, "lead": False},
                     "bad": {"booked": False, "lead": False}}
    recent = client.get("/api/admin/overview", headers=admin_headers(client)).json()["recent_calls"]
    assert sorted(c["booked"] for c in recent) == [False, True]


def test_a_saved_lead_is_flagged_as_a_lead(client):
    _call_with_tool("save_lead", {"name": "Kiran", "phone": "9998887776",
                                  "interest": "braces"}, "lead")
    [call] = client.get("/api/calls?client_id=demo_clinic", headers=admin_headers(client)).json()
    assert call["outcome"] == {"booked": False, "lead": True}


def test_old_records_without_an_outcome_fall_back_to_the_transcript():
    assert server.record_outcome({"transcript": "  [tool call] book_appointment(...)"}) \
        == {"booked": True, "lead": False}
    assert server.record_outcome({"transcript": "Customer: hi"}) == {"booked": False, "lead": False}
    stored = {"transcript": "book_appointment", "outcome": {"booked": False, "lead": False}}
    assert server.record_outcome(stored)["booked"] is False   # the stored truth wins


def test_shipping_outcomes_never_mutates_the_shared_cache(client):
    _call_with_tool("save_lead", {"name": "Kiran", "phone": "9998887776",
                                  "interest": "braces"}, "lead")
    cached = storage.read_call_logs("demo_clinic")[0]
    cached.pop("outcome")                               # simulate an old record in cache
    client.get("/api/calls?client_id=demo_clinic", headers=admin_headers(client))
    assert "outcome" not in storage.read_call_logs("demo_clinic")[0]
