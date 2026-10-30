"""Credential guessing is slow and codes are long (audit RT-3, 2026-10-21:
1,500 wrong business codes were accepted for checking in 2 seconds)."""

import re
import shutil

import pytest
from fastapi.testclient import TestClient

import ratelimit
import server
import storage
from conftest import DEMO_CODE, SALON_CODE


# ---- the limiter itself --------------------------------------------------------

class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_blocks_after_max_failures_and_recovers_after_the_window():
    clock = Clock()
    lim = ratelimit.FailureLimiter(max_failures=3, window_s=60, clock=clock)
    for _ in range(2):
        lim.fail("1.2.3.4")
    assert lim.retry_after("1.2.3.4") == 0
    lim.fail("1.2.3.4")
    assert 0 < lim.retry_after("1.2.3.4") <= 61
    assert lim.retry_after("5.6.7.8") == 0            # one address doesn't block another
    clock.t += 61
    assert lim.retry_after("1.2.3.4") == 0


def test_memory_stays_bounded():
    lim = ratelimit.FailureLimiter(max_failures=3, window_s=60, max_keys=100)
    for i in range(1000):
        lim.fail(f"10.0.{i // 250}.{i % 250}")
    assert len(lim._fails) == 100


# ---- through the server ----------------------------------------------------------

@pytest.fixture
def client(tmp_storage, monkeypatch):
    import auth
    monkeypatch.setattr(auth, "DB_FILE", tmp_storage / "voxagent.db")
    monkeypatch.setattr(auth, "LEGACY_USERS", tmp_storage / "no_users.json")
    monkeypatch.setattr(auth, "LEGACY_TOKENS", tmp_storage / "no_tokens.json")
    return TestClient(server.app)


def guess(client, code, **headers):
    return client.post("/api/portal/login", json={"access_key": code}, headers=headers).status_code


def test_guessing_business_codes_is_cut_off(client):
    statuses = [guess(client, f"VX-{i:06X}") for i in range(ratelimit.MAX_FAILURES)]
    assert statuses == [401] * ratelimit.MAX_FAILURES
    blocked = client.post("/api/portal/login", json={"access_key": DEMO_CODE})
    assert blocked.status_code == 429                       # even the right code, while blocked
    assert int(blocked.headers["Retry-After"]) > 0 and "Try again" in blocked.json()["detail"]


def test_the_data_api_header_counts_too(client):
    for _ in range(ratelimit.MAX_FAILURES):
        assert client.get("/api/dashboard?client_id=demo_clinic",
                          headers={"X-Client-Key": "VX-WRONG"}).status_code == 401
    assert client.get("/api/dashboard?client_id=demo_clinic",
                      headers={"X-Client-Key": DEMO_CODE}).status_code == 429


def test_guessing_one_business_never_locks_out_another(client):
    """Review P1-2: counting every 401 per address let one attacker lock out
    every owner behind the same address."""
    for _ in range(ratelimit.MAX_FAILURES + 5):
        client.get("/api/dashboard?client_id=demo_clinic", headers={"X-Client-Key": "VX-WRONG"})
    assert client.get("/api/dashboard?client_id=lakshmi_beauty_salon",
                      headers={"X-Client-Key": SALON_CODE}).status_code == 200
    assert guess(client, SALON_CODE) == 200          # code login is its own count too


def test_made_up_business_ids_share_one_count(client):
    for i in range(ratelimit.MAX_FAILURES):
        client.get(f"/api/dashboard?client_id=nobody_{i}", headers={"X-Client-Key": "VX-WRONG"})
    assert client.get("/api/dashboard?client_id=nobody_x",
                      headers={"X-Client-Key": "VX-WRONG"}).status_code == 429


def test_admin_key_guesses_count_once_whatever_the_route(client, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "Correct-Horse-Battery-77")
    for i in range(ratelimit.MAX_FAILURES):
        client.get(f"/api/dashboard?client_id=biz_{i}", headers={"X-Admin-Key": "wrong"})
    assert client.get("/api/admin/overview", headers={"X-Admin-Key": "wrong"}).status_code == 429
    # Blocked on every route, even with the right key, so guessing can't move to another one.
    assert client.get("/api/dashboard?client_id=demo_clinic",
                      headers={"X-Admin-Key": "Correct-Horse-Battery-77"}).status_code == 429


def test_an_expired_sign_in_token_is_not_a_guess(client):
    """A stale browser tab polling with an old token must not lock its owner out."""
    for _ in range(ratelimit.MAX_FAILURES * 2):
        assert client.get("/api/dashboard?client_id=demo_clinic",
                          headers={"Authorization": "Bearer expired-token"}).status_code == 401
    assert client.get("/api/dashboard?client_id=demo_clinic",
                      headers={"X-Client-Key": DEMO_CODE}).status_code == 200


def test_behind_our_proxy_only_the_hop_it_added_is_trusted(client, monkeypatch):
    """Review P1-1: the leftmost X-Forwarded-For entry is whatever the client
    sent. Our proxy appends the address it saw, so read from the right."""
    monkeypatch.setenv("VOXAGENT_TRUST_PROXY", "true")
    for i in range(ratelimit.MAX_FAILURES):
        assert guess(client, "VX-WRONG", **{"X-Forwarded-For": f"1.1.1.{i}, 203.0.113.9"}) == 401
    assert guess(client, DEMO_CODE, **{"X-Forwarded-For": "8.8.8.8, 203.0.113.9"}) == 429
    assert guess(client, DEMO_CODE, **{"X-Forwarded-For": "198.51.100.4"}) == 200   # another visitor
    # Without the setting the header is ignored entirely.
    monkeypatch.delenv("VOXAGENT_TRUST_PROXY")
    for i in range(ratelimit.MAX_FAILURES):
        guess(client, "VX-WRONG", **{"X-Forwarded-For": f"192.0.2.{i}"})
    assert guess(client, DEMO_CODE, **{"X-Forwarded-For": "192.0.2.200"}) == 429


def test_ipv6_addresses_count_per_64_block():
    from starlette.requests import Request

    def req(host):
        return Request({"type": "http", "headers": [], "client": (host, 1234)})
    assert server._client_ip(req("2001:db8:1:2::1")) == server._client_ip(req("2001:db8:1:2:ffff::9"))
    assert server._client_ip(req("2001:db8:1:3::1")) != server._client_ip(req("2001:db8:1:2::1"))
    assert server._client_ip(req("203.0.113.5")) == "203.0.113.5"


def test_website_chat_is_not_counted(client):
    for _ in range(ratelimit.MAX_FAILURES + 2):
        client.post("/api/public/session", json={"key": "wk_nope"})
    assert guess(client, DEMO_CODE) == 200


# ---- codes ----------------------------------------------------------------------

def test_new_codes_are_long_and_unambiguous():
    codes = {storage.new_access_code() for _ in range(200)}
    assert len(codes) == 200
    for c in codes:
        assert re.fullmatch(r"VX-[2-9A-HJKMNP-Z]{4}-[2-9A-HJKMNP-Z]{4}-[2-9A-HJKMNP-Z]{4}", c), c


def test_the_sample_businesses_no_longer_use_short_codes():
    assert storage.short_code_businesses() == []


def test_rotating_a_code_retires_the_old_one(client, tmp_storage, monkeypatch):
    clients = tmp_storage / "clients"
    shutil.copytree(storage.CLIENTS_DIR, clients)
    monkeypatch.setattr(storage, "CLIENTS_DIR", clients)
    storage.clear_caches()
    new = storage.rotate_access_code("demo_clinic")
    assert new != DEMO_CODE
    assert guess(client, DEMO_CODE) == 401
    assert guess(client, new) == 200


def test_creating_a_business_cannot_be_used_to_guess_the_admin_key(client, monkeypatch):
    """Review P2-N1: POST /api/business compared the admin key directly."""
    monkeypatch.setenv("ADMIN_PASSWORD", "Correct-Horse-Battery-77")
    body = {"business_name": "Probe Biz", "services": [{"name": "x", "price": "1"}]}
    codes = [client.post("/api/business", json=body, headers={"X-Admin-Key": f"wrong{i}"}).status_code
             for i in range(ratelimit.MAX_FAILURES + 1)]
    assert codes[:-1] == [401] * ratelimit.MAX_FAILURES and codes[-1] == 429


def test_the_admin_key_is_compared_in_exactly_one_place():
    """Any new route must use server.admin_key_ok, or it skips the throttle."""
    import inspect
    src = inspect.getsource(server)
    assert src.count("admin_password_matches(") == 1
    assert "def admin_key_ok" in src
