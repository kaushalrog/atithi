"""Access control: business codes lock each owner to their own data;
the admin password opens everything."""

import pytest
from fastapi.testclient import TestClient

import server


@pytest.fixture
def client(tmp_storage, monkeypatch):
    import auth
    # Accounts DB in the temp folder too: the admin console reads it, and an
    # earlier version of this fixture created a real voxagent.db in the repo.
    monkeypatch.setattr(auth, "DB_FILE", tmp_storage / "voxagent.db")
    monkeypatch.setattr(auth, "LEGACY_USERS", tmp_storage / "no_users.json")
    monkeypatch.setattr(auth, "LEGACY_TOKENS", tmp_storage / "no_tokens.json")
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


# ---- review fixes: auth + behaviour (approved D2 #5-#7, D3 #9, #10, #12) -------------

def test_non_ascii_or_numeric_credentials_are_rejected_not_crashed(client, monkeypatch):
    """#5: hmac.compare_digest raises on non-ASCII str (and str-vs-int); that
    surfaced as HTTP 500 at three credential checks (QA probe 003/004)."""
    c = TestClient(server.app, raise_server_exceptions=False)
    assert c.get("/api/stats?client_id=demo_clinic",
                 headers={"X-Client-Key": b"VX-\xe9"}).status_code == 401
    assert c.post("/api/portal/login", json={"access_key": "VX-é"}).status_code == 401
    monkeypatch.setattr(server, "client_access_key", lambda cid: 482913)  # YAML int
    assert c.get("/api/stats?client_id=demo_clinic",
                 headers={"X-Client-Key": "482913"}).status_code == 200


def login_admin(client, email):
    return client.post("/api/auth/login", json={"email": email,
                                               "password": "test-admin-pw"}).json()["token"]


def test_admin_role_only_counts_for_the_current_admin_email(client, monkeypatch):
    """#6: an admin account seeded under an old ADMIN_EMAIL kept admin rights."""
    monkeypatch.setenv("ADMIN_EMAIL", "old@test.com")
    auth._invalidate_cache()
    old_token = login_admin(client, "old@test.com")
    monkeypatch.setenv("ADMIN_EMAIL", "new@test.com")
    auth._invalidate_cache()
    bearer = {"Authorization": f"Bearer {old_token}"}
    assert client.get("/api/admin/overview", headers=bearer).status_code == 401
    new_token = login_admin(client, "new@test.com")
    assert client.get("/api/admin/overview",
                      headers={"Authorization": f"Bearer {new_token}"}).status_code == 200


def test_admin_503_does_not_explain_the_misconfiguration(client, monkeypatch, capsys):
    """#7: anonymous callers must not learn why admin is off; the log says it."""
    monkeypatch.setenv("ADMIN_PASSWORD", "choose_a_strong_password")
    res = client.get("/api/admin/overview")
    assert res.status_code == 503
    assert "placeholder" not in res.text and "characters" not in res.text
    assert "placeholder" in capsys.readouterr().out


def test_admin_console_reports_live_calls_switch(client, monkeypatch):
    """#9: keys present but ENABLE_LIVE_CALLS off must not read as 'connected'."""
    for k, v in {"TWILIO_ACCOUNT_SID": "AC1", "TWILIO_AUTH_TOKEN": "t",
                 "PUBLIC_BASE_URL": "https://x.test"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("ENABLE_LIVE_CALLS", raising=False)
    data = client.get("/api/admin/overview", headers={"X-Admin-Key": "test-admin-pw"}).json()
    assert data["twilio_configured"] is False and data["status"]["twilio"] is False
    assert data["status"]["live_calls"] is False
    assert data["status"]["twilio_keys"] is True          # keys present: "off by design"
    assert data["status"]["bookings_paused"] is None
    assert data["status"]["sheets"] is False               # no SHEET_ID / credentials
    monkeypatch.setenv("ENABLE_LIVE_CALLS", "true")
    data = client.get("/api/admin/overview", headers={"X-Admin-Key": "test-admin-pw"}).json()
    assert data["twilio_configured"] is True


def test_voice_transcript_is_capped_like_typed_chat(client, session, monkeypatch):
    """#10: speech-to-text output bypassed the 2000-char chat limit."""
    monkeypatch.setattr(FakeLLM, "transcribe",
                        lambda self, data, mime_type: "word " * 1000, raising=False)
    res = client.post("/api/voice", data={"session_id": session},
                      files={"audio": ("a.wav", b"\0" * 100, "audio/wav")})
    assert res.status_code == 200
    assert len(res.json()["heard"]) <= server.MAX_CHAT_CHARS
    agent = server.sessions[session]["agent"]
    assert all(len(m["text"]) <= server.MAX_CHAT_CHARS
               for m in agent.history if m["role"] == "user")


def test_oversized_request_bodies_are_refused_before_parsing(client, session, monkeypatch):
    """#12: the 5 MB voice check ran only after the whole upload was spooled."""
    parsed = []
    monkeypatch.setattr(FakeLLM, "transcribe",
                        lambda self, data, mime_type: parsed.append(1) or "", raising=False)
    big = b"\0" * (server.MAX_BODY_BYTES + 1)
    res = client.post("/api/voice", data={"session_id": session},
                      files={"audio": ("a.wav", big, "audio/wav")})
    assert res.status_code == 413 and parsed == []
    res = client.post("/api/chat", content=b"{" + b" " * server.MAX_BODY_BYTES + b"}",
                      headers={"Content-Type": "application/json"})
    assert res.status_code == 413


# ---- review cycle 2 (approved D6 #1, #2) ------------------------------------------------

def test_admin_email_cannot_be_claimed_by_signup(client, monkeypatch):
    """#1: anyone could sign up as ADMIN_EMAIL before the owner's first login."""
    monkeypatch.setenv("ADMIN_EMAIL", "sai@test.com")
    res = client.post("/api/auth/signup", json={"email": "SAI@test.com", "password": "attacker1"})
    assert res.status_code in (403, 409) and "token" not in res.text


def test_admin_seeding_revokes_tokens_of_a_preclaimed_account(client, monkeypatch):
    """#1: an account that already held ADMIN_EMAIL (signed up before this fix)
    keeps no session once it is promoted; and seeding happens at startup."""
    monkeypatch.setenv("ADMIN_EMAIL", "")                 # signup open for this setup step
    attacker = client.post("/api/auth/signup", json={"email": "sai@test.com",
                                                      "password": "attacker1"}).json()["token"]
    monkeypatch.setenv("ADMIN_EMAIL", "sai@test.com")
    auth._invalidate_cache()
    bearer = {"Authorization": f"Bearer {attacker}"}
    with TestClient(server.app) as started:               # runs the startup hook (seeds admin)
        assert started.get("/api/admin/overview", headers=bearer).status_code == 401
    # The real owner logs in (seeding again) — the pre-claimed session must stay dead.
    assert client.post("/api/auth/login", json={"email": "sai@test.com",
                                                "password": "test-admin-pw"}).status_code == 200
    assert client.get("/api/admin/overview", headers=bearer).status_code == 401
    assert client.post("/api/auth/login", json={"email": "sai@test.com",
                                                "password": "attacker1"}).status_code == 401


def test_body_without_content_length_is_refused(client):
    """#2: a chunked upload (no Content-Length) bypassed the 6 MB check."""
    def chunks():
        yield b'{"session_id": "x", '
        yield b'"message": "hi"}'
    res = client.post("/api/chat", content=chunks(), headers={"Content-Type": "application/json"})
    assert res.status_code == 411


def test_a_failed_model_call_records_the_customer_turn_once(client, session):
    """Review I5: agent.chat records the customer's message before calling the
    model, and the degraded fallback recorded it again, so every outage
    showed the customer saying everything twice (and the trace got a turn
    with no timestamp)."""
    agent = server.get_session(session)["agent"]

    class Down:
        def send(self, messages, tools=None):
            raise ConnectionError("model unreachable")
    agent.llm = Down()
    res = client.post("/api/chat", json={"session_id": session, "message": "hello?"})
    assert res.status_code == 200 and res.json()["degraded"] is True
    users = [m for m in agent.history if m["role"] == "user"]
    assert [m["text"] for m in users] == ["hello?"]
    assert all(m.get("at") for m in agent.history)


# ---- bounded sessions (perf audit F7, F8; eng review D7) ------------------------------

import threading  # noqa: E402
import time  # noqa: E402


class SlowLLM:
    """Answers after `delay` seconds, so two requests can overlap."""

    def __init__(self, delay):
        self.delay, self.calls = delay, 0

    def send(self, messages, tools=None):
        self.calls += 1
        time.sleep(self.delay)
        return {"text": "Here you go.", "tool_calls": []}


def test_a_second_message_while_answering_gets_409_and_history_stays_whole(client, session):
    """Two tabs (or a double-click) used to run two turns at once and
    interleave them in one history (bench: 18 of 20 runs broken)."""
    agent = server.get_session(session)["agent"]
    agent.llm = SlowLLM(0.2)
    codes, barrier = [], threading.Barrier(2)

    def send():
        barrier.wait()
        codes.append(client.post("/api/chat", json={"session_id": session,
                                                    "message": "slots?"}).status_code)
    threads = [threading.Thread(target=send) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(codes) == [200, 409]
    assert [m["role"] for m in agent.history] == ["user", "assistant"]
    # ...and the session works normally afterwards.
    assert client.post("/api/chat", json={"session_id": session,
                                          "message": "thanks"}).status_code == 200


def test_the_409_names_the_problem_for_the_portal(client, session):
    s = server.get_session(session)
    s["lock"].acquire()
    try:
        res = client.post("/api/chat", json={"session_id": session, "message": "hi"})
    finally:
        s["lock"].release()
    assert res.status_code == 409 and "Still answering" in res.json()["detail"]


def test_a_session_ends_politely_at_the_turn_cap(client, session, monkeypatch):
    monkeypatch.setattr(server, "MAX_TURNS_PER_SESSION", 3)
    agent = server.get_session(session)["agent"]
    agent.llm = SlowLLM(0)
    for _ in range(3):
        assert client.post("/api/chat", json={"session_id": session,
                                              "message": "hi"}).json().get("ended") is None
    res = client.post("/api/chat", json={"session_id": session, "message": "one more"}).json()
    assert res["reply"] == server.CLOSING_LINE and res["ended"] is True
    assert agent.llm.calls == 3                       # no model call past the cap
    assert sum(m["role"] == "user" for m in agent.history) == 3


def test_sessions_are_capped_per_business_and_in_total(client, session, monkeypatch):
    monkeypatch.setattr(server, "MAX_SESSIONS_PER_BUSINESS", 2)
    new = lambda cid, key: client.post("/api/session", json={"client_id": cid},
                                       headers={"X-Client-Key": key}).status_code
    assert new("demo_clinic", DEMO_KEY) == 200        # the fixture's + this one = 2
    assert new("demo_clinic", DEMO_KEY) == 429
    assert new("lakshmi_beauty_salon", "VX-7TPX3R") == 200   # other businesses unaffected
    monkeypatch.setattr(server, "MAX_SESSIONS", 3)
    assert new("lakshmi_beauty_salon", "VX-7TPX3R") == 429


def test_idle_sessions_are_purged_on_any_request(client, session):
    server.get_session(session)["last_activity"] -= server.SESSION_IDLE_LIMIT * 2
    res = client.post("/api/chat", json={"session_id": session, "message": "hi"})
    assert res.status_code == 404 and session not in server.sessions


def test_a_session_mid_turn_is_never_purged(client, session):
    s = server.get_session(session)
    s["last_activity"] -= server.SESSION_IDLE_LIMIT * 2
    s["lock"].acquire()                               # a very slow model answer in progress
    try:
        server.purge_idle_sessions()
        assert session in server.sessions
    finally:
        s["lock"].release()
