"""Accounts & billing: signup/login, owner isolation, trials, activation."""

import datetime as dt

import pytest
import yaml
from fastapi.testclient import TestClient

import auth
import billing
import server
import storage


@pytest.fixture
def client(tmp_path, tmp_storage, monkeypatch):
    monkeypatch.setattr(auth, "DB_FILE", tmp_path / "voxagent.db")
    monkeypatch.setattr(auth, "LEGACY_USERS", tmp_path / "no_users.json")
    monkeypatch.setattr(auth, "LEGACY_TOKENS", tmp_path / "no_tokens.json")
    monkeypatch.setenv("ADMIN_EMAIL", "sai@test.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin-pw-123")
    monkeypatch.delenv("SMTP_HOST", raising=False)  # no email in tests
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
    assert not billing.client_active(client_id)
    assert client.post("/api/session", json={"client_id": client_id},
                       headers=bearer(token)).status_code == 402

    # the owner claims they've paid -> the admin sees it and activates
    res = client.post("/api/billing/renew", json={"client_id": client_id},
                      headers=bearer(token))
    assert res.status_code == 200 and res.json()["renewal_requested"]

    admin = client.post("/api/auth/login",
                        json={"email": "sai@test.com", "password": "admin-pw-123"}).json()
    overview = client.get("/api/admin/overview", headers=bearer(admin["token"])).json()
    row = next(c for c in overview["clients"] if c["client_id"] == client_id)
    assert row["renewal_requested"]

    res = client.post("/api/admin/activate", json={"client_id": client_id, "months": 1},
                      headers=bearer(admin["token"]))
    assert res.status_code == 200
    assert billing.client_active(client_id)
    assert res.json()["paid_until"] >= (dt.date.today() + dt.timedelta(days=29)).isoformat()
    # activation clears the claim
    assert billing.status(client_id)["renewal_requested"] is None


def test_forgot_password_flow(client):
    client.post("/api/auth/signup", json={"email": "o5@x.com", "password": "oldpass1"})
    # identical response for unknown emails (no account probing)
    unknown = client.post("/api/auth/forgot", json={"email": "ghost@x.com"})
    known = client.post("/api/auth/forgot", json={"email": "o5@x.com"})
    assert unknown.status_code == known.status_code == 200
    assert unknown.json()["message"] == known.json()["message"]

    # the admin can see the pending code and pass it to the owner
    admin = client.post("/api/auth/login",
                        json={"email": "sai@test.com", "password": "admin-pw-123"}).json()
    resets = client.get("/api/admin/overview",
                        headers=bearer(admin["token"])).json()["password_resets"]
    code = next(r["code"] for r in resets if r["email"] == "o5@x.com")

    # wrong code rejected; right code sets the new password and logs in
    assert client.post("/api/auth/reset", json={
        "email": "o5@x.com", "code": "RS-WRONG1", "new_password": "newpass1",
    }).status_code == 401
    res = client.post("/api/auth/reset", json={
        "email": "o5@x.com", "code": code, "new_password": "newpass1",
    })
    assert res.status_code == 200 and res.json()["token"]
    # a used code can't be replayed
    assert client.post("/api/auth/reset", json={
        "email": "o5@x.com", "code": code, "new_password": "again123",
    }).status_code == 401
    # old password dead, new one works
    assert client.post("/api/auth/login",
                       json={"email": "o5@x.com", "password": "oldpass1"}).status_code == 401
    assert client.post("/api/auth/login",
                       json={"email": "o5@x.com", "password": "newpass1"}).status_code == 200


def test_owner_cannot_use_admin_endpoints(client):
    token = client.post("/api/auth/signup",
                        json={"email": "o4@x.com", "password": "secret1"}).json()["token"]
    assert client.get("/api/clients", headers=bearer(token)).status_code == 401
    assert client.post("/api/admin/activate", json={"client_id": "x"},
                       headers=bearer(token)).status_code == 401
