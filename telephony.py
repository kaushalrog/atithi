"""telephony.py — real phone calls via Twilio. ALL Twilio-specific code lives here.

The pipeline (same shape as live_main.py, with a phone line instead of a mic),
with every gate a call must pass BEFORE we spend money on a Gemini session:

  Twilio ──POST /twilio/voice──► [ENABLE_LIVE_CALLS?]──no──► 503
                                     │yes
                                 [Twilio auth token set + X-Twilio-Signature valid?]──no──► 503/403
                                     │yes
                                 [business active? under MAX_CONCURRENT_CALLS?]──no──► <Say> sorry
                                     │yes
                                 TwiML <Stream> + signed one-time ticket (call_sid, client_id, caller, exp)
  Twilio ──WSS /twilio/stream──► [ENABLE_LIVE_CALLS?]──no──► close 1008
                                     │yes
                                 [x-twilio-signature on the upgrade valid?]──no──► close 1008
                                     │yes  accept, wait for Twilio's "start" message
                                 [ticket: HMAC ok · not expired · callSid matches · never used]──no──► close 1008
                                     │yes
                                 [business exists & active · a call slot is free]──no──► close 1008
                                     │yes — only now:
                                 ReceptionistAgent + GeminiLive ◄─► TwilioBridge
                                     (8 kHz mulaw ⇄ 16/24 kHz PCM)  ──finally──► free slot, log call

WHY the ticket (audit H1): the websocket used to accept anyone and trust the
business id sent in the "start" message, so a stranger could open paid Gemini
sessions against any business — even one whose plan had expired. The ticket is
minted only after Twilio's signed webhook, signed with a key that exists only
in this process's memory, valid for 2 minutes, bound to one call, usable once.
Note: a restart invalidates tickets in flight, and two server processes would
not share the key — run ONE worker (see docs/SAFE_TESTING.md).

Live calls are OFF until ENABLE_LIVE_CALLS=true is set in .env, on top of:
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN   from the Twilio console
    TWILIO_NUMBER                           the number you bought (+1...)
    PUBLIC_BASE_URL                         where Twilio can reach this server
                                            (an ngrok https URL, or your host)
    MAX_CONCURRENT_CALLS                    optional, default 3 (Gemini free tier)

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
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape, quoteattr

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from starlette.websockets import WebSocketState

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


def live_calls_enabled() -> bool:
    """The master switch. Off unless .env says ENABLE_LIVE_CALLS=true."""
    return os.getenv("ENABLE_LIVE_CALLS", "").strip().lower() in ("1", "true", "yes")


def max_concurrent_calls() -> int:
    try:
        return max(0, int(os.getenv("MAX_CONCURRENT_CALLS", "3")))
    except ValueError:
        return 3


def stream_url() -> str:
    """The exact wss:// URL we hand Twilio in TwiML (and verify signatures on)."""
    public = twilio_config()["public_url"]
    return public.replace("https://", "wss://").replace("http://", "ws://") + "/twilio/stream"


# ---- one-time stream tickets ---------------------------------------------------------
#
# The key lives only in this process's memory (a restart invalidates every
# ticket in flight, which the 2-minute lifetime makes harmless). Nothing in
# .env can be leaked to forge one.

_STREAM_SECRET = secrets.token_bytes(32)
STREAM_TICKET_TTL_S = 120
# Twilio sends "connected" then "start"; a few spare messages is generous.
MAX_PRE_START_MESSAGES = 5
_used_tickets: dict[str, float] = {}   # call_sid -> ticket expiry (replay guard)
_active_calls = 0                      # event-loop only, so a plain int is safe
# Tickets handed to Twilio but not yet used: each holds a call slot until its
# stream arrives or it expires. Without this, a burst of calls all passed the
# webhook's limit check and the extras were dropped silently at the stream.
_pending_tickets: dict[str, float] = {}   # call_sid -> reservation expiry
# A reservation is short: Twilio opens the stream within about a second of our
# TwiML, so a stream that never arrives (caller hung up, rejected before its
# 'start' message) gives its slot back after 30 s, not the ticket's 2 minutes.
PENDING_SLOT_S = 30
# An outbound call holds its slot from dialling until answered (Twilio rings
# for up to ~30 s by default), so inbound calls can't take the line meanwhile.
OUTBOUND_RING_S = 60
# The table is also touched from a worker thread (outbound calls run in
# FastAPI's thread pool), so every access holds this lock.
_slots_lock = threading.Lock()
# Accepted streams still waiting for 'start'. The handshake signature is the
# same on every call (it can be replayed), so cap how many can wait at once.
MAX_PRE_START_SOCKETS = 20
_pre_start_sockets = 0


def _reserve_slot(call_sid: str, expires_at: float):
    with _slots_lock:
        _pending_tickets[call_sid] = expires_at


def _release_slot(call_sid: str):
    with _slots_lock:
        _pending_tickets.pop(call_sid, None)


def _calls_in_flight() -> int:
    """Calls connected plus calls promised a slot (unexpired reservations)."""
    now = time.time()
    with _slots_lock:
        for sid in [s for s, e in _pending_tickets.items() if e < now]:
            _pending_tickets.pop(sid, None)
        return _active_calls + len(_pending_tickets)


def _ticket_signature(call_sid: str, client_id: str, caller: str, exp: str) -> str:
    # json.dumps of a list, not "a|b|c": a "|" inside a field can't make two
    # different tickets sign the same bytes.
    msg = json.dumps([call_sid, client_id, caller, exp]).encode()
    return hmac.new(_STREAM_SECRET, msg, hashlib.sha256).hexdigest()


def mint_stream_ticket(call_sid: str, client_id: str, caller: str,
                       now: float | None = None) -> dict:
    exp = str(int((now or time.time()) + STREAM_TICKET_TTL_S))
    return {"call_sid": call_sid, "client_id": client_id, "caller": caller,
            "exp": exp, "ticket": _ticket_signature(call_sid, client_id, caller, exp)}


def check_stream_ticket(params: dict, start_call_sid: str,
                        now: float | None = None) -> str | None:
    """None if the ticket is good (and consumes it); otherwise why not."""
    now = now or time.time()
    fields = [str(params.get(k, "")) for k in ("call_sid", "client_id", "caller", "exp")]
    call_sid, client_id, _caller, exp = fields
    ticket = str(params.get("ticket", ""))
    if not (ticket and call_sid and client_id and exp):
        return "missing ticket"
    # Compare bytes: compare_digest raises on non-ASCII str, and these values
    # come from the (unsigned) start message.
    if not hmac.compare_digest(ticket.encode(), _ticket_signature(*fields).encode()):
        return "bad ticket signature"
    if not exp.isdigit() or int(exp) < now:
        return "ticket expired"
    if not hmac.compare_digest(call_sid.encode(), (start_call_sid or "").encode()):
        return "ticket is for a different call"
    for sid in [s for s, e in _used_tickets.items() if e < now]:
        del _used_tickets[sid]                          # forget expired entries
    if call_sid in _used_tickets:
        return "ticket already used"
    _used_tickets[call_sid] = float(exp)
    return None


def _signature_ok(url: str, params: dict, signature: str) -> bool:
    """Twilio's own check (HMAC-SHA1 over URL + params with the auth token)."""
    token = twilio_config()["token"]
    if not token or not signature:
        return False
    from twilio.request_validator import RequestValidator

    return RequestValidator(token).validate(url, params, signature)


def resolve_client(to_number: str, explicit: str | None = None) -> str:
    """Which business does this call belong to?

    Priority: explicit ?client_id= (outbound calls) -> a client YAML whose
    twilio_number matches the dialed number -> DEFAULT_CLIENT -> demo_clinic.

    The number lookup used to re-read and re-parse every client YAML while the
    caller waited; storage keeps the parsed configs cached, so it is now a
    dictionary walk over already-loaded data.
    """
    if explicit:
        return explicit
    if to_number:
        owner = storage.client_for_number(to_number)
        if owner:
            return owner
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
    """Is this webhook really from Twilio? Fails closed: no auth token, no call.

    (It used to return True when the token was missing — "local testing" —
    which meant an unconfigured server answered anyone who POSTed.)
    """
    url = str(request.url).replace("http://", "https://", 1)
    return _signature_ok(url, form, request.headers.get("X-Twilio-Signature", ""))


def _say(text: str) -> Response:
    return Response(content=(
        '<?xml version="1.0" encoding="UTF-8"?><Response>'
        f"<Say>{escape(text)}</Say></Response>"
    ), media_type="application/xml")


@router.post("/twilio/voice")
async def twilio_voice(request: Request, client_id: str | None = None):
    if not live_calls_enabled():
        raise HTTPException(status_code=503, detail="Live calls are disabled (ENABLE_LIVE_CALLS)")
    if not (twilio_config()["token"] and twilio_config()["public_url"]):
        raise HTTPException(status_code=503, detail="Twilio is not configured")
    form = dict((await request.form()).items())
    if not _validate_signature(request, form):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")
    client = resolve_client(form.get("To", ""), client_id)
    # A call the business placed (from /admin) is answered by the customer:
    # their number is "To", and the lines were already checked when dialling,
    # so they must never hear "all our lines are busy" on picking up.
    outbound = form.get("Direction", "").startswith("outbound")
    caller = form.get("To", "") if outbound else form.get("From", "")
    if not billing.client_active(client):          # also False for an unknown business
        # Unpaid/expired business: apologize to the caller instead of answering.
        return _say("Sorry, this number is temporarily unavailable. Please try again later.")
    if not outbound and _calls_in_flight() >= max_concurrent_calls():
        return _say("Sorry, all our lines are busy right now. Please call again in a few minutes.")
    ticket = mint_stream_ticket(form.get("CallSid", ""), client, caller)
    _reserve_slot(ticket["call_sid"], time.time() + PENDING_SLOT_S)
    # Every attribute value is XML-escaped: From and client_id arrive from
    # outside, and an f-string used to let them inject TwiML (audit L2).
    params = "\n".join(
        f"      <Parameter name={quoteattr(k)} value={quoteattr(v)}/>"
        for k, v in ticket.items()
    )
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url={quoteattr(stream_url())}>
{params}
    </Stream>
  </Connect>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


# ---- WebSocket: the live audio of one phone call -------------------------------------

PRE_START_TIMEOUT_S = 10


async def _read_start(ws: WebSocket) -> dict | None:
    for _ in range(MAX_PRE_START_MESSAGES):
        msg = json.loads(await ws.receive_text())
        if not isinstance(msg, dict):           # Twilio frames are always objects
            raise ValueError("frame is not a JSON object")
        if msg.get("event") == "start":
            return msg
    return None


async def _reject(ws: WebSocket, reason: str):
    print(f"  [phone] stream rejected: {reason}")
    await ws.close(code=1008)   # 1008 = policy violation


@router.websocket("/twilio/stream")
async def twilio_stream(ws: WebSocket):
    global _active_calls, _pre_start_sockets
    # Gates 1-2 run before the websocket is even accepted.
    if not live_calls_enabled():
        return await _reject(ws, "live calls disabled")
    # Twilio's docs require validating this header on Media Streams (lowercase
    # on websockets) but don't publish the signed parameter set for the
    # upgrade; we verify the exact URL from our TwiML with no params. This is
    # UNVERIFIED against real Twilio traffic until the first test call — see
    # docs/SAFE_TESTING.md. Fail closed either way.
    if not _signature_ok(stream_url(), {}, ws.headers.get("x-twilio-signature", "")):
        return await _reject(ws, "bad or missing x-twilio-signature")
    if _pre_start_sockets >= MAX_PRE_START_SOCKETS:
        return await _reject(ws, "too many streams waiting to start")
    await ws.accept()
    from llm import GeminiLive  # imported here so tests can fake it easily

    bridge = None
    live = None
    holds_slot = False
    try:
        # Twilio sends "connected" then "start" (which carries our ticket).
        # Bounded in messages AND time: nothing has been checked yet, so an
        # idle or garbage-sending socket must not be able to sit here forever.
        _pre_start_sockets += 1
        try:
            start_msg = await asyncio.wait_for(_read_start(ws), timeout=PRE_START_TIMEOUT_S)
        except TimeoutError:
            return await _reject(ws, "no start message in time")
        except (ValueError, TypeError, AttributeError, KeyError):
            # KeyError: starlette's receive_text() on a binary frame.
            return await _reject(ws, "malformed message before start")
        finally:
            _pre_start_sockets -= 1
        if start_msg is None:
            return await _reject(ws, "no start message")
        start = start_msg.get("start")
        if not isinstance(start, dict):
            return await _reject(ws, "malformed start message")
        params = start.get("customParameters") or {}
        if not isinstance(params, dict):
            return await _reject(ws, "malformed start message")
        problem = check_stream_ticket(params, str(start.get("callSid", "")))
        if problem not in ("missing ticket", "bad ticket signature"):
            # A genuine ticket (signature checked): its reserved slot is now
            # either used below or given up. Unsigned input can't free slots.
            _release_slot(str(params.get("call_sid", "")))
        if problem:
            return await _reject(ws, problem)
        # Identity comes from the signed ticket, never from unsigned input.
        client_id, caller = params["client_id"], params.get("caller", "")
        if storage.read_client_config(client_id) is None:
            return await _reject(ws, f"unknown business {client_id!r}")
        if not billing.client_active(client_id):    # the plan may have lapsed since the webhook
            return await _reject(ws, f"plan inactive for {client_id!r}")
        if _calls_in_flight() >= max_concurrent_calls():
            return await _reject(ws, "concurrent call limit reached")
        _active_calls += 1
        holds_slot = True

        # Every gate passed — only now do we spend resources on the call.
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
        if holds_slot:
            _active_calls -= 1
        if live is not None:
            try:
                await live.close()
            except Exception:
                pass
        if bridge is not None:
            bridge.finish()
        # Hang up our side too: a finished or failed call must never leave a
        # half-open socket (Twilio closes after "stop"; anything else may not).
        if ws.client_state == WebSocketState.CONNECTED:
            try:
                await ws.close()
            except RuntimeError:
                pass


# ---- outbound calls (started from the admin console) ---------------------------------

def start_outbound_call(client_id: str, to_number: str) -> str:
    """Ring a customer; when they pick up, the agent takes the call.
    Returns the Twilio call SID."""
    cfg = twilio_config()
    if not live_calls_enabled():
        raise RuntimeError(
            "Live calls are disabled. Set ENABLE_LIVE_CALLS=true in .env only after "
            "the checks in docs/SAFE_TESTING.md pass."
        )
    if not is_configured():
        raise RuntimeError(
            "Twilio is not configured yet. Set TWILIO_ACCOUNT_SID, "
            "TWILIO_AUTH_TOKEN, TWILIO_NUMBER and PUBLIC_BASE_URL in .env "
            "(see SETUP.md, Part 3)."
        )
    # Check BEFORE dialling: once the customer picks up, it's too late to find
    # out the business can't serve them.
    if not billing.client_active(client_id):
        raise RuntimeError(f"'{client_id}' has no active plan — not calling.")
    if _calls_in_flight() >= max_concurrent_calls():
        raise RuntimeError("All call slots are in use — try again in a few minutes.")
    client_cfg = storage.read_client_config(client_id) or {}
    from_number = client_cfg.get("twilio_number") or cfg["number"]
    if not from_number:
        raise RuntimeError("No TWILIO_NUMBER in .env and no twilio_number in the client YAML.")

    from twilio.rest import Client

    call = Client(cfg["sid"], cfg["token"]).calls.create(
        to=to_number,
        from_=from_number,
        url=f"{cfg['public_url']}/twilio/voice?client_id={quote(client_id)}",
        method="POST",
    )
    _reserve_slot(call.sid, time.time() + OUTBOUND_RING_S)
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
