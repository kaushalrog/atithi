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


# ---- exposure fixes (Phase 0.5 hardening) ------------------------------------------

import auth  # noqa: E402
from agent import ReceptionistAgent  # noqa: E402
from conftest import FakeLLM  # noqa: E402


@pytest.fixture
def session(client, monkeypatch):
    """A live test-call session whose agent answers from a script (no API key)."""
    monkeypatch.setattr(server, "ReceptionistAgent",
                        lambda cid: ReceptionistAgent(cid, llm=FakeLLM([])))
    res = client.post("/api/session", json={"client_id": "demo_clinic"},
                      headers={"X-Client-Key": DEMO_KEY})
    assert res.status_code == 200
    return res.json()["session_id"]


def test_tts_requires_a_live_session_and_bounds_text(client, session, monkeypatch):
    """Audit M4 (R5): /api/tts was an open, unlimited TTS proxy."""
    monkeypatch.setattr(server.tts, "synthesize_bytes", lambda text: b"ID3fake")
    assert client.post("/api/tts", json={"text": "hi"}).status_code == 422
    assert client.post("/api/tts", json={"session_id": "nope", "text": "hi"}).status_code == 404
    too_long = {"session_id": session, "text": "x" * 1001}
    assert client.post("/api/tts", json=too_long).status_code == 422
    ok = client.post("/api/tts", json={"session_id": session, "text": "x" * 1000})
    assert ok.status_code == 200 and ok.content == b"ID3fake"


def test_chat_message_size_is_bounded(client, session):
    """Audit M5 (R7): a 2 MB message was accepted and re-sent every turn."""
    assert client.post("/api/chat", json={"session_id": session,
                                          "message": "x" * 2001}).status_code == 422
    assert client.post("/api/chat", json={"session_id": session,
                                          "message": "x" * 2000}).status_code == 200


def test_voice_upload_size_is_bounded(client, session, monkeypatch):
    heard = []
    monkeypatch.setattr(FakeLLM, "transcribe", lambda self, data, mime_type: heard.append(data) or "",
                        raising=False)
    big = b"\0" * (server.MAX_VOICE_BYTES + 1)
    res = client.post("/api/voice", data={"session_id": session},
                      files={"audio": ("a.wav", big, "audio/wav")})
    assert res.status_code == 413 and heard == []      # never sent to the model
    res = client.post("/api/voice", data={"session_id": session},
                      files={"audio": ("a.wav", b"\0" * 100, "audio/wav")})
    assert res.status_code == 200 and len(heard) == 1


@pytest.mark.parametrize("password,works", [
    ("choose_a_strong_password", False),   # the .env.example placeholder (R6b)
    ("short-pw-11", False),                # 11 characters
    ("long-enough1", True),                # 12 characters
])
def test_admin_password_policy(client, monkeypatch, password, works):
    monkeypatch.setenv("ADMIN_PASSWORD", password)
    res = client.get("/api/admin/overview", headers={"X-Admin-Key": password})
    assert res.status_code == (200 if works else 503)
    # The admin key must not open business data either while it is unusable.
    res = client.get("/api/bookings?client_id=demo_clinic", headers={"X-Admin-Key": password})
    assert res.status_code == (200 if works else 401)


def test_admin_login_endpoint_never_crashes(client):
    """Audit L1 (R6a): this endpoint returned 500 for every input."""
    assert client.post("/api/admin/login", json={"password": "test-admin-pw"}).status_code == 200
    assert client.post("/api/admin/login", json={"password": "wrong"}).status_code == 401


def test_admin_role_is_disabled_while_the_password_is_weak(client, tmp_path, monkeypatch):
    """An admin account seeded before the policy existed must stop working too."""
    monkeypatch.setattr(auth, "DB_FILE", tmp_path / "voxagent.db")
    monkeypatch.setattr(auth, "LEGACY_USERS", tmp_path / "none.json")
    monkeypatch.setattr(auth, "LEGACY_TOKENS", tmp_path / "none2.json")
    monkeypatch.setenv("ADMIN_EMAIL", "sai@test.com")
    auth._invalidate_cache()
    token = client.post("/api/auth/login", json={"email": "sai@test.com",
                                                 "password": "test-admin-pw"}).json()["token"]
    bearer = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/admin/overview", headers=bearer).status_code == 200
    monkeypatch.setenv("ADMIN_PASSWORD", "choose_a_strong_password")
    assert client.get("/api/admin/overview", headers=bearer).status_code == 503
    assert client.get("/api/bookings?client_id=demo_clinic", headers=bearer).status_code == 401


def test_placeholder_admin_email_is_never_seeded(client, tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "DB_FILE", tmp_path / "voxagent.db")
    monkeypatch.setattr(auth, "LEGACY_USERS", tmp_path / "none.json")
    monkeypatch.setattr(auth, "LEGACY_TOKENS", tmp_path / "none2.json")
    monkeypatch.setenv("ADMIN_EMAIL", "you@example.com")
    auth._invalidate_cache()
    res = client.post("/api/auth/login", json={"email": "you@example.com",
                                               "password": "test-admin-pw"})
    assert res.status_code == 401
