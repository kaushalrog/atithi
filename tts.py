"""tts.py — compatibility shim. The real voice logic lives in `voices.py`.

This module used to hold all the edge-tts code. It now forwards to
`voices.py`, which added two things edge-tts alone could not give us:
a choice of provider (Sarvam / ElevenLabs / Cartesia switch on the moment
their key appears) and a per-business, per-language routing policy.

New code should import `voices` directly. This file stays so that existing
callers (`voice_main.py`, older scripts) keep working unchanged.
"""

import voices
from voices import LANGUAGES, VoiceError, detect_language  # noqa: F401  (re-exported)

# Kept for callers that referenced the old names.
TTS_TIMEOUT_S = voices.SYNTH_TIMEOUT_S
VOICES = voices.EdgeProvider.voices

#: The old name for a synthesis failure. `voices.VoiceError` is the same idea,
#: widened to cover any provider rather than just a stalled edge-tts stream.
TTSTimeout = VoiceError


class EdgeTTS:
    """Old entry point. Now speaks through whichever provider is configured.

    The name is historical: with a Sarvam or ElevenLabs key in `.env` this no
    longer uses edge-tts at all. `config` lets a caller pass a business's YAML
    so its own voice choice is honoured.
    """

    def __init__(self, config: dict | None = None):
        self.config = config

    def synthesize_bytes(self, text: str, config: dict | None = None) -> bytes:
        audio, _plan = voices.synthesize(text, config or self.config)
        return audio

    def synthesize(self, text: str, out_path: str, config: dict | None = None) -> str:
        """Write speech to an mp3 file. Returns the voice that spoke."""
        audio, plan = voices.synthesize(text, config or self.config)
        with open(out_path, "wb") as f:
            f.write(audio)
        return plan["voice"]
