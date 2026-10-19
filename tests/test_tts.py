"""Voice picking: reply script decides which Indian voice speaks."""

from tts import VOICES, detect_language


def test_script_detection():
    assert detect_language("Your appointment is confirmed.") == "en"
    assert detect_language("आपका अपॉइंटमेंट पक्का हो गया है।") == "hi"
    assert detect_language("మీ అపాయింట్‌మెంట్ నిర్ధారించబడింది.") == "te"
    assert detect_language("உங்கள் முன்பதிவு உறுதி செய்யப்பட்டது.") == "ta"


def test_tanglish_uses_indian_english_voice():
    assert detect_language("naku appointment kavali anna, repu morning") == "en"
    assert VOICES["en"].startswith("en-IN")


def test_a_few_foreign_chars_do_not_flip_the_voice():
    assert detect_language("The word नमस्ते means hello.") == "en"


def test_a_stalled_speech_stream_times_out(monkeypatch):
    """Perf audit F6: edge-tts had no timeout, so a stalled stream held the
    request (and a worker thread) indefinitely."""
    import asyncio
    import time

    import pytest

    import tts

    class Stalled:
        def __init__(self, text, voice):
            pass

        async def stream(self):
            await asyncio.Event().wait()
            yield {}

    monkeypatch.setattr(tts.edge_tts, "Communicate", Stalled)
    monkeypatch.setattr(tts, "TTS_TIMEOUT_S", 0.1)
    t0 = time.perf_counter()
    with pytest.raises(tts.TTSTimeout):
        tts.EdgeTTS().synthesize_bytes("Hello")
    assert time.perf_counter() - t0 < 1.0
