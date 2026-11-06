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
    assert voices.detect_language("ನಿಮ್ಮ ಅಪಾಯಿಂಟ್ಮೆಂಟ್ ಖಚಿತವಾಗಿದೆ.") == "kn"
    assert voices.detect_language("നിങ്ങളുടെ അപ്പോയിന്റ്മെന്റ് സ്ഥിരീകരിച്ചു.") == "ml"


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


# ---- Gnani (Vachana) -------------------------------------------------------------

class _FakeResponse:
    def __init__(self, content=b"ID3-fake-mp3"):
        self.content = content

    def raise_for_status(self):
        pass


def test_gnani_switches_on_with_its_key_and_leads_every_language(monkeypatch):
    assert "gnani" not in voices.available_providers()
    monkeypatch.setenv("GNANI_API_KEY", "vach_test")
    voices.reset_registry()
    assert "gnani" in voices.available_providers()
    for language in voices.LANGUAGES:
        assert voices.plan(language)["provider"] == "gnani"


def test_gnani_request_matches_the_documented_api(monkeypatch):
    """docs.gnani.ai/api/TTS/tts-inference: key in X-API-Key-ID, body is the audio."""
    monkeypatch.setenv("GNANI_API_KEY", "vach_test")
    voices.reset_registry()
    sent = {}

    def fake_post(url, headers, json, timeout):
        sent.update(url=url, headers=headers, json=json)
        return _FakeResponse()

    import httpx
    monkeypatch.setattr(httpx, "post", fake_post)
    audio, used = voices.synthesize("ನಾಳೆ ಬೆಳಿಗ್ಗೆ 10:30 ಕ್ಕೆ ಬುಕ್ ಮಾಡಲೇ?")

    assert audio == b"ID3-fake-mp3" and used["provider"] == "gnani"
    assert sent["url"] == "https://api.vachana.ai/api/v1/tts/inference"
    assert sent["headers"]["X-API-Key-ID"] == "vach_test"
    body = sent["json"]
    assert body["language"] == "kn-IN"                 # detected from the script
    assert body["model"] == "timbre-v3.0" and body["voice"] == "Shivani"
    assert body["audio_config"]["container"] == "mp3"


def test_gnani_voice_and_model_come_from_env(monkeypatch):
    monkeypatch.setenv("GNANI_API_KEY", "vach_test")
    monkeypatch.setenv("GNANI_VOICE", "Avinash")
    monkeypatch.setenv("GNANI_MODEL", "timbre-v2.5")
    voices.reset_registry()
    gnani = voices.registry()["gnani"]
    assert gnani.voice_for("ml") == "Avinash"
    assert gnani._body("hi", "Avinash", "ml")["model"] == "timbre-v2.5"


def test_a_gnani_outage_falls_back_to_edge(monkeypatch):
    monkeypatch.setenv("GNANI_API_KEY", "vach_test")
    voices.reset_registry()

    def broken(*args, **kwargs):
        raise ConnectionError("vachana down")

    import httpx
    monkeypatch.setattr(httpx, "post", broken)
    monkeypatch.setattr(voices.registry()["edge"], "synthesize", lambda text, voice: b"edge-mp3")
    audio, used = voices.synthesize("మీ అపాయింట్‌మెంట్ నిర్ధారించబడింది.")
    assert audio == b"edge-mp3"
    assert used["provider"] == "edge" and used["fell_back"] is True
