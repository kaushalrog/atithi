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
    assert set(body) == {"stats", "calls", "bookings", "leads", "billing", "phone"}
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
