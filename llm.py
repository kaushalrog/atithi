"""llm.py — the ONLY file in VoxAgent that talks to Gemini.

WHY (architecture principle 6): the rest of the codebase speaks a tiny,
provider-neutral format. If we ever move to another provider (OpenAI, Anthropic,
a local model), we rewrite ONLY this file. Nothing else imports google-genai.

The neutral message format used everywhere else:

    {"role": "system",    "text": "..."}                      the system prompt
    {"role": "user",      "text": "..."}                      customer said this
    {"role": "assistant", "text": "..."}                      agent said this
    {"role": "assistant", "tool_calls": [{"name", "args"}]}   agent wants tools run
    {"role": "tool",      "name": "...", "result": {...}}     a tool's output

Tools are plain JSON-schema dicts:

    {"name": "...", "description": "...", "parameters": {...}}

send(messages, tools) returns:

    {"text": str | None, "tool_calls": [{"name": str, "args": dict}]}
"""

import os
import time

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

load_dotenv()

MODEL = "gemini-2.5-flash"


class QuotaExhausted(Exception):
    """The API key's DAILY free-tier quota is used up (resets at midnight
    Pacific time). Retrying is pointless — upgrade to the paid tier or wait."""
# "-latest" alias: tracks the newest 2.5 native-audio model so we don't chase
# preview names as Google retires them (the 07-2025 half-cascade one is already gone).
LIVE_MODEL = "gemini-2.5-flash-native-audio-latest"


def _tools_to_gemini(tools):
    """Convert our plain JSON-schema tool dicts to Gemini's format.
    Shared by the turn-based (GeminiLLM) and streaming (GeminiLive) classes."""
    if not tools:
        return None
    return [
        types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name=t["name"],
                    description=t["description"],
                    parameters=t["parameters"],
                )
                for t in tools
            ]
        )
    ]


class GeminiLLM:
    def __init__(self, model: str = MODEL):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Copy .env.example to .env and add your "
                "key (see SETUP.md for how to get one)."
            )
        self.client = genai.Client(api_key=api_key)
        self.model = model

    def send(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """One model turn: neutral messages in -> neutral response out."""
        system_prompt, contents = self._to_gemini_messages(messages)
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=_tools_to_gemini(tools),
            # A receptionist reply doesn't need chain-of-thought; turning
            # thinking off makes replies faster and saves free-tier quota.
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
        response = self._call_with_retry(contents, config)
        return self._normalize(response)

    def transcribe(self, audio_bytes: bytes, mime_type: str = "audio/wav") -> str:
        """Speech-to-text via Gemini's audio understanding (Stage 2).

        WHY here and not a separate stt.py: this IS Gemini-specific code, and
        principle 6 says all of it lives in this one file. When Stage 3 needs
        streaming STT (Deepgram/Sarvam), that becomes its own provider module
        and this method simply stops being called — nothing else changes.
        Returns "" when no speech was detected.
        """
        prompt = (
            "You are a transcription engine. Transcribe the speech in this audio "
            "exactly as spoken. It may be English, Telugu, Hindi, Tamil, or a "
            "roman-script mix (Tanglish/Hinglish) — keep the speaker's own words, "
            "language and script. Output ONLY the transcript, no quotes, no "
            "commentary. If there is no clear speech, output exactly: [no speech]"
        )
        contents = [types.Part.from_bytes(data=audio_bytes, mime_type=mime_type), prompt]
        config = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
        response = self._call_with_retry(contents, config)
        text = (self._normalize(response)["text"] or "").strip()
        return "" if text == "[no speech]" else text

    # ---- neutral format -> Gemini format -----------------------------------

    def _to_gemini_messages(self, messages):
        system_prompt = None
        contents = []
        for msg in messages:
            role = msg["role"]
            if role == "system":
                # Gemini takes the system prompt as config, not as a message.
                system_prompt = msg["text"]
            elif role == "user":
                contents.append(
                    types.Content(role="user", parts=[types.Part(text=msg["text"])])
                )
            elif role == "assistant":
                parts = []
                if msg.get("text"):
                    parts.append(types.Part(text=msg["text"]))
                for call in msg.get("tool_calls", []):
                    parts.append(
                        types.Part(
                            function_call=types.FunctionCall(
                                name=call["name"], args=call["args"]
                            )
                        )
                    )
                contents.append(types.Content(role="model", parts=parts))
            elif role == "tool":
                part = types.Part(
                    function_response=types.FunctionResponse(
                        name=msg["name"], response={"result": msg["result"]}
                    )
                )
                # Gemini expects tool results inside a "user"-role content. If the
                # previous content already carries tool results (the model called
                # several tools in one turn), append to it instead of starting a new one.
                last = contents[-1] if contents else None
                if last is not None and last.role == "user" and last.parts[0].function_response:
                    last.parts.append(part)
                else:
                    contents.append(types.Content(role="user", parts=[part]))
        return system_prompt, contents

    # ---- the actual API call, with retries ----------------------------------

    def _call_with_retry(self, contents, config, attempts=3):
        for attempt in range(attempts):
            try:
                return self.client.models.generate_content(
                    model=self.model, contents=contents, config=config
                )
            except errors.APIError as e:
                # A DAILY quota that's used up won't recover in seconds — fail
                # fast so callers can stop cleanly instead of burning minutes.
                if e.code == 429 and "PerDay" in str(e):
                    raise QuotaExhausted(str(e)) from e
                # Per-minute rate limit (429) or a transient server error (5xx):
                # wait a moment and try again instead of crashing the conversation.
                retriable = e.code in (429, 500, 503)
                if retriable and attempt < attempts - 1:
                    wait = 15 if e.code == 429 else 2 * (attempt + 1)
                    print(f"  [llm] API error {e.code}, retrying in {wait}s...")
                    time.sleep(wait)
                    continue
                raise

    # ---- Gemini response -> neutral format ----------------------------------

    def _normalize(self, response) -> dict:
        out = {"text": None, "tool_calls": []}
        if not response.candidates:
            return out
        content = response.candidates[0].content
        if content is None or not content.parts:
            return out
        for part in content.parts:
            if part.text:
                out["text"] = (out["text"] or "") + part.text
            if part.function_call:
                out["tool_calls"].append(
                    {
                        "name": part.function_call.name,
                        "args": dict(part.function_call.args or {}),
                    }
                )
        return out


class GeminiLive:
    """Stage 2.5: a streaming voice session over the Gemini Live API.

    Turn-based chat (GeminiLLM.send) waits for you to finish typing; the Live
    API instead holds an open websocket — you stream microphone audio UP while
    agent speech streams DOWN, and the server detects when you start/stop
    talking (so you can interrupt it mid-sentence, like a real phone call).

    Same isolation rule as GeminiLLM: all Gemini wire-format details stay in
    this class. Callers see only simple normalized event dicts from events():

        {"type": "audio", "data": b"..."}       24 kHz PCM — play it
        {"type": "user_text", "text": "..."}    transcript fragment of the caller
        {"type": "agent_text", "text": "..."}   transcript fragment of the agent
        {"type": "tool_calls", "calls": [...]}  run them, then send_tool_results()
        {"type": "interrupted"}                 caller barged in — stop playback NOW
        {"type": "turn_complete"}               agent finished its turn
    """

    # Mic audio must be 16 kHz mono 16-bit PCM; the agent's voice comes back at 24 kHz.
    INPUT_MIME = "audio/pcm;rate=16000"

    def __init__(self, model: str = LIVE_MODEL):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Copy .env.example to .env and add your "
                "key (see SETUP.md for how to get one)."
            )
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self._cm = None
        self._session = None

    async def connect(self, system_prompt: str, tools: list[dict] | None = None):
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=system_prompt,
            tools=_tools_to_gemini(tools),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore")
                )
            ),
            # Ask the server to also send TEXT transcripts of both sides, so we
            # can log the conversation exactly like the text modes do.
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
        )
        self._cm = self.client.aio.live.connect(model=self.model, config=config)
        self._session = await self._cm.__aenter__()

    async def close(self):
        if self._cm is not None:
            await self._cm.__aexit__(None, None, None)
            self._cm = self._session = None

    async def send_audio(self, pcm16_chunk: bytes):
        await self._session.send_realtime_input(
            audio=types.Blob(data=pcm16_chunk, mime_type=self.INPUT_MIME)
        )

    async def send_text(self, text: str):
        """Type instead of talk — useful for testing without a microphone.

        Uses send_realtime_input (not send_client_content): native-audio models
        generate replies from the REALTIME stream; client_content text is only
        added as silent context and never triggers a spoken answer.
        """
        await self._session.send_realtime_input(text=text)

    async def send_tool_results(self, results: list[dict]):
        """results: [{"id": ..., "name": ..., "result": {...}}, ...]"""
        await self._session.send_tool_response(
            function_responses=[
                types.FunctionResponse(
                    id=r["id"], name=r["name"], response={"result": r["result"]}
                )
                for r in results
            ]
        )

    async def events(self):
        """Yield normalized events until the session ends.

        receive() gives one agent turn per iteration, so we loop it forever;
        the websocket closing (session time limit, network drop) ends the loop.
        """
        while True:
            async for msg in self._session.receive():
                sc = msg.server_content
                if sc is not None:
                    # Pull audio out of the model turn ourselves (msg.data does the
                    # same but logs warnings about the text/thought parts we skip).
                    if sc.model_turn:
                        for part in sc.model_turn.parts or []:
                            if part.inline_data and part.inline_data.data:
                                yield {"type": "audio", "data": part.inline_data.data}
                    if sc.interrupted:
                        yield {"type": "interrupted"}
                    if sc.input_transcription and sc.input_transcription.text:
                        yield {"type": "user_text", "text": sc.input_transcription.text}
                    if sc.output_transcription and sc.output_transcription.text:
                        yield {"type": "agent_text", "text": sc.output_transcription.text}
                    if sc.turn_complete:
                        yield {"type": "turn_complete"}
                if msg.tool_call:
                    yield {
                        "type": "tool_calls",
                        "calls": [
                            {"id": fc.id, "name": fc.name, "args": dict(fc.args or {})}
                            for fc in msg.tool_call.function_calls
                        ],
                    }
