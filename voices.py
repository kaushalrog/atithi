"""voices.py — which voice speaks, and who synthesises it.

WHY this file exists: the phone line spoke every language through one
English-first Gemini voice (`Kore`), while the good native Indian voices
(te-IN, ta-IN) were only ever used by the web widget. Our best voices were on
the channel nobody hears and our worst on the one customers actually call.
Competitors sell "Standard" and "Premium" voice tiers because callers can hear
the difference immediately — an unnatural Telugu accent loses trust in one
sentence, while half a second of extra latency goes unnoticed.

Two things live here:

1. **A provider registry.** edge-tts is free and needs no key, so it is always
   available. Gnani, Sarvam, ElevenLabs and Cartesia switch themselves on the moment
   their key appears in `.env` — no code change, no redeploy. Adding a
   provider means adding one small class below and nothing else.

2. **The routing policy** (`plan`): for each language, who should speak and
   whether the phone call should stay on Gemini's native audio (fastest) or
   go through a dedicated Indian TTS (smoothest). English stays native;
   Telugu/Tamil/Hindi prefer a real Indian voice when one is configured.
   **The phone half of this policy is not wired yet** — see
   `use_cascaded_on_phone`. Today a call uses `live_voice()` only.

A business can override any of it in its YAML:

    voice:
      provider: sarvam        # force a provider for every language
      live: Puck              # the Gemini Live voice for native-audio calls
      te: anushka             # a specific voice id for one language

Nothing here raises on a missing key: an unconfigured provider is simply not
available, and `synthesize` falls back down the preference order to edge-tts,
so a wrong key can never take the phone line down.
"""

import asyncio
import os
import threading

import edge_tts

# Languages we route. The detector in this module decides which one a reply is.
LANGUAGES = ("en", "hi", "te", "ta", "kn", "ml")

# Who we would rather use for each language, best first. edge-tts is last
# because it is the free fallback that is always there, not because it is bad.
# Gnani leads: one voice speaks all six languages in the same timbre, so a
# caller who switches from Telugu to English hears the same receptionist.
PREFERENCE = {
    "en": ("gnani", "elevenlabs", "cartesia", "sarvam", "edge"),
    "hi": ("gnani", "sarvam", "elevenlabs", "cartesia", "edge"),
    "te": ("gnani", "sarvam", "elevenlabs", "cartesia", "edge"),
    "ta": ("gnani", "sarvam", "elevenlabs", "cartesia", "edge"),
    "kn": ("gnani", "sarvam", "elevenlabs", "cartesia", "edge"),
    "ml": ("gnani", "sarvam", "elevenlabs", "cartesia", "edge"),
}

# Gemini Live's own voice, used when a call stays on native audio.
DEFAULT_LIVE_VOICE = "Kore"

SYNTH_TIMEOUT_S = 15


class VoiceError(Exception):
    """Synthesis failed or timed out. The text reply still stands."""


# ---- language detection -------------------------------------------------------

def detect_language(text: str) -> str:
    """Pick a language by which script the reply is written in.

    Cheap but effective: count characters in the Devanagari, Telugu, Tamil,
    Kannada and Malayalam
    Unicode ranges. A script wins only when it makes up a real share of the
    letters — one Hindi word inside an English sentence must NOT flip the whole
    reply to the Hindi voice. Tanglish/Hinglish is roman script, so it lands on
    the Indian-English voice, which reads it with an Indian accent anyway.
    """
    counts = {"hi": 0, "te": 0, "ta": 0, "kn": 0, "ml": 0}
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
        elif 0x0C80 <= code <= 0x0CFF:
            counts["kn"] += 1
        elif 0x0D00 <= code <= 0x0D7F:
            counts["ml"] += 1
    best = max(counts, key=counts.get)
    if counts[best] >= 3 and counts[best] >= 0.3 * max(letters, 1):
        return best
    return "en"


# ---- providers ------------------------------------------------------------------

class Provider:
    """One text-to-speech vendor. Subclasses fill in `voices` and `_audio`."""

    name = ""
    env_key = ""          # empty means no key needed
    voices: dict = {}     # language -> default voice id
    needs_network = True

    def available(self) -> bool:
        return not self.env_key or bool(os.getenv(self.env_key, "").strip())

    def voice_for(self, language: str) -> str | None:
        return self.voices.get(language)

    def synthesize(self, text: str, voice: str) -> bytes:
        """mp3 bytes. Raises VoiceError on failure or timeout."""
        raise NotImplementedError


class EdgeProvider(Provider):
    """Microsoft neural voices through edge-tts: free, no key, decent Indian voices."""

    name = "edge"
    env_key = ""
    voices = {
        "en": "en-IN-NeerjaNeural",
        "hi": "hi-IN-SwaraNeural",
        "te": "te-IN-ShrutiNeural",
        "ta": "ta-IN-PallaviNeural",
        "kn": "kn-IN-SapnaNeural",
        "ml": "ml-IN-SobhanaNeural",
    }

    def synthesize(self, text: str, voice: str) -> bytes:
        async def collect() -> bytes:
            chunks = bytearray()
            async for chunk in edge_tts.Communicate(text, voice).stream():
                if chunk["type"] == "audio":
                    chunks.extend(chunk["data"])
            return bytes(chunks)

        try:
            return asyncio.run(asyncio.wait_for(collect(), globals()['SYNTH_TIMEOUT_S']))
        except TimeoutError as e:
            raise VoiceError(f"edge-tts: no speech after {globals()['SYNTH_TIMEOUT_S']}s") from e
        except Exception as e:                      # network, voice id, codec
            raise VoiceError(f"edge-tts: {e}") from e


class _HTTPProvider(Provider):
    """Shared plumbing for vendors with a simple 'POST text, get mp3' API.

    UNVERIFIED: these request shapes follow each vendor's published API but
    have not been run against a live key here. Check the vendor's current docs
    before trusting one in production — and because every call is wrapped in
    the fallback below, a wrong shape degrades to edge-tts instead of silence.
    """

    url = ""
    audio_field = None    # None means the body IS the audio

    def _headers(self) -> dict:
        raise NotImplementedError

    def _body(self, text: str, voice: str) -> dict:
        raise NotImplementedError

    def synthesize(self, text: str, voice: str) -> bytes:
        return self._post(self._body(text, voice))

    def _post(self, body: dict) -> bytes:
        import base64

        import httpx

        try:
            response = httpx.post(self.url, headers=self._headers(), json=body,
                                  timeout=SYNTH_TIMEOUT_S)
            response.raise_for_status()
            if self.audio_field is None:
                return response.content
            payload = response.json()
            chunk = payload
            for key in self.audio_field.split("."):
                chunk = chunk[key]
            if isinstance(chunk, list):            # some APIs return a list of chunks
                return b"".join(base64.b64decode(c) for c in chunk)
            return base64.b64decode(chunk)
        except Exception as e:
            raise VoiceError(f"{self.name}: {e}") from e


class SarvamProvider(_HTTPProvider):
    """Sarvam AI (Bulbul) — built for Indian languages. First choice for te/ta/hi."""

    name = "sarvam"
    env_key = "SARVAM_API_KEY"
    url = "https://api.sarvam.ai/text-to-speech"
    audio_field = "audios"
    voices = {"en": "anushka", "hi": "anushka", "te": "anushka", "ta": "anushka"}
    _LOCALE = {"en": "en-IN", "hi": "hi-IN", "te": "te-IN", "ta": "ta-IN"}

    def _headers(self) -> dict:
        return {"api-subscription-key": os.getenv(self.env_key, ""),
                "Content-Type": "application/json"}

    def _body(self, text: str, voice: str) -> dict:
        language = next((lang for lang, v in self.voices.items() if v == voice), "en")
        return {"text": text, "speaker": voice,
                "target_language_code": self._LOCALE.get(language, "en-IN")}


class ElevenLabsProvider(_HTTPProvider):
    """ElevenLabs — the most natural, and the one that clones a signature voice."""

    name = "elevenlabs"
    env_key = "ELEVENLABS_API_KEY"
    audio_field = None                     # the response body is the mp3
    _MODEL = "eleven_multilingual_v2"

    def __init__(self):
        # One multilingual voice id covers every language; a business can
        # override per language in its YAML.
        default = os.getenv("ELEVENLABS_VOICE_ID", "").strip()
        self.voices = {lang: default for lang in LANGUAGES} if default else {}

    @property
    def url(self) -> str:                  # type: ignore[override]
        return ""                          # built per voice in synthesize

    def available(self) -> bool:
        return bool(os.getenv(self.env_key, "").strip()) and bool(self.voices)

    def _headers(self) -> dict:
        return {"xi-api-key": os.getenv(self.env_key, ""),
                "Content-Type": "application/json"}

    def _body(self, text: str, voice: str) -> dict:
        return {"text": text, "model_id": self._MODEL}

    def synthesize(self, text: str, voice: str) -> bytes:
        import httpx
        try:
            response = httpx.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
                headers=self._headers(), json=self._body(text, voice),
                timeout=SYNTH_TIMEOUT_S)
            response.raise_for_status()
            return response.content
        except Exception as e:
            raise VoiceError(f"elevenlabs: {e}") from e


class CartesiaProvider(_HTTPProvider):
    """Cartesia (Sonic) — built for realtime agents, lowest added latency."""

    name = "cartesia"
    env_key = "CARTESIA_API_KEY"
    url = "https://api.cartesia.ai/tts/bytes"
    audio_field = None
    _MODEL = "sonic-2"

    def __init__(self):
        default = os.getenv("CARTESIA_VOICE_ID", "").strip()
        self.voices = {lang: default for lang in LANGUAGES} if default else {}

    def available(self) -> bool:
        return bool(os.getenv(self.env_key, "").strip()) and bool(self.voices)

    def _headers(self) -> dict:
        return {"X-API-Key": os.getenv(self.env_key, ""),
                "Cartesia-Version": "2024-06-10",
                "Content-Type": "application/json"}

    def _body(self, text: str, voice: str) -> dict:
        return {"model_id": self._MODEL, "transcript": text,
                "voice": {"mode": "id", "id": voice},
                "output_format": {"container": "mp3", "encoding": "mp3",
                                  "sample_rate": 24000}}


class GnaniProvider(_HTTPProvider):
    """Gnani Vachana (Timbre) — Indian voices; one voice speaks all our languages.

    Docs: https://docs.gnani.ai/api/TTS/tts-inference. POST JSON, key in the
    X-API-Key-ID header, and the response body is the audio itself (we ask
    for mp3, like every other provider here). On `timbre-v3.0` each voice
    speaks all ten supported languages, so one voice name covers our six.
    """

    name = "gnani"
    env_key = "GNANI_API_KEY"
    url = "https://api.vachana.ai/api/v1/tts/inference"
    audio_field = None
    _LOCALE = {"en": "en-IN", "hi": "hi-IN", "te": "te-IN", "ta": "ta-IN",
               "kn": "kn-IN", "ml": "ml-IN"}

    def __init__(self):
        voice = os.getenv("GNANI_VOICE", "").strip() or "Shivani"
        self.model = os.getenv("GNANI_MODEL", "").strip() or "timbre-v3.0"
        self.voices = {lang: voice for lang in LANGUAGES}

    def _headers(self) -> dict:
        return {"X-API-Key-ID": os.getenv(self.env_key, ""),
                "Content-Type": "application/json"}

    def _body(self, text: str, voice: str, language: str = "") -> dict:
        # "auto" lets Gnani detect the language from the script.
        return {"text": text, "model": self.model, "voice": voice,
                "language": self._LOCALE.get(language, "auto"),
                "speed": 1.0,
                "audio_config": {"container": "mp3", "sample_rate": 24000,
                                 "bitrate": "64k"}}

    def synthesize_in(self, text: str, voice: str, language: str) -> bytes:
        """Gnani needs the language as well as the voice (one voice, many languages)."""
        return self._post(self._body(text, voice, language))


_REGISTRY: dict[str, Provider] = {}
_registry_lock = threading.Lock()


def registry() -> dict[str, Provider]:
    """Provider instances, built once. Rebuilt when keys change (tests)."""
    with _registry_lock:
        if not _REGISTRY:
            for cls in (EdgeProvider, GnaniProvider, SarvamProvider,
                        ElevenLabsProvider, CartesiaProvider):
                instance = cls()
                _REGISTRY[instance.name] = instance
        # The real dict, not a copy: callers swap a provider in (tests do),
        # and a copy would silently ignore them.
        return _REGISTRY


def reset_registry():
    """Forget cached providers so new keys take effect (used by tests)."""
    with _registry_lock:
        _REGISTRY.clear()


def available_providers() -> list[str]:
    return [name for name, p in registry().items() if p.available()]


# ---- the routing policy ----------------------------------------------------------

def _voice_config(config: dict | None) -> dict:
    block = (config or {}).get("voice")
    return block if isinstance(block, dict) else {}


def plan(language: str, config: dict | None = None) -> dict:
    """Who should speak this language for this business, and how.

    Returns {language, provider, voice, native_ok, live_voice}. `native_ok`
    says the phone call may stay on Gemini's native audio (fastest); it is
    false for Indian languages once a dedicated provider is configured,
    because the smoother voice is worth the extra moment.
    """
    language = language if language in LANGUAGES else "en"
    chosen = _voice_config(config)
    providers = registry()

    forced = str(chosen.get("provider", "")).strip()
    order = (forced,) if forced else PREFERENCE.get(language, ("edge",))

    provider_name, voice = "edge", providers["edge"].voice_for(language)
    for name in order:
        provider = providers.get(name)
        if provider is None or not provider.available():
            continue
        candidate = str(chosen.get(language, "")).strip() or provider.voice_for(language)
        if candidate:
            provider_name, voice = name, candidate
            break

    # English keeps Gemini's native audio: it is already good and it is faster.
    # An Indian language goes cascaded only when a real Indian voice is on.
    native_ok = language == "en" or provider_name == "edge"
    return {
        "language": language,
        "provider": provider_name,
        "voice": voice,
        "native_ok": native_ok,
        "live_voice": str(chosen.get("live", "")).strip() or DEFAULT_LIVE_VOICE,
    }


def live_voice(config: dict | None = None) -> str:
    """The Gemini Live prebuilt voice for this business (was hardcoded 'Kore')."""
    return str(_voice_config(config).get("live", "")).strip() or DEFAULT_LIVE_VOICE


def use_cascaded_on_phone(text: str, config: dict | None = None) -> bool:
    """Should this reply be spoken by a dedicated TTS instead of native audio?

    NOT WIRED YET. The policy is correct and tested, but `telephony.py` only
    calls `live_voice()`, so a real phone call still speaks every language
    through one Gemini prebuilt voice. Routing it means taking Gemini off
    response_modalities=["AUDIO"] for those languages and streaming the TTS
    back as mu-law. Until that lands, do not read this function as shipped
    behaviour.
    """
    return not plan(detect_language(text), config)["native_ok"]


# ---- synthesis -------------------------------------------------------------------

def synthesize(text: str, config: dict | None = None,
               language: str | None = None) -> tuple[bytes, dict]:
    """Speak `text`. Returns (mp3 bytes, the plan that produced it).

    Falls back down the preference order on any provider failure, so a bad key
    or a vendor outage degrades the voice instead of silencing the agent.
    """
    language = language or detect_language(text)
    first = plan(language, config)
    providers = registry()

    tried: list[str] = []
    order = [first["provider"]] + [p for p in PREFERENCE.get(language, ("edge",))
                                   if p != first["provider"]]
    last_error: Exception | None = None
    for name in order:
        provider = providers.get(name)
        if provider is None or not provider.available():
            continue
        voice = (first["voice"] if name == first["provider"]
                 else provider.voice_for(language))
        if not voice:
            continue
        try:
            if hasattr(provider, "synthesize_in"):    # providers that take the language
                audio = provider.synthesize_in(text, voice, language)
            else:
                audio = provider.synthesize(text, voice)
            if not audio:
                raise VoiceError(f"{name}: empty audio")
            used = dict(first, provider=name, voice=voice, fell_back=bool(tried))
            return audio, used
        except Exception as e:                       # try the next provider
            last_error = e
            tried.append(name)
            print(f"  [voices] {name} failed ({e}); falling back")

    raise VoiceError(f"every provider failed for {language}: {last_error}")
