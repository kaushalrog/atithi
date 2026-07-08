"""Access control: business codes lock each owner to their own data;
the admin password opens everything."""

import pytest
from fastapi.testclient import TestClient

import server


@pytest.fixture
def client(tmp_storage, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-pw")
    return TestClient(server.app)


DEMO_KEY = "VX-84KQ2N"  # demo_clinic's code from its YAML


def test_no_key_is_rejected(client):
    assert client.get("/api/stats?client_id=demo_clinic").status_code == 401


def test_wrong_business_code_is_rejected(client):
    res = client.get("/api/stats?client_id=demo_clinic",
                     headers={"X-Client-Key": "VX-7TPX3R"})  # the salon's code
    assert res.status_code == 401


def test_own_business_code_works(client):
    res = client.get("/api/stats?client_id=demo_clinic",
                     headers={"X-Client-Key": DEMO_KEY})
    assert res.status_code == 200
    assert set(res.json()) >= {"calls", "bookings", "leads"}


def test_admin_password_opens_any_business(client):
    for cid in ("demo_clinic", "lakshmi_beauty_salon"):
        res = client.get(f"/api/bookings?client_id={cid}",
                         headers={"X-Admin-Key": "test-admin-pw"})
        assert res.status_code == 200


def test_portal_login_maps_code_to_business(client):
    res = client.post("/api/portal/login", json={"access_key": DEMO_KEY})
    assert res.status_code == 200
    assert res.json()["client_id"] == "demo_clinic"
    assert client.post("/api/portal/login", json={"access_key": "VX-NOPE99"}).status_code == 401
    assert client.post("/api/portal/login", json={"access_key": ""}).status_code == 401


def test_client_list_and_creation_are_admin_only(client):
    assert client.get("/api/clients").status_code in (401, 503)
    assert client.post("/api/business", json={
        "business_name": "X", "services": [{"name": "s", "price": "1"}],
    }).status_code in (401, 503)
