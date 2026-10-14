"""Telephony: audio conversion, call routing, and the Twilio<->Gemini bridge.

No Twilio account and no network needed — the bridge takes plain callables,
so a FakeLive and a list collector stand in for the real endpoints.
"""

import asyncio
import audioop
import base64
import math

import pytest
import yaml

import storage
import telephony
from telephony import AudioConverter, TwilioBridge, resolve_client
from agent import ReceptionistAgent


# ---- audio conversion -----------------------------------------------------------

def make_tone_pcm(rate: int, ms: int) -> bytes:
    """A 440 Hz test tone as 16-bit PCM."""
    n = rate * ms // 1000
    samples = (int(12000 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(n))
    return b"".join(s.to_bytes(2, "little", signed=True) for s in samples)


def test_twilio_to_gemini_doubles_sample_count():
    conv = AudioConverter()
    mulaw = audioop.lin2ulaw(make_tone_pcm(8000, 100), 2)  # 100ms at 8 kHz
    pcm16k = conv.twilio_to_gemini(mulaw)
    # 8 kHz mulaw (1 byte/sample) -> 16 kHz PCM (2 bytes/sample) = 4x the bytes
    assert len(pcm16k) == pytest.approx(len(mulaw) * 4, rel=0.05)


def test_gemini_to_twilio_shrinks_to_phone_rate():
    conv = AudioConverter()
    pcm24k = make_tone_pcm(24000, 100)
    mulaw = conv.gemini_to_twilio(pcm24k)
    # 24 kHz PCM (2 bytes) -> 8 kHz mulaw (1 byte) = 1/6 of the bytes
    assert len(mulaw) == pytest.approx(len(pcm24k) / 6, rel=0.05)


def test_roundtrip_preserves_signal_energy():
    conv = AudioConverter()
    original = make_tone_pcm(24000, 200)
    down = conv.gemini_to_twilio(original)
    back_up = conv.twilio_to_gemini(down)
    assert audioop.rms(back_up, 2) == pytest.approx(audioop.rms(original, 2), rel=0.25)


# ---- call routing ----------------------------------------------------------------

def test_resolve_client_priority(tmp_path, monkeypatch):
    clients_dir = tmp_path / "clients"
    clients_dir.mkdir()
    (clients_dir / "mapped_biz.yaml").write_text(
        yaml.safe_dump({"business_name": "Mapped", "twilio_number": "+15550001111"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(telephony, "BASE_DIR", tmp_path)
    monkeypatch.setattr(storage, "CLIENTS_DIR", clients_dir)  # routing reads via storage
    storage.clear_caches()
    monkeypatch.setenv("DEFAULT_CLIENT", "fallback_biz")

    assert resolve_client("+15550001111", explicit="chosen") == "chosen"
    assert resolve_client("+15550001111") == "mapped_biz"
    assert resolve_client("+19999999999") == "fallback_biz"


# ---- the bridge -------------------------------------------------------------------

class FakeLive:
    def __init__(self, events=()):
        self._events = list(events)
        self.sent_audio, self.sent_texts, self.tool_results = [], [], []

    async def send_audio(self, chunk):
        self.sent_audio.append(chunk)

    async def send_text(self, text):
        self.sent_texts.append(text)

    async def send_tool_results(self, results):
        self.tool_results.append(results)

    async def events(self):
        for e in self._events:
            yield e


def make_bridge(fake_llm, live, sent):
    agent = ReceptionistAgent("demo_clinic", llm=fake_llm([]))

    async def collect(msg):  # the real send_json (ws.send_json) is async too
        sent.append(msg)

    return TwilioBridge(agent, live, collect, caller="+919876543210")


def test_bridge_start_and_media(tmp_storage, fake_llm):
    live, sent = FakeLive(), []
    bridge = make_bridge(fake_llm, live, sent)

    keep = asyncio.run(bridge.handle_twilio(
        {"event": "start", "start": {"streamSid": "MZ123", "customParameters": {}}}))
    assert keep and bridge.stream_sid == "MZ123"
    assert live.sent_texts, "agent must be prompted to greet the caller first"

    mulaw = audioop.lin2ulaw(make_tone_pcm(8000, 20), 2)
    payload = base64.b64encode(mulaw).decode()
    asyncio.run(bridge.handle_twilio({"event": "media", "media": {"payload": payload}}))
    assert len(live.sent_audio) == 1
    # ratecv warm-up can shave a sample or two off the first chunk
    assert len(live.sent_audio[0]) == pytest.approx(len(mulaw) * 4, rel=0.05)

    assert asyncio.run(bridge.handle_twilio({"event": "stop"})) is False


def test_bridge_pumps_audio_interruption_tools_and_history(tmp_storage, fake_llm):
    from conftest import open_day, open_times
    date = open_day()
    live = FakeLive(events=[
        {"type": "audio", "data": make_tone_pcm(24000, 60)},
        {"type": "interrupted"},
        {"type": "tool_calls", "calls": [
            {"id": "t1", "name": "check_availability", "args": {"date": date}}]},
        {"type": "user_text", "text": "how much is cleaning?"},
        {"type": "agent_text", "text": "Cleaning is ₹1,200."},
        {"type": "turn_complete"},
    ])
    sent = []
    bridge = make_bridge(fake_llm, live, sent)
    bridge.stream_sid = "MZ123"
    asyncio.run(bridge.pump_gemini())

    events = [m["event"] for m in sent]
    assert events == ["media", "clear"]
    assert live.tool_results and live.tool_results[0][0]["name"] == "check_availability"
    assert live.tool_results[0][0]["result"]["available_slots"] == open_times(date=date)
    roles = [m["role"] for m in bridge.agent.history]
    assert roles == ["user", "assistant"]

    bridge.finish()
    logs = storage.read_call_logs("demo_clinic")
    assert len(logs) == 1 and logs[0]["channel"] == "phone"
    assert "+919876543210" in logs[0]["transcript"]  # caller id preserved


# ---- the inbound webhook and the media stream (audit H1) -----------------------------
#
# Every test runs offline: signatures are computed with Twilio's own validator
# and a made-up auth token; GeminiLive and the agent are spies, so a rejected
# connection can be proven to have allocated NOTHING.

import shutil
import time
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from twilio.request_validator import RequestValidator

import llm
import server

TOKEN = "test-auth-token"
PUBLIC = "https://demo.ngrok.app"
WEBHOOK_URL = "https://testserver/twilio/voice"   # what TestClient's request.url becomes


def sign(url, params=None):
    return RequestValidator(TOKEN).compute_signature(url, params or {})


class SpyLive:
    created = []

    def __init__(self):
        SpyLive.created.append(self)

    async def connect(self, system_prompt, tools):
        pass

    async def close(self):
        pass

    async def send_text(self, text):
        pass

    async def send_audio(self, chunk):
        pass

    async def events(self):
        return
        yield


@pytest.fixture
def phone(tmp_storage, fake_llm, monkeypatch):
    """Live calls enabled and fully configured, with spies on every resource."""
    monkeypatch.setenv("ENABLE_LIVE_CALLS", "true")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", TOKEN)
    monkeypatch.setenv("PUBLIC_BASE_URL", PUBLIC)
    monkeypatch.setenv("MAX_CONCURRENT_CALLS", "3")
    clients = tmp_storage / "clients"
    clients.mkdir()
    shutil.copy(storage.CLIENTS_DIR / "demo_clinic.yaml", clients)
    cfg = yaml.safe_load((clients / "demo_clinic.yaml").read_text(encoding="utf-8"))
    cfg["billing"] = {"plan": "trial", "paid_until": "2000-01-01"}
    (clients / "expired_biz.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setattr(storage, "CLIENTS_DIR", clients)
    storage.clear_caches()
    monkeypatch.setattr(telephony, "_used_tickets", {})
    monkeypatch.setattr(telephony, "_active_calls", 0)
    monkeypatch.setattr(telephony, "_pending_tickets", {})
    SpyLive.created = []
    monkeypatch.setattr(llm, "GeminiLive", SpyLive)
    agents = []

    def make_agent(client_id):
        agents.append(client_id)
        return ReceptionistAgent(client_id, llm=fake_llm([]))
    monkeypatch.setattr(telephony, "ReceptionistAgent", make_agent)
    return {"client": TestClient(server.app), "agents": agents}


def post_voice(client, data, signature=None, query=""):
    return client.post("/twilio/voice" + query, data=data, headers={
        "X-Twilio-Signature": signature if signature is not None
        else sign(WEBHOOK_URL + query, data)})


def stream(client, params, call_sid="CA1", signature=None):
    """Open /twilio/stream like Twilio would, send start + stop, and return the
    server's close code: 1008 = rejected, 1000 = the call ran and hung up."""
    headers = {"x-twilio-signature": signature if signature is not None
               else sign(telephony.stream_url())}
    try:
        with client.websocket_connect("/twilio/stream", headers=headers) as ws:
            ws.send_json({"event": "connected"})
            ws.send_json({"event": "start", "start": {
                "streamSid": "MZ1", "callSid": call_sid, "customParameters": params}})
            ws.send_json({"event": "stop"})
            ws.receive_text()        # server closes after stop (or after a rejection)
    except WebSocketDisconnect as e:
        return e.code
    raise AssertionError("server sent data instead of closing")


def ticket_from_twiml(xml_text):
    root = ET.fromstring(xml_text)
    return {p.get("name"): p.get("value") for p in root.iter("Parameter")}


def test_signed_call_gets_twiml_with_a_ticket_and_the_stream_runs(phone):
    data = {"To": "+15550001111", "From": "+919876543210", "CallSid": "CA1"}
    res = post_voice(phone["client"], data)
    assert res.status_code == 200
    root = ET.fromstring(res.text)
    assert root.find("Connect/Stream").get("url") == "wss://demo.ngrok.app/twilio/stream"
    params = ticket_from_twiml(res.text)
    assert params["caller"] == "+919876543210" and params["client_id"] == "demo_clinic"
    assert params["ticket"] and params["call_sid"] == "CA1"

    assert stream(phone["client"], params) == 1000
    assert len(SpyLive.created) == 1 and phone["agents"] == ["demo_clinic"]
    assert telephony._active_calls == 0                    # slot released
    assert storage.read_call_logs("demo_clinic") == []     # no turns spoken → not a call


def test_twiml_attributes_are_escaped(phone):
    """Audit L2 (reproduced as R8b): From used to inject TwiML."""
    evil = '+2"/></Stream></Connect><Dial>+15550000000</Dial><Connect><Stream url="x'
    res = post_voice(phone["client"], {"To": "+1", "From": evil, "CallSid": "CA1"})
    assert res.status_code == 200
    root = ET.fromstring(res.text)                   # still well-formed XML
    assert root.find(".//Dial") is None
    assert ticket_from_twiml(res.text)["caller"] == evil


@pytest.mark.parametrize("case", ["forged", "missing"])
def test_webhook_rejects_bad_or_missing_signature(phone, case):
    sig = "forged" if case == "forged" else ""
    res = post_voice(phone["client"], {"To": "+1", "CallSid": "CA1"}, signature=sig)
    assert res.status_code == 403


def test_webhook_fails_closed_without_an_auth_token(phone, monkeypatch):
    """The old "local mode" answered anyone when TWILIO_AUTH_TOKEN was empty."""
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "")
    res = phone["client"].post("/twilio/voice", data={"To": "+1"})
    assert res.status_code == 503


def test_live_calls_off_by_default(phone, monkeypatch):
    monkeypatch.delenv("ENABLE_LIVE_CALLS")
    assert post_voice(phone["client"], {"To": "+1", "CallSid": "CA1"}).status_code == 503
    params = telephony.mint_stream_ticket("CA1", "demo_clinic", "")
    assert stream(phone["client"], params) == 1008
    with pytest.raises(RuntimeError, match="ENABLE_LIVE_CALLS"):
        telephony.start_outbound_call("demo_clinic", "+919876543210")
    assert SpyLive.created == [] and phone["agents"] == []


def test_webhook_answers_inactive_or_unknown_business_with_an_apology(phone):
    for query in ("?client_id=expired_biz", "?client_id=no_such_biz"):
        res = post_voice(phone["client"], {"To": "+1", "CallSid": "CA1"}, query=query)
        assert res.status_code == 200 and "<Say>" in res.text and "<Stream" not in res.text


def test_webhook_says_busy_at_the_call_limit(phone, monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_CALLS", "0")
    res = post_voice(phone["client"], {"To": "+1", "CallSid": "CA1"})
    assert "busy" in res.text and "<Stream" not in res.text


def good_ticket(**overrides):
    params = telephony.mint_stream_ticket("CA1", "demo_clinic", "+919876543210")
    params.update(overrides)
    return params


@pytest.mark.parametrize("make_params,call_sid,reason", [
    (lambda: {}, "CA1", "missing ticket"),
    (lambda: good_ticket(client_id="lakshmi_beauty_salon"), "CA1", "bad ticket signature"),
    (lambda: good_ticket(ticket="0" * 64), "CA1", "bad ticket signature"),
    (lambda: good_ticket(ticket="\u00e9" * 64), "CA1", "bad ticket signature"),  # non-ASCII
    (lambda: good_ticket(), "CA_OTHER", "different call"),
    (lambda: telephony.mint_stream_ticket("CA1", "demo_clinic", "",
                                          now=time.time() - 3600), "CA1", "expired"),
    (lambda: telephony.mint_stream_ticket("CA1", "no_such_biz", ""), "CA1", "unknown business"),
    (lambda: telephony.mint_stream_ticket("CA1", "expired_biz", ""), "CA1", "plan inactive"),
], ids=["no-ticket", "tampered-business", "tampered-signature", "non-ascii-ticket",
        "other-call", "expired", "unknown-business", "inactive-plan"])
def test_stream_rejects_before_allocating_anything(phone, capsys, make_params, call_sid, reason):
    # Tickets are minted inside the test (not at collection time), and each
    # case asserts ITS gate's reason — so a case can't pass because an
    # earlier, unrelated gate (e.g. expiry on a slow run) rejected it.
    assert stream(phone["client"], make_params(), call_sid=call_sid) == 1008
    assert reason in capsys.readouterr().out
    assert SpyLive.created == [] and phone["agents"] == []


def test_stream_without_a_start_message_is_rejected(phone):
    headers = {"x-twilio-signature": sign(telephony.stream_url())}
    with pytest.raises(WebSocketDisconnect) as closed:
        with phone["client"].websocket_connect("/twilio/stream", headers=headers) as ws:
            for _ in range(telephony.MAX_PRE_START_MESSAGES):
                ws.send_json({"event": "connected"})
            ws.receive_text()
    assert closed.value.code == 1008
    assert SpyLive.created == [] and phone["agents"] == []


@pytest.mark.parametrize("signature", ["", "forged"])
def test_stream_rejects_bad_handshake_signature(phone, signature):
    assert stream(phone["client"], good_ticket(), signature=signature) == 1008
    assert SpyLive.created == [] and phone["agents"] == []


def test_stream_ticket_cannot_be_replayed(phone):
    params = good_ticket()
    assert stream(phone["client"], params) == 1000
    assert stream(phone["client"], params) == 1008
    assert len(SpyLive.created) == 1


def test_stream_enforces_the_concurrent_call_limit(phone, monkeypatch):
    monkeypatch.setattr(telephony, "_active_calls", 3)        # three calls in progress
    assert stream(phone["client"], good_ticket()) == 1008
    assert SpyLive.created == []


def test_call_slot_is_released_when_the_model_fails_to_connect(phone, monkeypatch):
    async def broken(self, *a):
        raise ConnectionError("Gemini unreachable")
    monkeypatch.setattr(SpyLive, "connect", broken)
    with pytest.raises(ConnectionError):
        stream(phone["client"], good_ticket())
    assert telephony._active_calls == 0


# ---- review fixes: stream robustness and call-slot accounting (D2 #8, D3 #11) -------

def test_malformed_frame_before_start_is_a_clean_rejection(phone):
    """#8: a non-JSON frame used to escape as an unhandled exception."""
    headers = {"x-twilio-signature": sign(telephony.stream_url())}
    with pytest.raises(WebSocketDisconnect) as closed:
        with phone["client"].websocket_connect("/twilio/stream", headers=headers) as ws:
            ws.send_text("this is not json")
            ws.receive_text()
    assert closed.value.code == 1008 and SpyLive.created == []


def test_silent_socket_is_closed_after_the_start_timeout(phone, monkeypatch):
    """#8: a socket that never sends 'start' used to stay open forever."""
    monkeypatch.setattr(telephony, "PRE_START_TIMEOUT_S", 0.2)
    headers = {"x-twilio-signature": sign(telephony.stream_url())}
    with pytest.raises(WebSocketDisconnect) as closed:
        with phone["client"].websocket_connect("/twilio/stream", headers=headers) as ws:
            ws.receive_text()                    # we send nothing at all
    assert closed.value.code == 1008 and SpyLive.created == []


def test_issued_tickets_hold_a_call_slot_until_used(phone, monkeypatch):
    """#11: a burst of calls all passed the webhook check, then the extras
    were dropped silently at the stream. Issued tickets now reserve a slot."""
    monkeypatch.setenv("MAX_CONCURRENT_CALLS", "1")
    first = post_voice(phone["client"], {"To": "+1", "From": "+2", "CallSid": "CA1"})
    assert "<Stream" in first.text
    second = post_voice(phone["client"], {"To": "+1", "From": "+3", "CallSid": "CA2"})
    assert "busy" in second.text and "<Stream" not in second.text
    assert stream(phone["client"], ticket_from_twiml(first.text)) == 1000   # slot used, freed
    third = post_voice(phone["client"], {"To": "+1", "From": "+4", "CallSid": "CA3"})
    assert "<Stream" in third.text


def test_a_forged_ticket_cannot_free_another_calls_slot(phone, monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_CALLS", "1")
    post_voice(phone["client"], {"To": "+1", "From": "+2", "CallSid": "CA1"})
    stream(phone["client"], {"call_sid": "CA1", "client_id": "demo_clinic", "caller": "",
                             "exp": "9999999999", "ticket": "0" * 64}, call_sid="CA1")
    res = post_voice(phone["client"], {"To": "+1", "From": "+3", "CallSid": "CA2"})
    assert "busy" in res.text                      # CA1's slot is still reserved


def test_an_unused_ticket_frees_its_slot_when_it_expires(phone, monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_CALLS", "1")
    post_voice(phone["client"], {"To": "+1", "From": "+2", "CallSid": "CA1"})
    later = time.time() + telephony.STREAM_TICKET_TTL_S + 1
    monkeypatch.setattr(telephony.time, "time", lambda: later)
    res = post_voice(phone["client"], {"To": "+1", "From": "+3", "CallSid": "CA2"})
    assert "<Stream" in res.text


@pytest.mark.parametrize("why", ["lines-full", "plan-inactive"])
def test_outbound_call_refused_before_dialling(phone, monkeypatch, why):
    """#11: the business must not ring a customer it cannot then serve."""
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC1")
    monkeypatch.setenv("TWILIO_NUMBER", "+15550001111")
    dialled = []
    import twilio.rest
    monkeypatch.setattr(twilio.rest, "Client", lambda *a: dialled.append(a))
    client_id = "demo_clinic"
    if why == "lines-full":
        monkeypatch.setattr(telephony, "_active_calls", 3)
    else:
        client_id = "expired_biz"
    reason = "call slots" if why == "lines-full" else "no active plan"
    with pytest.raises(RuntimeError, match=reason):
        telephony.start_outbound_call(client_id, "+919876543210")
    assert dialled == []


# ---- review cycle 2 (approved D6 #3-#4, D7 #5-#7, cycle-2 test gaps) --------------------

def test_every_call_slot_table_access_holds_the_lock(phone, monkeypatch):
    """#3: outbound calls touch the slot table from a worker thread while the
    event loop prunes it. The race ('dictionary changed size during
    iteration') is too rare under CPython's GIL to reproduce reliably in a
    test, so this checks the contract instead: every access holds the lock."""
    import threading as th
    real, held = th.Lock(), []

    class RecordingLock:
        def __enter__(self):
            real.acquire()
            held.append(True)

        def __exit__(self, *exc):
            real.release()
    monkeypatch.setattr(telephony, "_slots_lock", RecordingLock())
    telephony._reserve_slot("CA1", time.time() + 30)
    telephony._calls_in_flight()
    telephony._release_slot("CA1")
    post_voice(phone["client"], {"To": "+1", "From": "+2", "CallSid": "CA2"})
    assert len(held) >= 5                       # 3 direct + webhook check and reserve


def test_idle_pre_start_sockets_are_capped(phone, monkeypatch):
    """#4: a replayed handshake signature allowed unlimited idle sockets."""
    monkeypatch.setattr(telephony, "MAX_PRE_START_SOCKETS", 1)
    headers = {"x-twilio-signature": sign(telephony.stream_url())}
    with phone["client"].websocket_connect("/twilio/stream", headers=headers):
        with pytest.raises(WebSocketDisconnect) as closed:
            with phone["client"].websocket_connect("/twilio/stream", headers=headers) as second:
                second.receive_text()
        assert closed.value.code == 1008


def test_reserved_slot_lasts_30_seconds_not_the_ticket_lifetime(phone, monkeypatch):
    """#5: a stream rejected before 'start' held its slot for 2 minutes."""
    monkeypatch.setenv("MAX_CONCURRENT_CALLS", "1")
    post_voice(phone["client"], {"To": "+1", "From": "+2", "CallSid": "CA1"})
    later = time.time() + telephony.PENDING_SLOT_S + 1
    assert later < time.time() + telephony.STREAM_TICKET_TTL_S
    monkeypatch.setattr(telephony.time, "time", lambda: later)
    res = post_voice(phone["client"], {"To": "+1", "From": "+3", "CallSid": "CA2"})
    assert "<Stream" in res.text


def test_answered_outbound_call_never_hears_busy(phone, monkeypatch):
    """#6: lines were checked when dialling; on answer the customer must not
    hear 'all our lines are busy'. #7: the caller number is the dialled one."""
    monkeypatch.setenv("MAX_CONCURRENT_CALLS", "0")
    data = {"To": "+919876543210", "From": "+15550001111", "CallSid": "CA9",
            "Direction": "outbound-api"}
    res = post_voice(phone["client"], data, query="?client_id=demo_clinic")
    assert "<Stream" in res.text and "busy" not in res.text
    assert ticket_from_twiml(res.text)["caller"] == "+919876543210"


@pytest.mark.parametrize("frame", ['{"event": "start", "start": "x"}',
                                   '{"event": "start", "start": ["x"]}', "[1, 2]"])
def test_odd_start_messages_are_clean_rejections(phone, frame):
    """Cycle-2 finding: the 'malformed start' guard ran one line too late."""
    headers = {"x-twilio-signature": sign(telephony.stream_url())}
    with pytest.raises(WebSocketDisconnect) as closed:
        with phone["client"].websocket_connect("/twilio/stream", headers=headers) as ws:
            ws.send_text(frame)
            ws.send_text(frame)
            ws.receive_text()
    assert closed.value.code == 1008


def test_binary_frame_before_start_is_a_clean_rejection(phone):
    headers = {"x-twilio-signature": sign(telephony.stream_url())}
    with pytest.raises(WebSocketDisconnect) as closed:
        with phone["client"].websocket_connect("/twilio/stream", headers=headers) as ws:
            ws.send_bytes(b"\x00\x01")
            ws.receive_text()
    assert closed.value.code == 1008


def test_a_signed_ticket_for_the_wrong_call_still_gives_back_its_slot(phone, monkeypatch):
    """Documented intent: once a GENUINE ticket is presented, its reserved slot
    is used or given up, whatever the outcome (only unsigned input can't free one)."""
    monkeypatch.setenv("MAX_CONCURRENT_CALLS", "1")
    first = post_voice(phone["client"], {"To": "+1", "From": "+2", "CallSid": "CA1"})
    assert stream(phone["client"], ticket_from_twiml(first.text), call_sid="CA_OTHER") == 1008
    res = post_voice(phone["client"], {"To": "+1", "From": "+3", "CallSid": "CA2"})
    assert "<Stream" in res.text


def test_outbound_refused_while_slots_are_reserved_by_pending_tickets(phone, monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_CALLS", "1")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC1")
    monkeypatch.setenv("TWILIO_NUMBER", "+15550001111")
    dialled = []
    import twilio.rest
    monkeypatch.setattr(twilio.rest, "Client", lambda *a: dialled.append(a))
    post_voice(phone["client"], {"To": "+1", "From": "+2", "CallSid": "CA1"})   # holds the slot
    with pytest.raises(RuntimeError, match="call slots"):
        telephony.start_outbound_call("demo_clinic", "+919876543210")
    assert dialled == []
