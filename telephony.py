"""telephony.py — real phone calls via Twilio. ALL Twilio-specific code lives here.

The pipeline (same shape as live_main.py, with a phone line instead of a mic):

    caller's phone ──► Twilio ──► POST /twilio/voice   (we answer with TwiML)
                          │
                          └──► wss /twilio/stream      (bidirectional audio)
                                     │ 8 kHz mulaw frames
                              TwilioBridge  ◄── converts audio both ways
                                     │ 16 kHz PCM up / 24 kHz PCM down
                              GeminiLive session (llm.py) + ReceptionistAgent tools

Works the moment these are set in .env (see SETUP.md):
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN   from the Twilio console
    TWILIO_NUMBER                           the number you bought (+1...)
    PUBLIC_BASE_URL                         where Twilio can reach this server
                                            (an ngrok https URL, or your host)

Multi-tenant routing: each client YAML may set `twilio_number: "+1..."` —
inbound calls to that number reach that business. Calls to an unmapped number
go to DEFAULT_CLIENT (env) or demo_clinic.

Concurrency: every call is one independent websocket + one GeminiLive session
inside FastAPI's event loop — no shared mutable state between calls, so many
calls run in parallel. The practical ceiling is your Gemini tier's concurrent
Live sessions (free: 3, paid tier 1: ~50), not this code.
"""

import asyncio
import audioop
import base64
import datetime as dt
import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

import billing
import storage
from agent import TOOL_SCHEMAS, ReceptionistAgent

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent


# ---- configuration ----------------------------------------------------------------

def twilio_config() -> dict:
    return {
        "sid": os.getenv("TWILIO_ACCOUNT_SID", ""),
        "token": os.getenv("TWILIO_AUTH_TOKEN", ""),
        "number": os.getenv("TWILIO_NUMBER", ""),
        "public_url": os.getenv("PUBLIC_BASE_URL", "").rstrip("/"),
    }


def is_configured() -> bool:
    cfg = twilio_config()
    return bool(cfg["sid"] and cfg["token"] and cfg["public_url"])


def resolve_client(to_number: str, explicit: str | None = None) -> str:
    """Which business does this call belong to?

    Priority: explicit ?client_id= (outbound calls) -> a client YAML whose
    twilio_number matches the dialed number -> DEFAULT_CLIENT -> demo_clinic.
    """
    if explicit:
        return explicit
    if to_number:
        import yaml
        for path in (BASE_DIR / "clients").glob("*.yaml"):
            with open(path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            if str(cfg.get("twilio_number", "")).strip() == to_number.strip():
                return path.stem
    return os.getenv("DEFAULT_CLIENT", "demo_clinic")


# ---- audio conversion (Twilio 8 kHz mulaw <-> Gemini PCM) ---------------------------

class AudioConverter:
    """Stateful resampler for one call. Twilio speaks 8 kHz mulaw; Gemini
    listens at 16 kHz PCM and answers at 24 kHz PCM. ratecv keeps a little
    filter state between chunks, so each call gets its own converter."""

    def __init__(self):
        self._up_state = None    # 8k -> 16k (caller's voice going up to Gemini)
        self._down_state = None  # 24k -> 8k (agent's voice going down the line)

    def twilio_to_gemini(self, mulaw_8k: bytes) -> bytes:
        pcm_8k = audioop.ulaw2lin(mulaw_8k, 2)
        pcm_16k, self._up_state = audioop.ratecv(pcm_8k, 2, 1, 8000, 16000, self._up_state)
        return pcm_16k

    def gemini_to_twilio(self, pcm_24k: bytes) -> bytes:
        pcm_8k, self._down_state = audioop.ratecv(pcm_24k, 2, 1, 24000, 8000, self._down_state)
        return audioop.lin2ulaw(pcm_8k, 2)


# ---- the bridge: one instance per live phone call -----------------------------------

class TwilioBridge:
    """Translates between Twilio's websocket protocol and GeminiLive events.

    Deliberately takes plain callables (send_json) instead of the websocket
    itself, so tests can drive it with fakes — same philosophy as FakeLLM.
    """

    def __init__(self, agent: ReceptionistAgent, live, send_json, caller: str = ""):
        self.agent = agent
        self.live = live
        self.send_json = send_json
        self.caller = caller
        self.converter = AudioConverter()
        self.stream_sid = None
        self.started = dt.datetime.now()
        self._user_line = ""
        self._agent_line = ""

    async def handle_twilio(self, msg: dict) -> bool:
        """One message from Twilio. Returns False when the call has ended."""
        event = msg.get("event")
        if event == "start":
            self.stream_sid = msg["start"]["streamSid"]
            # The receptionist speaks first on a phone call.
            await self.live.send_text("(the call has just connected — greet the caller briefly)")
        elif event == "media":
            mulaw = base64.b64decode(msg["media"]["payload"])
            await self.live.send_audio(self.converter.twilio_to_gemini(mulaw))
        elif event == "stop":
            return False
        return True  # "connected", "mark", unknown events: keep going

    async def pump_gemini(self):
        """Forward everything Gemini produces back down the phone line."""
        async for event in self.live.events():
            kind = event["type"]
            if kind == "audio":
                payload = base64.b64encode(
                    self.converter.gemini_to_twilio(event["data"])
                ).decode("ascii")
                await self.send_json(
                    {"event": "media", "streamSid": self.stream_sid,
                     "media": {"payload": payload}}
                )
            elif kind == "interrupted":
                # Caller barged in: tell Twilio to drop buffered agent audio NOW.
                await self.send_json({"event": "clear", "streamSid": self.stream_sid})
            elif kind == "tool_calls":
                results = []
                for call in event["calls"]:
                    try:
                        result = self.agent._execute_tool(call["name"], call["args"])
                    except Exception as e:
                        result = {"error": f"{type(e).__name__}: {e}"}
                    results.append({"id": call["id"], "name": call["name"], "result": result})
                await self.live.send_tool_results(results)
            elif kind == "user_text":
                self._user_line += event["text"]
            elif kind == "agent_text":
                self._agent_line += event["text"]
            elif kind == "turn_complete":
                self._flush_turn()

    def _flush_turn(self):
        if self._user_line.strip():
            self.agent.history.append({"role": "user", "text": self._user_line.strip()})
        if self._agent_line.strip():
            self.agent.history.append({"role": "assistant", "text": self._agent_line.strip()})
        self._user_line = self._agent_line = ""

    def finish(self):
        """Call ended: flush any half-turn and log it like every other channel."""
        self._flush_turn()
        if self.caller and self.agent.history:
            self.agent.history.insert(0, {"role": "user", "text": f"[caller id: {self.caller}]"})
        storage.log_call_from_agent(self.agent, "phone", self.started)


# ---- HTTP: the webhook Twilio hits when a call starts -------------------------------

def _validate_signature(request: Request, form: dict) -> bool:
    """Reject webhook calls that aren't really from Twilio (when configured)."""
    token = twilio_config()["token"]
    if not token:
        return True  # not configured yet — local testing
    from twilio.request_validator import RequestValidator

    signature = request.headers.get("X-Twilio-Signature", "")
    url = str(request.url).replace("http://", "https://", 1)
    return RequestValidator(token).validate(url, form, signature)


@router.post("/twilio/voice")
async def twilio_voice(request: Request, client_id: str | None = None):
    form = dict((await request.form()).items())
    if not _validate_signature(request, form):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")
    client = resolve_client(form.get("To", ""), client_id)
    caller = form.get("From", "")
    if not billing.client_active(client):
        # Unpaid/expired business: apologize to the caller instead of answering.
        return Response(content=(
            '<?xml version="1.0" encoding="UTF-8"?><Response>'
            "<Say>Sorry, this number is temporarily unavailable. "
            "Please try again later.</Say></Response>"
        ), media_type="application/xml")
    public = twilio_config()["public_url"]
    ws_url = public.replace("https://", "wss://").replace("http://", "ws://") + "/twilio/stream"
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="{ws_url}">
      <Parameter name="client_id" value="{client}"/>
      <Parameter name="caller" value="{caller}"/>
    </Stream>
  </Connect>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


# ---- WebSocket: the live audio of one phone call -------------------------------------

@router.websocket("/twilio/stream")
async def twilio_stream(ws: WebSocket):
    await ws.accept()
    from llm import GeminiLive  # imported here so tests can fake it easily

    bridge = None
    live = None
    try:
        # Twilio sends "connected" then "start" (which carries our parameters).
        start_msg = None
        while start_msg is None:
            msg = json.loads(await ws.receive_text())
            if msg.get("event") == "start":
                start_msg = msg
        params = start_msg["start"].get("customParameters", {})
        client_id = params.get("client_id", os.getenv("DEFAULT_CLIENT", "demo_clinic"))
        caller = params.get("caller", "")

        agent = ReceptionistAgent(client_id)
        if caller:
            agent.system_prompt += (
                f"\n\nThis is a PHONE CALL. The caller's number from caller ID is {caller} "
                "— when taking a booking or lead you may offer to use it, but always "
                "confirm it with the caller first."
            )
        live = GeminiLive()
        await live.connect(agent.system_prompt, TOOL_SCHEMAS)
        bridge = TwilioBridge(agent, live, ws.send_json, caller=caller)
        await bridge.handle_twilio(start_msg)

        async def read_twilio():
            while True:
                msg = json.loads(await ws.receive_text())
                if not await bridge.handle_twilio(msg):
                    return

        pump = asyncio.create_task(bridge.pump_gemini())
        try:
            await read_twilio()
        finally:
            pump.cancel()
    except WebSocketDisconnect:
        pass
    finally:
        if live is not None:
            try:
                await live.close()
            except Exception:
                pass
        if bridge is not None:
            bridge.finish()


# ---- outbound calls (started from the admin console) ---------------------------------

def start_outbound_call(client_id: str, to_number: str) -> str:
    """Ring a customer; when they pick up, the agent takes the call.
    Returns the Twilio call SID."""
    cfg = twilio_config()
    if not is_configured():
        raise RuntimeError(
            "Twilio is not configured yet. Set TWILIO_ACCOUNT_SID, "
            "TWILIO_AUTH_TOKEN, TWILIO_NUMBER and PUBLIC_BASE_URL in .env "
            "(see SETUP.md, Part 3)."
        )
    import yaml
    client_yaml = BASE_DIR / "clients" / f"{client_id}.yaml"
    from_number = cfg["number"]
    if client_yaml.exists():
        with open(client_yaml, encoding="utf-8") as f:
            from_number = yaml.safe_load(f).get("twilio_number") or cfg["number"]
    if not from_number:
        raise RuntimeError("No TWILIO_NUMBER in .env and no twilio_number in the client YAML.")

    from twilio.rest import Client

    call = Client(cfg["sid"], cfg["token"]).calls.create(
        to=to_number,
        from_=from_number,
        url=f"{cfg['public_url']}/twilio/voice?client_id={client_id}",
        method="POST",
    )
    return call.sid


def set_voice_webhook(public_url: str) -> str:
    """Point TWILIO_NUMBER's incoming-call webhook at this server via the
    Twilio API — no clicking around the Twilio console. Returns the number."""
    cfg = twilio_config()
    if not (cfg["sid"] and cfg["token"] and cfg["number"]):
        raise RuntimeError("Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_NUMBER in .env first.")

    from twilio.rest import Client

    numbers = Client(cfg["sid"], cfg["token"]).incoming_phone_numbers.list(
        phone_number=cfg["number"]
    )
    if not numbers:
        raise RuntimeError(f"{cfg['number']} was not found in this Twilio account.")
    numbers[0].update(voice_url=f"{public_url}/twilio/voice", voice_method="POST")
    return numbers[0].phone_number
