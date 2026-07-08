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
    live = FakeLive(events=[
        {"type": "audio", "data": make_tone_pcm(24000, 60)},
        {"type": "interrupted"},
        {"type": "tool_calls", "calls": [
            {"id": "t1", "name": "check_availability", "args": {"date": "2026-07-09"}}]},
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
    assert "09:30" in live.tool_results[0][0]["result"]["available_slots"]
    roles = [m["role"] for m in bridge.agent.history]
    assert roles == ["user", "assistant"]

    bridge.finish()
    logs = storage.read_call_logs("demo_clinic")
    assert len(logs) == 1 and logs[0]["channel"] == "phone"
    assert "+919876543210" in logs[0]["transcript"]  # caller id preserved


# ---- the inbound webhook -----------------------------------------------------------

def test_voice_webhook_returns_stream_twiml(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://demo.ngrok.app")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "")  # no signature check in local mode
    from fastapi.testclient import TestClient
    from server import app

    client = TestClient(app)
    res = client.post("/twilio/voice", data={"To": "+15550001111", "From": "+919876543210"})
    assert res.status_code == 200
    assert "wss://demo.ngrok.app/twilio/stream" in res.text
    assert 'name="caller" value="+919876543210"' in res.text


def test_voice_webhook_rejects_bad_signature(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://demo.ngrok.app")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "real-token-set")
    from fastapi.testclient import TestClient
    from server import app

    client = TestClient(app)
    res = client.post("/twilio/voice", data={"To": "+15550001111"},
                      headers={"X-Twilio-Signature": "forged"})
    assert res.status_code == 403
