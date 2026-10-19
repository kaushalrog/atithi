"""tts.py — text-to-speech, isolated behind one small class.

Same pattern as llm.py (principle 6 applied to a new provider): ALL edge-tts
code lives here. To switch to Sarvam voices in Stage 4, rewrite ONLY this file.

WHY edge-tts: Microsoft's neural voices — free, no API key, no signup, and with
genuinely good Indian voices (English, Hindi, Telugu, Tamil). Sarvam/ElevenLabs
sound even better but need paid keys; this gets Stage 2 working today.
"""

import asyncio

import edge_tts

# A reply is a few seconds of speech; edge-tts normally streams it in about
# a second. A stalled stream used to hold the request (and a worker thread)
# for as long as the network allowed. The portal shows the text reply either way.
TTS_TIMEOUT_S = 15


class TTSTimeout(Exception):
    """Speech took longer than TTS_TIMEOUT_S; the text reply still stands."""

VOICES = {
    "en": "en-IN-NeerjaNeural",
    "hi": "hi-IN-SwaraNeural",
    "te": "te-IN-ShrutiNeural",
    "ta": "ta-IN-PallaviNeural",
}


def detect_language(text: str) -> str:
    """Pick a voice by which script the reply is written in.

    Cheap but effective: count characters in the Devanagari, Telugu, and Tamil
    Unicode ranges. A script wins only when it makes up a real share of the
    letters — one Hindi word inside an English sentence must NOT flip the whole
    reply to the Hindi voice. Tanglish/Hinglish is roman script, so it lands on
    the en-IN voice — which reads it with an Indian accent anyway. No ML needed.
    """
    counts = {"hi": 0, "te": 0, "ta": 0}
    letters = 0
    for ch in text:
        if ch.isalpha():
            letters += 1
        code = ord(ch)
        if 0x0900 <= code <= 0x097F:
            counts["hi"] += 1
        elif 0x0C00 <= code <= 0x0C7F:
            counts["te"] += 1
        elif 0x0B80 <= code <= 0x0BFF:
            counts["ta"] += 1
    best = max(counts, key=counts.get)
    if counts[best] >= 3 and counts[best] >= 0.3 * max(letters, 1):
        return best
    return "en"


class EdgeTTS:
    def synthesize(self, text: str, out_path: str) -> str:
        """Write speech for `text` to an mp3 file. Returns the voice used."""
        voice = VOICES[detect_language(text)]
        audio = self.synthesize_bytes(text)
        with open(out_path, "wb") as f:
            f.write(audio)
        return voice

    def synthesize_bytes(self, text: str) -> bytes:
        """Speech as mp3 bytes, straight from the network into memory.

        The web endpoint used to write a temp file and read it straight back
        just to hand the bytes to the browser — three pointless disk
        operations on the path between the agent answering and the caller
        hearing it.
        """
        voice = VOICES[detect_language(text)]
        try:
            return asyncio.run(asyncio.wait_for(self._collect(text, voice), TTS_TIMEOUT_S))
        except TimeoutError as e:
            raise TTSTimeout(f"no speech after {TTS_TIMEOUT_S}s") from e

    async def _collect(self, text: str, voice: str) -> bytes:
        chunks = bytearray()
        async for chunk in edge_tts.Communicate(text, voice).stream():
            if chunk["type"] == "audio":
                chunks.extend(chunk["data"])
        return bytes(chunks)
