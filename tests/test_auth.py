"""Accounts & billing: signup/login, owner isolation, trials, activation."""

import datetime as dt

import pytest
import yaml
from fastapi.testclient import TestClient

import auth
import server
import storage


@pytest.fixture
def client(tmp_path, tmp_storage, monkeypatch):
    monkeypatch.setattr(auth, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(auth, "TOKENS_FILE", tmp_path / "tokens.json")
    monkeypatch.setenv("ADMIN_EMAIL", "sai@test.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin-pw-123")
    # Isolate business YAMLs created during tests
    (tmp_path / "clients").mkdir()
    monkeypatch.setattr(server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(storage, "CLIENTS_DIR", tmp_path / "clients")
    return TestClient(server.app)


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


BIZ = {"business_name": "Test Salon", "services": [{"name": "Cut", "price": "₹100"}]}


def test_signup_login_and_wrong_password(client):
    res = client.post("/api/auth/signup", json={"email": "owner@x.com", "password": "secret1"})
    assert res.status_code == 200
    body = res.json()
    assert body["role"] == "owner" and body["client_id"] is None and body["token"]

    assert client.post("/api/auth/signup",
                       json={"email": "owner@x.com", "password": "other66"}).status_code == 409
    assert client.post("/api/auth/signup",
                       json={"email": "new@x.com", "password": "tiny"}).status_code == 422
    assert client.post("/api/auth/login",
                       json={"email": "owner@x.com", "password": "WRONG"}).status_code == 401
    assert client.post("/api/auth/login",
                       json={"email": "owner@x.com", "password": "secret1"}).status_code == 200


def test_admin_account_is_seeded_from_env(client):
    res = client.post("/api/auth/login", json={"email": "sai@test.com", "password": "admin-pw-123"})
    assert res.status_code == 200 and res.json()["role"] == "admin"
    token = res.json()["token"]
    assert client.get("/api/clients", headers=bearer(token)).status_code == 200


def test_owner_onboards_once_and_is_locked_to_own_business(client):
    token = client.post("/api/auth/signup",
                        json={"email": "o2@x.com", "password": "secret1"}).json()["token"]
    # can't read anything before onboarding
    assert client.get("/api/stats?client_id=test_salon", headers=bearer(token)).status_code == 401
    # anonymous creation is rejected
    assert client.post("/api/business", json=BIZ).status_code == 401

    res = client.post("/api/business", json=BIZ, headers=bearer(token))
    assert res.status_code == 200
    client_id = res.json()["client_id"]
    # account is now linked...
    relog = client.post("/api/auth/login", json={"email": "o2@x.com", "password": "secret1"}).json()
    assert relog["client_id"] == client_id and relog["business_name"] == "Test Salon"
    # ...own data opens, a second business does not
    assert client.get(f"/api/stats?client_id={client_id}", headers=bearer(token)).status_code == 200
    assert client.post("/api/business", json=BIZ, headers=bearer(token)).status_code == 403
    # and someone else's data stays closed
    assert client.get("/api/stats?client_id=other_biz", headers=bearer(token)).status_code == 401


def test_new_business_gets_trial_and_admin_can_activate(client, tmp_path):
    token = client.post("/api/auth/signup",
                        json={"email": "o3@x.com", "password": "secret1"}).json()["token"]
    client_id = client.post("/api/business", json=BIZ, headers=bearer(token)).json()["client_id"]

    status = client.get(f"/api/billing_status?client_id={client_id}", headers=bearer(token)).json()
    assert status["plan"] == "trial" and status["active"] and 0 <= status["days_left"] <= 7

    # simulate the trial ending yesterday
    path = tmp_path / "clients" / f"{client_id}.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg["billing"]["paid_until"] = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    assert not storage.client_active(client_id)
    assert client.post("/api/session", json={"client_id": client_id},
                       headers=bearer(token)).status_code == 402

    # the owner pays -> admin activates one month
    admin = client.post("/api/auth/login",
                        json={"email": "sai@test.com", "password": "admin-pw-123"}).json()
    res = client.post("/api/admin/activate", json={"client_id": client_id, "months": 1},
                      headers=bearer(admin["token"]))
    assert res.status_code == 200
    assert storage.client_active(client_id)
    assert res.json()["paid_until"] >= (dt.date.today() + dt.timedelta(days=29)).isoformat()


def test_owner_cannot_use_admin_endpoints(client):
    token = client.post("/api/auth/signup",
                        json={"email": "o4@x.com", "password": "secret1"}).json()["token"]
    assert client.get("/api/clients", headers=bearer(token)).status_code == 401
    assert client.post("/api/admin/activate", json={"client_id": "x"},
                       headers=bearer(token)).status_code == 401
