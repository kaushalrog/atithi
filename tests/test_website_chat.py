"""Website chat: public, so off by default, capped, and isolated from the
owner's login code and paid endpoints."""

import shutil

import pytest
from fastapi.testclient import TestClient

import server
import storage
from agent import ReceptionistAgent
from conftest import FakeLLM, DEMO_CODE

DEMO_KEY = {"X-Client-Key": DEMO_CODE}


@pytest.fixture
def client(tmp_storage, monkeypatch):
    import auth
    clients = tmp_storage / "clients"
    shutil.copytree(storage.CLIENTS_DIR, clients)
    monkeypatch.setattr(storage, "CLIENTS_DIR", clients)
    monkeypatch.setattr(auth, "DB_FILE", tmp_storage / "voxagent.db")
    monkeypatch.setattr(auth, "LEGACY_USERS", tmp_storage / "no_users.json")
    monkeypatch.setattr(auth, "LEGACY_TOKENS", tmp_storage / "no_tokens.json")
    monkeypatch.setattr(server, "ReceptionistAgent",
                        lambda cid: ReceptionistAgent(cid, llm=FakeLLM([])))
    monkeypatch.setattr(server, "_widget_ips", {})
    monkeypatch.setattr(server, "_widget_turns", {})
    storage.clear_caches()
    return TestClient(server.app)


def enable(client, on=True):
    body = client.get("/api/business/demo_clinic/settings", headers=DEMO_KEY).json()
    body["website_chat"] = on
    return client.put("/api/business/demo_clinic/settings", json=body, headers=DEMO_KEY).json()


def test_off_by_default_and_unknown_keys_get_nothing(client):
    s = client.get("/api/business/demo_clinic/settings", headers=DEMO_KEY).json()
    assert s["website_chat"] is False and s["widget_key"] == ""
    assert client.post("/api/public/session", json={"key": "wk_guess"}).status_code == 404


def test_switching_on_gives_a_public_key_that_is_not_the_login_code(client):
    s = enable(client)
    key = s["widget_key"]
    assert key.startswith("wk_") and key != DEMO_CODE
    assert enable(client)["widget_key"] == key                  # stable across saves
    res = client.post("/api/public/session", json={"key": key})
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"session_id", "business_name", "greeting"}   # nothing private leaks
    assert "AI receptionist" in body["greeting"] and "saved" in body["greeting"]
    reply = client.post("/api/public/chat", json={"session_id": body["session_id"], "message": "hi"})
    assert reply.status_code == 200 and "reply" in reply.json() and "tools" not in reply.json()
    [record] = storage.read_call_logs("demo_clinic")
    assert record["channel"] == "website"
    # Switched off again: the same key stops working.
    enable(client, on=False)
    assert client.post("/api/public/session", json={"key": key}).status_code == 404


def test_website_sessions_cannot_use_paid_or_owner_endpoints(client):
    key = enable(client)["widget_key"]
    sid = client.post("/api/public/session", json={"key": key}).json()["session_id"]
    assert client.post("/api/tts", json={"session_id": sid, "text": "hi"}).status_code == 403
    assert client.post("/api/voice", data={"session_id": sid},
                       files={"audio": ("a.wav", b"RIFF0000", "audio/wav")}).status_code == 403
    owner_sid = client.post("/api/session", json={"client_id": "demo_clinic"}, headers=DEMO_KEY).json()["session_id"]
    assert client.post("/api/public/chat", json={"session_id": owner_sid, "message": "hi"}).status_code == 404


def test_new_chats_are_rate_limited_per_visitor(client, monkeypatch):
    monkeypatch.setattr(server, "WIDGET_NEW_SESSIONS_PER_IP", 3)
    key = enable(client)["widget_key"]
    codes = [client.post("/api/public/session", json={"key": key}).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


def test_the_daily_message_cap_answers_politely_without_the_model(client, monkeypatch):
    monkeypatch.setattr(server, "WIDGET_DAILY_TURNS", 2)
    key = enable(client)["widget_key"]
    sid = client.post("/api/public/session", json={"key": key}).json()["session_id"]
    calls = []
    agent = server.get_session(sid)["agent"]
    real_send = agent.llm.send
    agent.llm.send = lambda *a, **k: calls.append(1) or real_send(*a, **k)
    for _ in range(2):
        assert "busy" not in client.post("/api/public/chat", json={"session_id": sid, "message": "hi"}).json()
    third = client.post("/api/public/chat", json={"session_id": sid, "message": "hi"}).json()
    assert third["busy"] is True and "call us" in third["reply"]
    assert len(calls) == 2


def test_long_messages_and_expired_plans_are_refused(client, monkeypatch):
    key = enable(client)["widget_key"]
    sid = client.post("/api/public/session", json={"key": key}).json()["session_id"]
    assert client.post("/api/public/chat", json={"session_id": sid, "message": "x" * 501}).status_code == 422
    monkeypatch.setattr(server.billing, "client_active", lambda cid: False)
    assert client.post("/api/public/session", json={"key": key}).status_code == 404


def test_the_widget_files_are_served(client):
    js = client.get("/widget.js")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"] and "data-atithi" in js.text
    page = client.get("/chat?k=wk_x")
    assert page.status_code == 200 and "/api/public/session" in page.text
    assert "innerHTML = r.reply" not in page.text                 # replies are text, never HTML
