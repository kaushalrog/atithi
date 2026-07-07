"""tts.py — text-to-speech, isolated behind one small class.

Same pattern as llm.py (principle 6 applied to a new provider): ALL edge-tts
code lives here. To switch to Sarvam voices in Stage 4, rewrite ONLY this file.

WHY edge-tts: Microsoft's neural voices — free, no API key, no signup, and with
genuinely good Indian voices (English, Hindi, Telugu, Tamil). Sarvam/ElevenLabs
sound even better but need paid keys; this gets Stage 2 working today.
"""

import asyncio

import edge_tts

VOICES = {
    "en": "en-IN-NeerjaNeural",
    "hi": "hi-IN-SwaraNeural",
    "te": "te-IN-ShrutiNeural",
    "ta": "ta-IN-PallaviNeural",
}


def detect_language(text: str) -> str:
    """Pick a voice by which script the reply is written in.

    Cheap but effective: count characters in the Devanagari, Telugu, and Tamil
    Unicode ranges. Tanglish/Hinglish is roman script, so it lands on the en-IN
    voice — which reads it with an Indian accent anyway. No ML needed.
    """
    counts = {"hi": 0, "te": 0, "ta": 0}
    for ch in text:
        code = ord(ch)
        if 0x0900 <= code <= 0x097F:
            counts["hi"] += 1
        elif 0x0C00 <= code <= 0x0C7F:
            counts["te"] += 1
        elif 0x0B80 <= code <= 0x0BFF:
            counts["ta"] += 1
    best = max(counts, key=counts.get)
    return best if counts[best] >= 3 else "en"


class EdgeTTS:
    def synthesize(self, text: str, out_path: str) -> str:
        """Write speech for `text` to an mp3 file. Returns the voice used."""
        voice = VOICES[detect_language(text)]
        # edge-tts is async-only; we hide that in here so callers stay simple.
        asyncio.run(self._synth(text, voice, out_path))
        return voice

    async def _synth(self, text: str, voice: str, out_path: str):
        await edge_tts.Communicate(text, voice).save(out_path)
