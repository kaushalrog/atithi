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
inside FastAPI's ONE event loop. That loop is shared by every live call, so
nothing that blocks (a tool hitting the database, building the agent,
saving the record) may run on it — a 300 ms booking there froze every other
caller's audio for 300 ms (docs/PERFORMANCE_AUDIT.md F2). Those run on the
call-I/O thread pool below instead. The practical ceiling is your Gemini
tier's concurrent Live sessions (free: 3, paid tier 1: ~50), not this code.
"""

import asyncio
import audioop
import base64
import concurrent.futures
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
import perf
import storage
from agent import TOOL_SCHEMAS, ReceptionistAgent, TurnRecorder

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent


# ---- configuration ----------------------------------------------------------------

TOOL_DRAIN_S = 15   # at hang-up, how long to wait for a booking still running
LIVE_CONNECT_TIMEOUT_S = 10   # opening the Gemini Live session; the caller hears silence meanwhile
# Twilio runs the TwiML after </Connect> once OUR side ends the stream — a
# dropped model session, a connect that failed. (A caller hanging up ends
# the call, so they never hear it.) Twilio documents this behaviour; it is
# UNVERIFIED on a real call until docs/SAFE_TESTING.md §5 is done.
APOLOGY = "Sorry, we're having trouble right now. Please call back in a few minutes."
HANDOFF_SPEAK_S = 4   # let "connecting you now" play before the line switches
HANDOFF_RING_S = 25   # how long the owner's phone rings before we give up
NO_ANSWER = "Sorry, nobody could take your call right now. The team will call you back soon."

_call_io_pool = None
_call_io_lock = threading.Lock()


def call_io_pool() -> concurrent.futures.ThreadPoolExecutor:
    """The threads that run phone calls' blocking work.

    Its own pool, not asyncio's default one: the default (min(32, CPUs + 4)
    threads — 5 on a 1-vCPU VM) is shared with everything else in the
    process, so a few slow tools could leave a hanging-up call waiting for
    a thread just to save its record. Two per call allows a tool and a
    record save at once."""
    global _call_io_pool
    with _call_io_lock:
        if _call_io_pool is None:
            _call_io_pool = concurrent.futures.ThreadPoolExecutor(
                max_workers=call_io_workers(), thread_name_prefix="call-io")
        return _call_io_pool


def call_io_workers() -> int:
    return max(8, 2 * max_concurrent_calls())


async def _off_loop(fn, *args):
    """Run blocking fn(*args) on the call-I/O pool; the loop keeps serving calls."""
    return await asyncio.wrap_future(call_io_pool().submit(fn, *args))

def twilio_config() -> dict:
    return {
        "sid": os.getenv("TWILIO_ACCOUNT_SID", ""),
        "token": os.getenv("TWILIO_AUTH_TOKEN", ""),
        "number": os.getenv("TWILIO_NUMBER", ""),
        "public_url": os.getenv("PUBLIC_BASE_URL", "").rstrip("/"),
    }


def sms_enabled() -> bool:
    """Texting customers is OFF unless ENABLE_SMS=true AND Twilio is set up.
    Off, notify.py records what it would have sent (a dry run) instead."""
    cfg = twilio_config()
    return (os.getenv("ENABLE_SMS", "").strip().lower() == "true"
            and bool(cfg["sid"] and cfg["token"] and cfg["number"]))


def send_sms(to: str, body: str) -> str:
    """Send one SMS from the business line; returns Twilio's message SID.
    Raises on any failure (notify.py logs it; the booking is never affected)."""
    from twilio.rest import Client
    cfg = twilio_config()
    return Client(cfg["sid"], cfg["token"]).messages.create(
        to=to, from_=cfg["number"], body=body).sid


def is_configured() -> bool:
    cfg = twilio_config()
    return bool(cfg["sid"] and cfg["token"] and cfg["public_url"])


def live_calls_enabled() -> bool:
    """The master switch. Off unless .env says ENABLE_LIVE_CALLS=true."""
    return os.getenv("ENABLE_LIVE_CALLS", "").strip().lower() in ("1", "true", "yes")


def handoff_enabled() -> bool:
    """Live transfer to the owner's phone: OFF unless ENABLE_HANDOFF=true
    (on top of live calls). It rings a real person's phone."""
    return live_calls_enabled() and os.getenv("ENABLE_HANDOFF", "").strip().lower() == "true"


def callbacks_enabled() -> bool:
    """Ringing customers back (missed calls, busy lines): OFF unless
    ENABLE_CALLBACKS=true, on top of live calls and a configured Twilio."""
    return (live_calls_enabled() and is_configured()
            and os.getenv("ENABLE_CALLBACKS", "").strip().lower() == "true")


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


def _ticket_signature(call_sid: str, client_id: str, caller: str, exp: str,
                      purpose: str = "") -> str:
    # json.dumps of a list, not "a|b|c": a "|" inside a field can't make two
    # different tickets sign the same bytes. The purpose (e.g. "callback") is
    # signed too, so nobody can turn an ordinary call into something else.
    fields = [call_sid, client_id, caller, exp] + ([purpose] if purpose else [])
    msg = json.dumps(fields).encode()
    return hmac.new(_STREAM_SECRET, msg, hashlib.sha256).hexdigest()


def mint_stream_ticket(call_sid: str, client_id: str, caller: str,
                       now: float | None = None, purpose: str = "") -> dict:
    exp = str(int((now or time.time()) + STREAM_TICKET_TTL_S))
    ticket = {"call_sid": call_sid, "client_id": client_id, "caller": caller, "exp": exp,
              "ticket": _ticket_signature(call_sid, client_id, caller, exp, purpose)}
    if purpose:
        ticket["purpose"] = purpose
    return ticket


def check_stream_ticket(params: dict, start_call_sid: str,
                        now: float | None = None) -> str | None:
    """None if the ticket is good (and consumes it); otherwise why not."""
    now = now or time.time()
    fields = [str(params.get(k, "")) for k in ("call_sid", "client_id", "caller", "exp", "purpose")]
    call_sid, client_id, _caller, exp, _purpose = fields
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

    def __init__(self, agent: ReceptionistAgent, live, send_json, caller: str = "",
                 call_sid: str = "", purpose: str = ""):
        self.agent = agent
        self.purpose = purpose
        self._handoff_task = None
        self.live = live
        self.send_json = send_json
        self.caller = caller
        # Twilio's id for this call. Only letters and digits ever reach a file
        # name (real SIDs are "CA" + 32 hex characters).
        self.call_sid = "".join(ch for ch in call_sid if ch.isascii() and ch.isalnum())
        self.converter = AudioConverter()
        self.stream_sid = None
        self.started = dt.datetime.now()
        self.turn = TurnRecorder(agent)
        # Audio timing (perf_counter). The Live API detects the end of the
        # caller's speech itself, so "the caller finished" is approximated by
        # the last transcript fragment heard before the reply's first audio.
        self._tool_job = None      # the tool run in flight (a concurrent Future)
        self.late_save_done = threading.Event()   # set once a late tool's re-save ran
        self._greet_t = None       # when we asked for the greeting
        self._heard_t = None       # last caller transcript fragment
        self._reply_t0 = self._reply_last = None

    def _audio_out(self):
        now = time.perf_counter()
        if self._reply_t0 is None:
            self._reply_t0 = now
            pid = self.agent.perf_id
            if self._heard_t is not None:
                perf.record("call.first_audio", (now - self._heard_t) * 1000, call=pid)
            elif self._greet_t is not None:
                perf.record("call.greeting_audio", (now - self._greet_t) * 1000, call=pid)
            self._heard_t = self._greet_t = None
        self._reply_last = now

    def _reply_ended(self, outcome: str):
        if self._reply_t0 is not None:
            perf.record("call.reply_audio", (self._reply_last - self._reply_t0) * 1000,
                        call=self.agent.perf_id, outcome=outcome)
        self._reply_t0 = self._reply_last = None

    async def handle_twilio(self, msg: dict) -> bool:
        """One message from Twilio. Returns False when the call has ended."""
        event = msg.get("event")
        if event == "start":
            self.stream_sid = msg["start"]["streamSid"]
            # The receptionist speaks first on a phone call.
            self._greet_t = time.perf_counter()
            if self.purpose == "callback":
                await self.live.send_text(
                    "(you are calling this customer BACK: they gave the business a missed call. "
                    "Say you are calling from the business about their missed call, and ask how you can help)")
            else:
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
                self._audio_out()
                payload = base64.b64encode(
                    self.converter.gemini_to_twilio(event["data"])
                ).decode("ascii")
                await self.send_json(
                    {"event": "media", "streamSid": self.stream_sid,
                     "media": {"payload": payload}}
                )
            elif kind == "interrupted":
                # Caller barged in: tell Twilio to drop buffered agent audio NOW,
                # and end the turn so the cut-off reply is recorded before the
                # caller's next words.
                await self.send_json({"event": "clear", "streamSid": self.stream_sid})
                self._reply_ended("interrupted")
                self.turn.flush()
            elif kind == "tool_calls":
                # On a worker thread: the database (and anything slow behind
                # it) must never stall the other calls on this event loop.
                # Safe because this pump handles ONE event at a time — nothing
                # else touches this call's TurnRecorder until the tool is done.
                self._tool_job = call_io_pool().submit(self.turn.tool_calls, event["calls"])
                results = await asyncio.wrap_future(self._tool_job)
                await self.live.send_tool_results(results)
                if self.agent.handoff and self._handoff_task is None:
                    self._handoff_task = asyncio.create_task(self._transfer())
            elif kind == "user_text":
                self._heard_t = time.perf_counter()
                self.turn.user_text(event["text"])
            elif kind == "agent_text":
                self.turn.agent_text(event["text"])
            elif kind == "turn_complete":
                self._reply_ended("complete")
                self.turn.flush()

    async def _transfer(self):
        """Hand the live call to the owner's phone. The agent has just said
        "connecting you now"; give that a moment to play, then ask Twilio to
        replace this stream with a <Dial>. Twilio ends the stream, so the
        call is saved the normal way; the transfer is in it as an action."""
        await asyncio.sleep(HANDOFF_SPEAK_S)
        to = str(self.agent.config.get("handoff_phone", ""))
        try:
            # A lead first: if nobody picks up, the owner still sees who it was.
            await _off_loop(storage.save_lead, self.agent.client_id,
                            self.agent.handoff.get("name", ""), self.caller,
                            "Transferred to the team", "Call transferred: " + self.agent.handoff["reason"])
            await _off_loop(transfer_call, self.call_sid, to)
            perf.event("call.transferred")
        except Exception as e:
            perf.event("error.transfer")
            print(f"  [phone] transfer failed ({type(e).__name__}); the agent keeps the call")
            await self.live.send_text("(the transfer did not go through: apologise, and offer that "
                                      "the team will call them back on this number)")

    def finish(self):
        """Call ended: flush any half-turn and log it like every other channel.

        The caller's number is call metadata, not something the caller said:
        it used to be inserted as a customer turn, which inflated the turn
        count and shifted every turn after it (audit M2).

        Runs on a worker thread. If the caller hung up while a tool was
        running, wait for it (up to TOOL_DRAIN_S) so the record includes its
        result. If it is still running after that, save now and save again
        when it finishes: a booking that happened is never missing from the
        record. TurnRecorder's lock keeps the two threads from interleaving."""
        self.ended = dt.datetime.now()     # the hang-up, for both saves below
        job = self._tool_job
        late = False
        if job is not None and not job.done():
            try:
                job.result(timeout=TOOL_DRAIN_S)
            except concurrent.futures.TimeoutError:
                late = True
                perf.event("timeout.tool_at_hangup")
                print(f"  (call {self.call_sid or '?'}: a tool was still running after "
                      f"{TOOL_DRAIN_S}s at hang-up; saving now and again when it finishes)")
            except Exception:
                pass   # run_tool never raises; a cancelled job never ran
        self._save()
        if late:
            # Save once more when the tool finishes (on its worker thread):
            # same call id, so the record is rewritten, now with the result.
            # A booking that committed late must never be missing from it.
            job.add_done_callback(lambda _: self._save_late())

    def _save_late(self):
        try:
            self._save()
        except Exception as e:
            print(f"  (call {self.call_sid or '?'}: late re-save failed: {type(e).__name__}: {e})")
        finally:
            self.late_save_done.set()

    def _save(self):
        self.turn.flush()
        # Two calls can start in the same second, so the call id carries the
        # Twilio SID; without one it would overwrite the other call's record.
        call_id = self.started.strftime("%Y%m%d_%H%M%S_phone")
        if self.call_sid:
            call_id += f"_{self.call_sid}"
        storage.log_call_from_agent(self.agent, "phone", self.started,
                                    call_id=call_id, caller=self.caller,
                                    ended=getattr(self, "ended", None))


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


def _route_and_check(to_number: str, explicit: str | None) -> tuple[str, bool, dict]:
    client = resolve_client(to_number, explicit)
    cfg = storage.read_client_config(client) or {}
    line = {"missed_call_mode": bool(cfg.get("missed_call_mode")),
            "callback_when_busy": cfg.get("callback_when_busy", True) is not False}
    return client, billing.client_active(client), line


def _reject_busy() -> Response:
    """Decline the call with a busy tone. In India a "missed call" is a
    request to be called back, and a rejected call costs the caller nothing."""
    return Response(content='<?xml version="1.0" encoding="UTF-8"?>'
                            '<Response><Reject reason="busy"/></Response>',
                    media_type="application/xml")


def _business_problem(client_id: str) -> str | None:
    if storage.read_client_config(client_id) is None:
        return f"unknown business {client_id!r}"
    if not billing.client_active(client_id):       # the plan may have lapsed since the webhook
        return f"plan inactive for {client_id!r}"
    return None


@router.post("/twilio/voice")
async def twilio_voice(request: Request, client_id: str | None = None):
    if not live_calls_enabled():
        raise HTTPException(status_code=503, detail="Live calls are disabled (ENABLE_LIVE_CALLS)")
    if not (twilio_config()["token"] and twilio_config()["public_url"]):
        raise HTTPException(status_code=503, detail="Twilio is not configured")
    form = dict((await request.form()).items())
    if not _validate_signature(request, form):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")
    # Routing and the plan check read client files: off the loop, because
    # live calls share it (cached reads are fast, but a cold one is not).
    client, active, line = await _off_loop(_route_and_check, form.get("To", ""), client_id)
    # A call the business placed (from /admin) is answered by the customer:
    # their number is "To", and the lines were already checked when dialling,
    # so they must never hear "all our lines are busy" on picking up.
    outbound = form.get("Direction", "").startswith("outbound")
    caller = form.get("To", "") if outbound else form.get("From", "")
    if not active:                                 # also False for an unknown business
        # Unpaid/expired business: apologize to the caller instead of answering.
        return _say("Sorry, this number is temporarily unavailable. Please try again later.")
    # Missed-call mode and busy-line callbacks only when ringing customers
    # back is switched on: never reject a caller we won't call back.
    can_call_back = not outbound and bool(caller) and callbacks_enabled()
    if can_call_back and line["missed_call_mode"]:
        # Reject only if a callback is really owed; a caller we called back
        # recently, or one past today's cap, is answered by the agent instead.
        if await _off_loop(storage.queue_callback, client, caller, "missed call") in ("queued", "pending"):
            perf.event("call.missed_call")
            return _reject_busy()
    if not outbound and _calls_in_flight() >= max_concurrent_calls():
        if can_call_back and line["callback_when_busy"]:
            if await _off_loop(storage.queue_callback, client, caller, "lines busy") in ("queued", "pending"):
                return _say("Sorry, all our lines are busy right now. We'll call you back in a few minutes.")
        return _say("Sorry, all our lines are busy right now. Please call again in a few minutes.")
    purpose = "callback" if outbound and request.query_params.get("purpose") == "callback" else ""
    ticket = mint_stream_ticket(form.get("CallSid", ""), client, caller, purpose=purpose)
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
  <Say>{escape(APOLOGY)}</Say>
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
        # Check-and-take the line with no await in between: the ticket's
        # reserved slot was just given back, so an await here would let
        # another call take the line this caller was promised.
        if _calls_in_flight() >= max_concurrent_calls():
            return await _reject(ws, "concurrent call limit reached")
        _active_calls += 1
        holds_slot = True
        problem = await _off_loop(_business_problem, client_id)
        if problem:
            return await _reject(ws, problem)    # finally gives the line back

        # Every gate passed — only now do we spend resources on the call.
        agent = await _off_loop(ReceptionistAgent, client_id)
        agent.can_transfer = handoff_enabled() and bool(agent.config.get("handoff_phone"))
        if caller:
            agent.system_prompt += (
                f"\n\nThis is a PHONE CALL. The caller's number from caller ID is {caller} "
                "— when taking a booking or lead you may offer to use it, but always "
                "confirm it with the caller first."
            )
        perf.gauge("calls.active", _active_calls)
        perf.ensure_loop_monitor()
        live = GeminiLive()
        # Bounded: a handshake that hangs used to leave the caller in silence
        # (holding a line) for as long as the network let it.
        try:
            with perf.span("call.model_connect", call=agent.perf_id):
                await asyncio.wait_for(live.connect(agent.system_prompt, TOOL_SCHEMAS),
                                       timeout=LIVE_CONNECT_TIMEOUT_S)
        except Exception as e:
            kind = "timeout" if isinstance(e, TimeoutError) else "error"
            perf.event(f"{kind}.model_connect")
            print(f"  [phone] model session did not open ({type(e).__name__}); "
                  "ending the stream so the caller hears the apology")
            return
        bridge = TwilioBridge(agent, live, ws.send_json, caller=caller,
                              call_sid=str(params.get("call_sid", "")),
                              purpose=str(params.get("purpose", "")))
        await bridge.handle_twilio(start_msg)

        async def read_twilio():
            while True:
                msg = json.loads(await ws.receive_text())
                if not await bridge.handle_twilio(msg):
                    return

        # The call lasts until EITHER side ends. Waiting on the caller alone
        # meant a dropped model session left them on a silent line until they
        # gave up (bench: 5 of 5 calls). Now our side hangs up at once, and
        # Twilio plays the apology that follows </Connect>.
        reader = asyncio.create_task(read_twilio())
        pump = asyncio.create_task(bridge.pump_gemini())
        done = set()
        try:
            done, _ = await asyncio.wait({reader, pump}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            reader.cancel()
            pump.cancel()
            # Let both finish unwinding BEFORE finish() runs on a worker
            # thread, so nothing on the event loop can touch this call's
            # history while it is being saved. return_exceptions also
            # collects a crash instead of leaving it unretrieved.
            reader_result, pump_result = await asyncio.gather(reader, pump,
                                                              return_exceptions=True)
        if reader in done:          # the caller's side ended: the normal way out
            if isinstance(reader_result, Exception) \
                    and not isinstance(reader_result, WebSocketDisconnect):
                perf.event("error.twilio_stream")
                print(f"  [phone] bad message from Twilio mid-call "
                      f"({type(reader_result).__name__}); ending the call")
        elif pump in done:          # the model's side dropped or failed first
            why = type(pump_result).__name__ if isinstance(pump_result, BaseException) else "closed"
            perf.event("error.model_stream")
            print(f"  [phone] model stream ended mid-call ({why}); hanging up our side")
    except WebSocketDisconnect:
        pass
    finally:
        if holds_slot:
            _active_calls -= 1
            perf.gauge("calls.active", _active_calls)
        if live is not None:
            try:
                await live.close()
            except Exception:
                pass
        if bridge is not None:
            # Saving the call log reads the database and writes files: do it
            # on a worker thread so other live calls never stall, and never
            # let a failure here skip closing the socket below.
            try:
                await _off_loop(bridge.finish)
            except Exception as e:
                print(f"  (call {params.get('call_sid', '?')}: call log not saved: {type(e).__name__}: {e})")
        # Hang up our side too: a finished or failed call must never leave a
        # half-open socket (Twilio closes after "stop"; anything else may not).
        if ws.client_state == WebSocketState.CONNECTED:
            try:
                await ws.close()
            except RuntimeError:
                pass


# ---- outbound calls (started from the admin console) ---------------------------------

def start_outbound_call(client_id: str, to_number: str, purpose: str = "") -> str:
    """Ring a customer; when they pick up, the agent takes the call.
    purpose="callback" makes the agent open with "you gave us a missed call".
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
        url=f"{cfg['public_url']}/twilio/voice?client_id={quote(client_id)}"
            + ("&purpose=callback" if purpose == "callback" else ""),
        method="POST",
    )
    _reserve_slot(call.sid, time.time() + OUTBOUND_RING_S)
    return call.sid


def transfer_call(call_sid: str, to_number: str) -> None:
    """Replace a live call's stream with a <Dial> to the business's own phone.
    Twilio ends the media stream when the call's TwiML is replaced."""
    if not handoff_enabled():
        raise RuntimeError("Transfers are off (ENABLE_HANDOFF).")
    if not (call_sid and to_number):
        raise RuntimeError("No call to transfer, or no number to transfer it to.")
    cfg = twilio_config()
    twiml = ('<?xml version="1.0" encoding="UTF-8"?><Response>'
             f'<Dial timeout="{HANDOFF_RING_S}">{escape(to_number)}</Dial>'
             f'<Say>{escape(NO_ANSWER)}</Say></Response>')
    from twilio.rest import Client

    Client(cfg["sid"], cfg["token"]).calls(call_sid).update(twiml=twiml)


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


# ---- WhatsApp: the same receptionist, in the customer's WhatsApp --------------------
#
# Twilio POSTs each incoming WhatsApp message to /twilio/whatsapp; we answer
# with TwiML <Message>. Customers already message businesses on WhatsApp all
# day, so this is often the channel they reach first.
#
# OFF unless ENABLE_WHATSAPP=true. A business is reached through the number
# in its YAML's `whatsapp_number` (the platform sets it, like twilio_number;
# Twilio's sandbox number works for testing). We only ever REPLY: Atithi never
# starts a WhatsApp conversation, so there are no unsolicited messages.

WHATSAPP_IDLE = dt.timedelta(minutes=30)   # a longer silence starts a new conversation
WHATSAPP_REPLY_WAIT_S = 12                  # Twilio gives a webhook ~15 s; after this we reply via the API
WHATSAPP_MAX_CHARS = 1000
WHATSAPP_PER_SENDER = 20                    # messages per sender per 10 minutes
WHATSAPP_WINDOW = dt.timedelta(minutes=10)
WHATSAPP_MAX_SESSIONS = 500
_wa_sessions: dict[tuple[str, str], dict] = {}
_wa_recent: dict[str, list[dt.datetime]] = {}
_wa_lock = threading.Lock()


def whatsapp_enabled() -> bool:
    cfg = twilio_config()
    return (os.getenv("ENABLE_WHATSAPP", "").strip().lower() == "true"
            and bool(cfg["token"] and cfg["public_url"]))


def _wa_number(value: str) -> str:
    return value.removeprefix("whatsapp:").strip()


def _message(text: str | None) -> Response:
    body = f"<Message>{escape(text)}</Message>" if text else ""
    return Response(content=f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>',
                    media_type="application/xml")


def _wa_allowed(sender: str, now: dt.datetime) -> bool:
    """A sender may send WHATSAPP_PER_SENDER messages per window; past that we
    stay silent (each reply costs a model call)."""
    with _wa_lock:
        recent = [t for t in _wa_recent.get(sender, []) if now - t < WHATSAPP_WINDOW]
        if len(recent) >= WHATSAPP_PER_SENDER:
            _wa_recent[sender] = recent
            return False
        recent.append(now)
        _wa_recent[sender] = recent
        if len(_wa_recent) > 5000:          # forget quiet senders
            for k in [k for k, v in _wa_recent.items() if not v or now - v[-1] >= WHATSAPP_WINDOW]:
                del _wa_recent[k]
        return True


def _wa_session(client_id: str, sender: str, now: dt.datetime) -> dict | None:
    """This sender's open conversation with this business, or a new one."""
    key = (client_id, sender)
    with _wa_lock:
        s = _wa_sessions.get(key)
        if s is not None and now - s["last"] < WHATSAPP_IDLE:
            s["last"] = now
            return s
        if len(_wa_sessions) >= WHATSAPP_MAX_SESSIONS:
            for k in [k for k, v in _wa_sessions.items() if now - v["last"] >= WHATSAPP_IDLE]:
                del _wa_sessions[k]
            if len(_wa_sessions) >= WHATSAPP_MAX_SESSIONS:
                return None
        s = {"agent": None, "started": now, "last": now, "lock": threading.Lock(),
             "call_id": now.strftime("%Y%m%d_%H%M%S_whatsapp_") + secrets.token_hex(3)}
        _wa_sessions[key] = s
        return s


def _wa_turn(session: dict, client_id: str, sender: str, text: str) -> str:
    """One customer message -> the receptionist's reply. Runs on a worker
    thread; one message at a time per conversation."""
    with session["lock"]:
        if session["agent"] is None:
            agent = ReceptionistAgent(client_id)
            agent.system_prompt += (
                f"\n\nThis is a WHATSAPP chat. The customer's WhatsApp number is {sender}: when "
                "booking or saving a lead you may offer to use it, but confirm it first. Keep "
                "replies short, plain text, no markdown.")
            session["agent"] = agent
        agent = session["agent"]
        reply = agent.chat(text)
        try:
            storage.log_call_from_agent(agent, "whatsapp", session["started"],
                                        call_id=session["call_id"], caller=sender)
        except Exception as e:
            print(f"  [whatsapp] record not saved: {type(e).__name__}: {e}")
        return reply


def send_whatsapp(to: str, from_: str, body: str) -> str:
    """A reply sent through the API (when the model took too long for the
    webhook). Only ever a reply to a message the customer just sent."""
    from twilio.rest import Client
    cfg = twilio_config()
    return Client(cfg["sid"], cfg["token"]).messages.create(
        to=f"whatsapp:{to}", from_=f"whatsapp:{from_}", body=body).sid


@router.post("/twilio/whatsapp")
async def twilio_whatsapp(request: Request):
    if not whatsapp_enabled():
        raise HTTPException(status_code=503, detail="WhatsApp is disabled (ENABLE_WHATSAPP)")
    form = dict((await request.form()).items())
    if not _validate_signature(request, form):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")
    sender, line = _wa_number(form.get("From", "")), _wa_number(form.get("To", ""))
    text = " ".join(str(form.get("Body", "")).split())[:WHATSAPP_MAX_CHARS]
    if not sender:
        return _message(None)
    now = dt.datetime.now()
    if not _wa_allowed(sender, now):
        perf.event("whatsapp.rate_limited")
        return _message(None)
    client_id = await _off_loop(storage.client_for_number, line, "whatsapp_number")
    if client_id is None or not await _off_loop(billing.client_active, client_id):
        return _message("Sorry, this number isn't taking messages right now.")
    if not text:
        # A photo, voice note or sticker: we can only read text for now.
        return _message("Sorry, I can only read text messages. Could you type your question?")
    session = _wa_session(client_id, sender, now)
    if session is None:
        return _message("Sorry, we're very busy right now. Please message again in a few minutes.")
    job = call_io_pool().submit(_wa_turn, session, client_id, sender, text)
    try:
        reply = await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(job)), WHATSAPP_REPLY_WAIT_S)
        return _message(reply)
    except TimeoutError:
        # Too slow for the webhook: answer through the API once it's ready.
        perf.event("whatsapp.late_reply")

        def late(fut):
            try:
                send_whatsapp(sender, line, fut.result())
            except Exception as e:
                print(f"  [whatsapp] late reply not sent: {type(e).__name__}: {e}")
        job.add_done_callback(late)
        return _message(None)
    except Exception as e:
        perf.event("error.whatsapp")
        print(f"  [whatsapp] reply failed: {type(e).__name__}: {e}")
        return _message("Sorry, something went wrong on our side. Please try again in a moment.")
