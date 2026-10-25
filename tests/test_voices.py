"""voices.py — language detection, provider routing and the fallback chain.

No network and no keys: the paid providers are driven through fakes, which is
also the point of the design — a provider is a small class with one method.
"""

import pytest

import voices


@pytest.fixture(autouse=True)
def clean_registry(monkeypatch):
    """Keys are read from the environment, so start every test from none."""
    for key in ("SARVAM_API_KEY", "ELEVENLABS_API_KEY", "CARTESIA_API_KEY",
                "ELEVENLABS_VOICE_ID", "CARTESIA_VOICE_ID"):
        monkeypatch.delenv(key, raising=False)
    voices.reset_registry()
    yield
    voices.reset_registry()


# ---- language detection ----------------------------------------------------------

def test_detects_the_script_a_reply_is_written_in():
    assert voices.detect_language("Your appointment is confirmed.") == "en"
    assert voices.detect_language("आपका अपॉइंटमेंट पक्का हो गया है।") == "hi"
    assert voices.detect_language("మీ అపాయింట్‌మెంట్ నిర్ధారించబడింది.") == "te"
    assert voices.detect_language("உங்கள் முன்பதிவு உறுதி செய்யப்பட்டது.") == "ta"


def test_tanglish_stays_on_the_indian_english_voice():
    assert voices.detect_language("naku appointment kavali anna, repu morning") == "en"


def test_one_foreign_word_does_not_flip_the_whole_reply():
    assert voices.detect_language("The word नमस्ते means hello.") == "en"


# ---- what is available ------------------------------------------------------------

def test_edge_needs_no_key_and_is_always_available():
    assert "edge" in voices.available_providers()


def test_a_provider_switches_on_when_its_key_appears(monkeypatch):
    assert "sarvam" not in voices.available_providers()
    monkeypatch.setenv("SARVAM_API_KEY", "sk-test")
    voices.reset_registry()
    assert "sarvam" in voices.available_providers()


def test_a_key_without_a_voice_id_is_not_enough(monkeypatch):
    """ElevenLabs/Cartesia need a voice id too — a key alone cannot speak."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-test")
    voices.reset_registry()
    assert "elevenlabs" not in voices.available_providers()
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "voice-123")
    voices.reset_registry()
    assert "elevenlabs" in voices.available_providers()


# ---- the routing policy ------------------------------------------------------------

def test_without_keys_everything_falls_to_edge_and_stays_native():
    for language in voices.LANGUAGES:
        plan = voices.plan(language)
        assert plan["provider"] == "edge"
        # No dedicated Indian voice configured, so there is nothing to gain by
        # leaving Gemini's native audio — keep the lower latency.
        assert plan["native_ok"] is True


def test_an_indian_language_goes_cascaded_once_a_real_voice_exists(monkeypatch):
    monkeypatch.setenv("SARVAM_API_KEY", "sk-test")
    voices.reset_registry()
    telugu = voices.plan("te")
    assert telugu["provider"] == "sarvam"
    assert telugu["native_ok"] is False        # worth the latency for the voice

    english = voices.plan("en")
    assert english["native_ok"] is True        # English stays fast on native audio


def test_a_business_can_force_a_provider_and_a_voice(monkeypatch):
    monkeypatch.setenv("SARVAM_API_KEY", "sk-test")
    voices.reset_registry()
    config = {"voice": {"provider": "sarvam", "te": "meera", "live": "Puck"}}
    plan = voices.plan("te", config)
    assert plan["provider"] == "sarvam" and plan["voice"] == "meera"
    assert voices.live_voice(config) == "Puck"


def test_live_voice_defaults_and_is_per_business():
    assert voices.live_voice(None) == voices.DEFAULT_LIVE_VOICE
    assert voices.live_voice({"voice": {"live": "Charon"}}) == "Charon"


def test_use_cascaded_on_phone_follows_the_text(monkeypatch):
    monkeypatch.setenv("SARVAM_API_KEY", "sk-test")
    voices.reset_registry()
    assert voices.use_cascaded_on_phone("మీ అపాయింట్‌మెంట్ నిర్ధారించబడింది.") is True
    assert voices.use_cascaded_on_phone("Your appointment is confirmed.") is False


# ---- synthesis and fallback ---------------------------------------------------------

class FakeProvider(voices.Provider):
    name = "fake"
    env_key = ""
    voices = {lang: f"{lang}-voice" for lang in voices.LANGUAGES}

    def __init__(self, audio=b"ID3fake", fail=False):
        self._audio, self._fail = audio, fail
        self.calls = []

    def synthesize(self, text, voice):
        self.calls.append((text, voice))
        if self._fail:
            raise voices.VoiceError("provider is down")
        return self._audio


def test_synthesize_returns_audio_and_the_plan_that_made_it(monkeypatch):
    fake = FakeProvider()
    monkeypatch.setitem(voices.registry(), "edge", fake)
    audio, plan = voices.synthesize("Hello there")
    assert audio == b"ID3fake"
    assert plan["provider"] == "edge" and plan["language"] == "en"
    assert fake.calls == [("Hello there", "en-voice")]


def test_a_failing_provider_falls_back_instead_of_going_silent(monkeypatch):
    """A wrong key or a vendor outage must degrade the voice, never the agent."""
    broken, working = FakeProvider(fail=True), FakeProvider(audio=b"ID3good")
    monkeypatch.setenv("SARVAM_API_KEY", "sk-test")
    voices.reset_registry()
    registry = voices.registry()
    monkeypatch.setitem(registry, "sarvam", broken)
    monkeypatch.setitem(registry, "edge", working)

    audio, plan = voices.synthesize("మీ అపాయింట్‌మెంట్ నిర్ధారించబడింది.")
    assert audio == b"ID3good"
    assert plan["provider"] == "edge" and plan["fell_back"] is True
    assert broken.calls and working.calls          # tried the good one first


def test_empty_audio_counts_as_a_failure(monkeypatch):
    monkeypatch.setitem(voices.registry(), "edge", FakeProvider(audio=b""))
    with pytest.raises(voices.VoiceError):
        voices.synthesize("Hello")


def test_every_provider_failing_raises_rather_than_returning_nothing(monkeypatch):
    monkeypatch.setitem(voices.registry(), "edge", FakeProvider(fail=True))
    with pytest.raises(voices.VoiceError):
        voices.synthesize("Hello")
