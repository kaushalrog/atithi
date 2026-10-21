"""Live handoff and missed-call callbacks: off unless switched on, never a
nuisance (opening hours, one per number, daily cap), never a caller left
without a callback they were promised."""

import asyncio
import datetime as dt

import pytest
import yaml

import callbacks
import scheduling
import storage
import telephony
from agent import ReceptionistAgent
from conftest import FakeLLM, DEMO_CODE, SALON_CODE
from test_telephony import FakeLive, SpyLive, phone, post_voice, stream, ticket_from_twiml  # noqa: F401

PHONE = "+919876543210"


def tool(agent, tool_name, **args):
    return agent.run_tool({"name": tool_name, "args": args})["result"]


def set_config(client_id, **changes):
    path = storage.CLIENTS_DIR / f"{client_id}.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg.update(changes)
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    storage.clear_caches()


# ---- transfer_to_owner ----------------------------------------------------------

def test_without_a_live_line_a_transfer_becomes_an_urgent_callback(tmp_storage):
    agent = ReceptionistAgent("demo_clinic", llm=FakeLLM([]))
    res = tool(agent, "transfer_to_owner", reason="tooth pain, wants the doctor")
    assert res["status"] == "failed" and "10-digit" in res["error"]
    res = tool(agent, "transfer_to_owner", reason="tooth pain", name="Ravi", phone="9876543210")
    assert res["status"] == "callback_saved" and agent.handoff is None
    [lead] = storage.read_leads("demo_clinic")
    assert lead["note"].startswith("URGENT callback") and lead["phone"] == "9876543210"
    assert storage.call_outcome(agent.history + [{"role": "tool", "name": "transfer_to_owner",
                                                  "result": res}])["lead"] is True


def test_on_a_live_line_the_agent_asks_the_channel_to_transfer(tmp_storage, monkeypatch):
    real = storage.read_client_config
    monkeypatch.setattr(storage, "read_client_config",
                        lambda cid: {**(real(cid) or {}), "handoff_phone": "+919999900000"})
    agent = ReceptionistAgent("demo_clinic", llm=FakeLLM([]))
    agent.can_transfer = True
    res = tool(agent, "transfer_to_owner", reason="complaint")
    assert res["status"] == "transferring" and agent.handoff["reason"] == "complaint"
    assert storage.read_leads("demo_clinic") == []        # the channel saves it when it transfers


def test_the_bridge_transfers_after_the_agent_speaks(tmp_storage, monkeypatch):
    real = storage.read_client_config
    monkeypatch.setattr(storage, "read_client_config",
                        lambda cid: {**(real(cid) or {}), "handoff_phone": "+919999900000"})
    monkeypatch.setattr(telephony, "HANDOFF_SPEAK_S", 0)
    moved = []
    monkeypatch.setattr(telephony, "transfer_call", lambda sid, to: moved.append((sid, to)))
    agent = ReceptionistAgent("demo_clinic", llm=FakeLLM([]))
    agent.can_transfer = True
    live = FakeLive([{"type": "tool_calls", "calls": [
        {"id": "1", "name": "transfer_to_owner", "args": {"reason": "wants the owner"}}]}])

    async def send(msg):
        pass

    bridge = telephony.TwilioBridge(agent, live, send, caller=PHONE, call_sid="CA42")

    async def run():
        await bridge.pump_gemini()
        await bridge._handoff_task

    asyncio.run(run())
    assert moved == [("CA42", "+919999900000")]
    [lead] = storage.read_leads("demo_clinic")
    assert lead["phone"] == PHONE and "Call transferred" in lead["note"]


def test_a_failed_transfer_tells_the_agent_to_offer_a_callback(tmp_storage, monkeypatch):
    real = storage.read_client_config
    monkeypatch.setattr(storage, "read_client_config",
                        lambda cid: {**(real(cid) or {}), "handoff_phone": "+919999900000"})
    monkeypatch.setattr(telephony, "HANDOFF_SPEAK_S", 0)

    def down(sid, to):
        raise ConnectionError("twilio down")
    monkeypatch.setattr(telephony, "transfer_call", down)
    agent = ReceptionistAgent("demo_clinic", llm=FakeLLM([]))
    agent.can_transfer = True
    agent.handoff = {"reason": "x"}
    live = FakeLive()

    async def send(msg):
        pass
    bridge = telephony.TwilioBridge(agent, live, send, caller=PHONE, call_sid="CA1")
    asyncio.run(bridge._transfer())
    assert "transfer did not go through" in live.sent_texts[-1]


def test_transfers_are_off_unless_switched_on(monkeypatch):
    monkeypatch.setenv("ENABLE_LIVE_CALLS", "true")
    assert telephony.handoff_enabled() is False
    with pytest.raises(RuntimeError, match="ENABLE_HANDOFF"):
        telephony.transfer_call("CA1", "+919999900000")
    monkeypatch.setenv("ENABLE_HANDOFF", "true")
    assert telephony.handoff_enabled() is True
    monkeypatch.setenv("ENABLE_LIVE_CALLS", "false")
    assert telephony.handoff_enabled() is False


# ---- the callback queue -------------------------------------------------------------

def test_one_callback_per_number_and_a_daily_cap(tmp_storage, monkeypatch):
    now = dt.datetime(2026, 10, 20, 11, 0)
    assert storage.queue_callback("demo_clinic", PHONE, "missed call", now) == "queued"
    assert storage.queue_callback("demo_clinic", "09876543210", "missed call", now) == "pending"
    [cb] = storage.pending_callbacks()
    assert storage.claim_callback(cb["id"]) and not storage.claim_callback(cb["id"])  # once only
    storage.mark_callback(cb["id"], "done", "called")
    later = now + dt.timedelta(hours=2)
    assert storage.queue_callback("demo_clinic", PHONE, "missed call", later) == "recent"
    assert storage.queue_callback("demo_clinic", PHONE, "missed call",
                                  now + dt.timedelta(hours=7)) == "queued"
    assert storage.queue_callback("demo_clinic", "123", "x", now) == "invalid"
    monkeypatch.setattr(storage, "CALLBACKS_PER_DAY", 2)
    assert storage.queue_callback("demo_clinic", "+919000000001", "x",
                                  now + dt.timedelta(hours=8)) == "capped"


def test_is_open_follows_days_hours_and_closures():
    cfg = {"schedule": {"days": ["Mon", "Tue"], "ranges": [["10:00", "13:00"], ["16:00", "20:00"]],
                        "closed": [{"date": "2026-10-20", "from": "16:00", "to": "18:00"}]}}
    tue = dt.date(2026, 10, 20)
    at = lambda h, m=0, d=tue: dt.datetime.combine(d, dt.time(h, m))  # noqa: E731
    assert scheduling.is_open(cfg, at(10, 30)) and scheduling.is_open(cfg, at(19))
    assert not scheduling.is_open(cfg, at(9, 59)) and not scheduling.is_open(cfg, at(13))
    assert not scheduling.is_open(cfg, at(17))                       # closed hours
    assert not scheduling.is_open(cfg, at(11, d=dt.date(2026, 10, 22)))  # Thursday


@pytest.fixture
def dialer(tmp_storage, monkeypatch):
    monkeypatch.setattr(telephony, "callbacks_enabled", lambda: True)
    monkeypatch.setattr(telephony, "_calls_in_flight", lambda: 0)
    rang = []
    monkeypatch.setattr(telephony, "start_outbound_call",
                        lambda cid, to, purpose="": rang.append((cid, to, purpose)) or "CAOUT")
    return rang


def _utc(local_naive, cfg_client="demo_clinic"):
    tz, _ = callbacks._business_timezone(storage.read_client_config(cfg_client))
    return local_naive.replace(tzinfo=tz).astimezone(dt.timezone.utc)


def _open_and_closed_times():
    cfg = storage.read_client_config("demo_clinic")
    day = dt.date.today() + dt.timedelta(days=1)
    while not scheduling.day_times(cfg["schedule"], day):
        day += dt.timedelta(days=1)
    first = scheduling.parse_time(cfg["schedule"]["ranges"][0][0])
    opened = dt.datetime.combine(day, first) + dt.timedelta(minutes=5)
    closed = dt.datetime.combine(day, dt.time(2, 0))
    return opened, closed


def test_callbacks_ring_only_while_open_and_only_once(dialer):
    opened, closed = _open_and_closed_times()
    storage.queue_callback("demo_clinic", PHONE, "missed call", closed - dt.timedelta(hours=1))
    assert callbacks.run_due(_utc(closed))["waiting"] == 1 and dialer == []   # 2 AM: wait
    assert callbacks.run_due(_utc(opened))["called"] == 1
    assert dialer == [("demo_clinic", PHONE, "callback")]
    assert callbacks.run_due(_utc(opened))["called"] == 0                    # never twice
    [row] = storage.read_callbacks("demo_clinic")
    assert row["status"] == "done" and "CAOUT" in row["note"]


def test_stale_callbacks_are_dropped_not_made_a_day_late(dialer):
    opened, _ = _open_and_closed_times()
    storage.queue_callback("demo_clinic", PHONE, "missed call", opened - dt.timedelta(hours=30))
    assert callbacks.run_due(_utc(opened))["dropped"] == 1 and dialer == []


def test_a_failed_dial_is_recorded_and_not_retried(dialer, monkeypatch):
    def down(cid, to, purpose=""):
        raise RuntimeError("All call slots are in use")
    monkeypatch.setattr(telephony, "start_outbound_call", down)
    opened, _ = _open_and_closed_times()
    storage.queue_callback("demo_clinic", PHONE, "missed call", opened - dt.timedelta(minutes=5))
    assert callbacks.run_due(_utc(opened))["failed"] == 1
    assert storage.read_callbacks("demo_clinic")[0]["status"] == "failed"
    assert storage.pending_callbacks() == []


def test_the_dialer_does_nothing_while_switched_off(tmp_storage, monkeypatch):
    rang = []
    monkeypatch.setattr(telephony, "start_outbound_call", lambda *a, **k: rang.append(a))
    storage.queue_callback("demo_clinic", PHONE, "missed call")
    assert callbacks.run_due()["disabled"] is True and rang == []
    assert callbacks.start_worker(None) is None                 # never a thread in tests


# ---- the phone webhook ------------------------------------------------------------

@pytest.fixture
def line(phone, monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACtest")
    return phone


def test_missed_call_mode_rejects_free_and_queues_a_callback(line, monkeypatch):
    set_config("demo_clinic", missed_call_mode=True)
    data = {"To": "+15550001111", "From": PHONE, "CallSid": "CA1"}
    # Switched off: the agent answers as usual (never reject someone we won't call).
    res = post_voice(line["client"], data)
    assert "<Stream" in res.text and storage.pending_callbacks() == []
    monkeypatch.setenv("ENABLE_CALLBACKS", "true")
    res = post_voice(line["client"], {**data, "CallSid": "CA2"})
    assert '<Reject reason="busy"/>' in res.text and "<Stream" not in res.text
    assert [c["phone"] for c in storage.pending_callbacks()] == [PHONE]
    assert SpyLive.created == []                                # no model session spent


def test_a_number_called_back_recently_is_answered_not_rejected(line, monkeypatch):
    set_config("demo_clinic", missed_call_mode=True)
    monkeypatch.setenv("ENABLE_CALLBACKS", "true")
    storage.queue_callback("demo_clinic", PHONE, "missed call")
    [cb] = storage.pending_callbacks()
    storage.mark_callback(cb["id"], "done", "called")
    res = post_voice(line["client"], {"To": "+1", "From": PHONE, "CallSid": "CA3"})
    assert "<Stream" in res.text


def test_busy_lines_promise_a_callback_only_when_one_is_queued(line, monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_CALLS", "0")
    data = {"To": "+1", "From": PHONE, "CallSid": "CA1"}
    assert "call again" in post_voice(line["client"], data).text           # callbacks off
    monkeypatch.setenv("ENABLE_CALLBACKS", "true")
    assert "call you back" in post_voice(line["client"], data).text
    set_config("demo_clinic", callback_when_busy=False)
    storage.mark_callback(storage.pending_callbacks()[0]["id"], "dismissed")
    assert "call again" in post_voice(line["client"], {**data, "From": "+919111111111"}).text


def test_a_callback_call_opens_with_the_missed_call(line):
    data = {"To": PHONE, "From": "+15550001111", "CallSid": "CA9", "Direction": "outbound-api"}
    res = post_voice(line["client"], data, query="?client_id=demo_clinic&purpose=callback")
    params = ticket_from_twiml(res.text)
    assert params["purpose"] == "callback"
    tampered = {**params, "purpose": ""}
    assert telephony.check_stream_ticket(tampered, "CA9") == "bad ticket signature"
    assert stream(line["client"], params, call_sid="CA9") == 1000
    # An inbound call can't ask to be treated as a callback.
    res = post_voice(line["client"], {"To": "+1", "From": PHONE, "CallSid": "CA8"},
                     query="?purpose=callback")
    assert "purpose" not in ticket_from_twiml(res.text)


def test_the_callback_greeting_mentions_the_missed_call(tmp_storage):
    live = FakeLive()

    async def send(msg):
        pass
    agent = ReceptionistAgent("demo_clinic", llm=FakeLLM([]))
    bridge = telephony.TwilioBridge(agent, live, send, caller=PHONE, purpose="callback")
    asyncio.run(bridge.handle_twilio({"event": "start", "start": {"streamSid": "MZ1"}}))
    assert "missed call" in live.sent_texts[0]


def test_two_workers_never_ring_the_same_customer(dialer, monkeypatch):
    """A second worker runs while the first is still dialling: the row is
    already claimed, so the customer's phone rings once."""
    opened, _ = _open_and_closed_times()
    storage.queue_callback("demo_clinic", PHONE, "missed call", opened - dt.timedelta(minutes=5))

    def dial(cid, to, purpose=""):
        dialer.append(to)
        if len(dialer) == 1:
            callbacks.run_due(_utc(opened))          # the other worker, mid-dial
        return "CAOUT"
    monkeypatch.setattr(telephony, "start_outbound_call", dial)
    callbacks.run_due(_utc(opened))
    assert dialer == [PHONE]


def test_owner_sets_the_transfer_number_and_marks_callbacks_handled(tmp_storage, monkeypatch):
    import shutil
    import auth
    import server
    from fastapi.testclient import TestClient
    clients = tmp_storage / "clients"
    shutil.copytree(storage.CLIENTS_DIR, clients)
    monkeypatch.setattr(storage, "CLIENTS_DIR", clients)
    storage.clear_caches()
    monkeypatch.setattr(auth, "DB_FILE", tmp_storage / "voxagent.db")
    monkeypatch.setattr(auth, "LEGACY_USERS", tmp_storage / "no_users.json")
    monkeypatch.setattr(auth, "LEGACY_TOKENS", tmp_storage / "no_tokens.json")
    client, key = TestClient(server.app), {"X-Client-Key": DEMO_CODE}
    s = client.get("/api/business/demo_clinic/settings", headers=key).json()
    assert (s["handoff_phone"], s["missed_call_mode"], s["callback_when_busy"]) == ("", False, True)
    body = {k: v for k, v in s.items() if k in server.BusinessRequest.model_fields}
    bad = client.put("/api/business/demo_clinic/settings", json={**body, "handoff_phone": "12345"}, headers=key)
    assert bad.status_code == 422
    ok = client.put("/api/business/demo_clinic/settings",
                    json={**body, "handoff_phone": "098765 43210", "missed_call_mode": True}, headers=key)
    assert ok.json()["handoff_phone"] == "+919876543210" and ok.json()["missed_call_mode"] is True

    storage.queue_callback("demo_clinic", PHONE, "missed call")
    [cb] = client.get("/api/dashboard?client_id=demo_clinic", headers=key).json()["callbacks"]
    req = {"client_id": "demo_clinic", "callback_id": cb["id"]}
    assert client.post("/api/callbacks/handled", json=req,
                       headers={"X-Client-Key": SALON_CODE}).status_code == 401   # another business
    assert client.post("/api/callbacks/handled", json=req, headers=key).status_code == 200
    assert storage.pending_callbacks() == []
    assert client.post("/api/callbacks/handled", json=req, headers=key).status_code == 404
