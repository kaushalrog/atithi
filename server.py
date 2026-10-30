"""server.py — the Atithi business portal.

This is the page a BUSINESS OWNER uses (any business that takes bookings:
a clinic, salon, restaurant, gym, coaching centre, repair shop...):
  1. Onboard: fill a form with their business details -> we write
     clients/<client_id>.yaml (the multi-tenant principle as a web form).
  2. The AI receptionist handles conversations for them.
  3. They watch results: bookings, leads, full call history with transcripts,
     and top-line stats (calls, minutes talked, conversion).

Still a thin layer (principle 3): endpoints translate HTTP <-> ReceptionistAgent
calls, and all persistence lives in storage.py. Zero business logic here.

Run:  python server.py            (opens http://127.0.0.1:8765)
"""

import argparse
import contextlib
import contextvars
import copy
import datetime as dt
import hmac
import ipaddress
import os
import re
import secrets
import threading
import uuid
import webbrowser
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

import auth
import billing
import callbacks
import llm as llm_module
import notify
import perf
import ratelimit
import scheduling
import storage
import telephony
from agent import ReceptionistAgent
from tts import EdgeTTS, TTSTimeout

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Atithi")


class BodySizeLimit:
    """Refuse oversized requests by their Content-Length header, BEFORE any
    body is read. The per-endpoint checks (e.g. the 5 MB voice limit) only run
    after Starlette has already spooled the whole upload to disk.

    A body-carrying request with NO Content-Length (a chunked upload, whose
    size isn't known up front) is refused with 411: browsers' fetch() and
    Twilio always send the header. Still put a reverse proxy's body limit in
    front of any public deployment."""

    BODY_METHODS = {"POST", "PUT", "PATCH"}

    def __init__(self, inner):
        self.inner = inner

    @staticmethod
    async def _refuse(send, status: int, message: bytes):
        body = b'{"detail":"' + message + b'"}'
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            length = dict(scope.get("headers") or []).get(b"content-length")
            if length is None:
                if scope.get("method") in self.BODY_METHODS:
                    return await self._refuse(send, 411, b"Content-Length required")
            elif not length.isdigit() or int(length) > MAX_BODY_BYTES:
                return await self._refuse(send, 413, b"Request too large")
        await self.inner(scope, receive, send)


app.add_middleware(BodySizeLimit)
app.include_router(telephony.router)  # /twilio/voice + /twilio/stream (phone calls)

# ---------- credential throttle (audit RT-3, review 2026-10-21) ---------------
#
# Wrong credentials are counted where they are checked, per (address, what is
# being guessed): each business's code separately, the admin key, code login,
# password login and reset codes. So one attacker guessing business A can't
# lock out business B, and nobody can lock out everyone behind a shared
# address (an earlier version counted every 401 per address and could).
# Expired sign-in tokens aren't counted: tokens are long random strings, not
# guessable, and a stale browser tab would otherwise lock its own owner out.

CREDENTIAL_FAILURES = ratelimit.FailureLimiter()
_request_ip: contextvars.ContextVar[str] = contextvars.ContextVar("request_ip", default="?")


def _proxy_hops() -> int:
    """How many proxies of ours sit in front of the server (VOXAGENT_TRUST_PROXY:
    'true' = 1, or a number). 0 = trust no forwarding header."""
    raw = os.getenv("VOXAGENT_TRUST_PROXY", "").strip().lower()
    if raw in ("true", "yes"):
        return 1
    return int(raw) if raw.isdigit() else 0


def _client_ip(request: Request) -> str:
    """The caller's address. Behind our own proxy, X-Forwarded-For is read from
    the RIGHT: each proxy appends the address it saw, so the last N entries
    come from our proxies and anything to their left is whatever the client
    sent (spoofable). IPv6 addresses count per /64, which one user controls."""
    ip = request.client.host if request.client else "?"
    hops = _proxy_hops()
    if hops:
        chain = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
        if len(chain) >= hops:
            ip = chain[-hops]
    try:
        addr = ipaddress.ip_address(ip)
        if addr.version == 6:
            return str(ipaddress.ip_network(f"{addr}/64", strict=False))
    except ValueError:
        pass
    return ip


@app.middleware("http")
async def remember_client_ip(request: Request, call_next):
    """Make the caller's address available to the credential checks below
    (contextvars follow the request into FastAPI's worker threads)."""
    token = _request_ip.set(_client_ip(request))
    try:
        return await call_next(request)
    finally:
        _request_ip.reset(token)


def throttle(scope: str):
    """Refuse (429) while this address has too many wrong guesses at `scope`.
    Checked BEFORE the credential, so a blocked guesser learns nothing even
    when the next guess would have been right."""
    wait = CREDENTIAL_FAILURES.retry_after(f"{_request_ip.get()}|{scope}")
    if wait:
        perf.event("auth.throttled")
        minutes = max(1, round(wait / 60))
        raise HTTPException(status_code=429, headers={"Retry-After": str(wait)},
                            detail=f"Too many failed sign-in attempts. Try again in about "
                                   f"{minutes} minute{'s' if minutes != 1 else ''}.")


def wrong_guess(scope: str):
    CREDENTIAL_FAILURES.fail(f"{_request_ip.get()}|{scope}")
tts = EdgeTTS()


@app.on_event("startup")
def _warm_up():
    """Build the Gemini client while the server boots.

    It costs ~780 ms to construct. Doing it here means the first caller — who
    is on a live phone line — doesn't wait for it.
    """
    llm_module.warm_up()
    problem = auth.admin_password_problem()
    if problem:
        print(f"  [admin] admin console disabled: {problem}")
    # Seed (and, if needed, take back) the admin account now, not on the
    # first login — so a signup can't race the owner for ADMIN_EMAIL. A
    # failure is logged, never fatal: the portal must still come up.
    try:
        auth.ensure_admin_seed()
    except Exception as e:
        print(f"  [admin] could not seed the admin account: {type(e).__name__}: {e}")
    paused = storage.bookings_paused_reason()
    if paused:
        print(f"  [bookings] NEW BOOKINGS ARE PAUSED: {paused}")
    print(_capacity_line())
    short = storage.short_code_businesses()
    if short:
        print(f"  [security] {len(short)} business(es) still use an old short code "
              f"({', '.join(short)}). Rotate before going public: python storage.py rotate-code <id>")
    # The callback dialer runs in the background and checks its switch
    # (ENABLE_CALLBACKS) on every round, so it does nothing until turned on.
    callbacks.start_worker(_callbacks_stop)


_callbacks_stop = threading.Event()


def _capacity_line() -> str:
    """The limits this process runs with, printed once at startup.

    WHY: Atithi is ONE process (the phone tickets' signing key and the
    session table live in its memory). Its capacity is these numbers, and
    nothing scales them for you — see SETUP.md "Capacity"."""
    try:
        import anyio.to_thread
        portal = anyio.to_thread.current_default_thread_limiter().total_tokens
    except Exception:            # no async backend in this thread: show the default
        portal = "40 (anyio default)"
    calls = telephony.max_concurrent_calls()
    return (f"  [capacity] one process · portal worker threads: {portal} · "
            f"phone call-I/O threads: {telephony.call_io_workers()} · "
            f"MAX_CONCURRENT_CALLS={calls} (keep it within your Gemini Live tier) · "
            f"web sessions: {MAX_SESSIONS_PER_BUSINESS}/business, {MAX_SESSIONS} total")


# The pages change only when we deploy, so serve them from memory — but
# revalidate against the file's mtime (one stat() call) so editing a page
# during development doesn't serve a stale copy until restart.
_page_cache: dict[str, tuple] = {}


def _page(name: str) -> str:
    path = BASE_DIR / "web" / name
    stamp = path.stat().st_mtime_ns
    hit = _page_cache.get(name)
    if hit is None or hit[0] != stamp:
        hit = (stamp, path.read_text(encoding="utf-8"))
        _page_cache[name] = hit
    return hit[1]

# One test-call session = one agent + one call-log entry. In memory only; the
# call log JSON on disk is the durable record. Everything here is BOUNDED, so
# a long-running server (or someone scripting the portal) can't grow it
# without limit (docs/PERFORMANCE_AUDIT.md F8): idle sessions are purged on
# every request, and sessions and turns are capped. Each turn re-sends the
# whole history to the model, so turn 60 already costs ~60x turn 1.
sessions: dict[str, dict] = {}
_sessions_lock = threading.Lock()   # sync endpoints run on many threads at once
SESSION_IDLE_LIMIT = dt.timedelta(hours=2)
MAX_TURNS_PER_SESSION = 60
MAX_SESSIONS_PER_BUSINESS = 20
MAX_SESSIONS = 500
CLOSING_LINE = ("Thanks for chatting — this conversation has reached its limit. "
                "Please start a new one, or the front desk will call you back.")

MIME_FIX = {"audio/mpeg": "audio/mp3", "audio/x-wav": "audio/wav",
            "application/octet-stream": "audio/wav"}

WEEKDAYS = scheduling.WEEKDAYS   # one definition, shared with the scheduler

DEFAULT_FALLBACK = (
    "If you are unsure about anything, or the customer asks something not "
    "covered in the business information, say that the front desk will call "
    "them back with the exact details. NEVER guess or invent prices, offers, "
    "or professional advice."
)
BOOKING_WORDS = ("appointment", "reservation", "table", "session", "class", "service visit", "slot")


# ---------- request models ----------------------------------------------------

class SessionRequest(BaseModel):
    client_id: str = "demo_clinic"


# Size limits (audit M5): a customer turn longer than this is not a real
# turn, and every message is re-sent to the model on each later turn — so an
# unbounded one costs quota and money for the rest of the conversation.
MAX_CHAT_CHARS = 2000
MAX_TTS_CHARS = 1000                # mirrored in web/index.html speak()
MAX_VOICE_BYTES = 5 * 1024 * 1024   # ~55 s of the portal's 48 kHz WAV; a turn is seconds
MAX_BODY_BYTES = 6 * 1024 * 1024    # whole request, checked before it is parsed


class ChatRequest(BaseModel):
    session_id: str
    message: str = Field(max_length=MAX_CHAT_CHARS)


class TTSRequest(BaseModel):
    session_id: str                 # only a live test call may use our TTS
    text: str = Field(max_length=MAX_TTS_CHARS)


class AdminLoginRequest(BaseModel):
    password: str


class PortalLoginRequest(BaseModel):
    access_key: str


class CredentialsRequest(BaseModel):
    email: str
    password: str


class ActivateRequest(BaseModel):
    client_id: str
    months: int = 1


class ForgotRequest(BaseModel):
    email: str


class ResetRequest(BaseModel):
    email: str
    code: str
    new_password: str


class OutboundCallRequest(BaseModel):
    client_id: str
    to: str


class ServiceItem(BaseModel):
    name: str
    price: str


class FaqItem(BaseModel):
    q: str
    a: str


class BusinessRequest(BaseModel):
    business_name: str
    address: str = ""
    phone: str = ""
    timings: str = ""
    services: list[ServiceItem]
    faq: list[FaqItem] = []
    policies: list[str] = []
    fallback: str = DEFAULT_FALLBACK
    slot_days: list[str] = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    slot_ranges: list[list[str]] = [["10:00", "13:00"], ["16:00", "20:00"]]
    slot_gap_min: int = 30
    languages: list[str] = ["en"]       # first = the greeting language
    sms_confirmations: bool = True      # still needs ENABLE_SMS=true to actually send
    closed_dates: list[dict[str, str]] = []   # [{date, from?, to?, reason?}]
    website_chat: bool = False                 # off until the owner switches it on
    business_type: str = Field(default="", max_length=60)   # "dental clinic", "restaurant"...
    booking_word: str = "appointment"          # what customers book: table, session, class...
    handoff_phone: str = Field(default="", max_length=20)   # where "talk to a person" calls go
    missed_call_mode: bool = False             # reject calls (busy tone) and ring back
    callback_when_busy: bool = True            # lines busy: offer a callback


def _clean_closed(entries: list[dict]) -> list[dict]:
    """Validated closed dates, past ones dropped (they can't matter any more)."""
    try:
        cleaned = scheduling.clean_closed(entries)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Closed dates: {e}")
    today = dt.date.today().isoformat()
    return [c for c in cleaned if c["date"] >= today]


def _clean_handoff_phone(phone: str) -> str:
    """"" (no transfers) or a full international number Twilio can dial."""
    if not (phone or "").strip():
        return ""
    e164 = notify.to_e164(phone)
    if e164 is None:
        raise HTTPException(status_code=422, detail="Transfer number: enter a full mobile number, e.g. +91 98765 43210")
    return e164


def _clean_booking_word(word: str) -> str:
    word = (word or "appointment").strip().lower()
    if word not in BOOKING_WORDS:
        raise HTTPException(status_code=422, detail=f"Bookings must be one of: {', '.join(BOOKING_WORDS)}")
    return word


def _clean_languages(codes: list[str]) -> list[str]:
    from agent import LANGUAGES
    out = []
    for c in codes:
        if c not in LANGUAGES:
            raise HTTPException(status_code=422, detail=f"Unsupported language '{c}'")
        if c not in out:
            out.append(c)
    return out or ["en"]


# ---------- access control -------------------------------------------------------
#
# Primary: email+password accounts (auth.py) — the frontend sends the session
# token as "Authorization: Bearer <token>". Admin sees everything; an owner
# only their own business. The older mechanisms (X-Admin-Key password header,
# per-business access codes) still work as fallbacks for scripts and tests.

def bearer_user(authorization: str | None) -> dict | None:
    if authorization and authorization.startswith("Bearer "):
        return auth.user_for_token(authorization[7:])
    return None


def same_secret(supplied, expected) -> bool:
    """Constant-time comparison that never crashes. hmac.compare_digest raises
    on non-ASCII str and on str-vs-int (a hand-edited YAML code like 482913),
    which surfaced as HTTP 500 instead of a rejection — so compare bytes."""
    if supplied is None or expected is None:
        return False
    return hmac.compare_digest(str(supplied).encode(), str(expected).encode())


def is_admin(user: dict | None) -> bool:
    """Admin role counts only for the CURRENT ADMIN_EMAIL, and only while
    ADMIN_PASSWORD passes the policy. So an admin account seeded earlier (from
    a placeholder password, or under an old email) has no admin rights."""
    if not (user and user["role"] == "admin") or auth.admin_password_problem():
        return False
    return user["email"] == os.getenv("ADMIN_EMAIL", "").strip().lower()


def client_access_key(client_id: str) -> str | None:
    cfg = storage.read_client_config(client_id)
    return cfg.get("access_key") if cfg else None


def authorize_client(client_id: str, client_key: str | None, admin_key: str | None,
                     authorization: str | None = None):
    user = bearer_user(authorization)
    if is_admin(user) or (user and user["client_id"] == client_id):
        return
    if admin_key:
        throttle("admin")
        if auth.admin_password_matches(admin_key):
            return
        wrong_guess("admin")
    expected = client_access_key(client_id)
    if client_key:
        # An unknown business id shares one bucket, so made-up ids can't
        # buy an attacker extra guesses.
        scope = f"code:{client_id}" if expected else "code:?"
        throttle(scope)
        if expected and same_secret(client_key, expected):
            return
        wrong_guess(scope)
    raise HTTPException(status_code=401, detail="Not authorized for this business")


# ---------- helpers ------------------------------------------------------------

def get_session(session_id: str) -> dict:
    purge_idle_sessions()
    with _sessions_lock:
        session = sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Unknown or expired session")
        # Touched on every use, so a session a request has just fetched (and
        # is about to lock) is never the "oldest idle" one evicted at the cap.
        session["last_activity"] = dt.datetime.now()
    return session


def _owner_session(session_id: str) -> dict:
    """A session from the owner's own test widget. Voice and speech cost
    money or capacity, so a public website-chat session can't use them."""
    session = get_session(session_id)
    if session.get("channel", "web-test") != "web-test":
        raise HTTPException(status_code=403, detail="Not available for website chat")
    return session


def purge_idle_sessions():
    """Drop sessions idle for 2 h. A scan of at most MAX_SESSIONS dicts —
    microseconds — so it runs on every request, not only at session start.
    A session mid-turn is never dropped, however long the model takes."""
    now = dt.datetime.now()
    with _sessions_lock:
        for sid in [s for s, v in sessions.items()
                    if now - v["last_activity"] > SESSION_IDLE_LIMIT
                    and not v["lock"].locked()]:
            del sessions[sid]
    perf.gauge("sessions.active", len(sessions))


@contextlib.contextmanager
def one_turn_at_a_time(session: dict):
    """Refuse a second message while this session is still answering.

    WHY: two tabs (or a double-click) on one session used to run two turns at
    once on two threads, interleaving both into the same history — a tool
    call separated from its result breaks every later model request (audit
    F7, 18 of 20 runs). It refuses instead of waiting, because a waiting
    request would hold one of the server's worker threads for nothing."""
    if not session["lock"].acquire(blocking=False):
        raise HTTPException(status_code=409,
                            detail="Still answering your last message — send this one after the reply.")
    try:
        yield
    finally:
        session["last_activity"] = dt.datetime.now()
        session["lock"].release()


def turn_cap_reached(session: dict) -> bool:
    return sum(1 for m in session["agent"].history if m["role"] == "user") >= MAX_TURNS_PER_SESSION


def run_turn(session: dict, message: str) -> dict:
    """One customer turn; also reports which tools fired so the UI can show them.
    The caller holds one_turn_at_a_time(session)."""
    agent = session["agent"]
    if turn_cap_reached(session):
        # The cap: a polite end, no model call, nothing more added to history.
        return {"reply": CLOSING_LINE, "tools": [], "ended": True}
    before = len(agent.history)
    reply = agent.chat(message)
    tools = []
    for msg in agent.history[before:]:
        if msg["role"] == "assistant" and msg.get("tool_calls"):
            for call in msg["tool_calls"]:
                tools.append({"name": call["name"], "args": call["args"]})
    session["last_activity"] = dt.datetime.now()
    storage.log_call_from_agent(agent, session.get("channel", "web-test"), session["started"],
                                call_id=session["call_id"])
    return {"reply": reply, "tools": tools}


def generate_slots(days: list[str], ranges: list[list[str]], gap_min: int) -> dict:
    """Expand 'open Mon-Sat, 10-1 and 4-8, every 30 min' into dated slots.

    Kept as a preview of the rule for the onboarding form. What a business
    STORES is the rule itself (`schedule:`), not these dates — see
    scheduling.py for why that outage-proofing matters.
    """
    return scheduling.generate(
        scheduling.schedule_from_form(days, ranges, gap_min)
    )


# ---------- admin (the platform owner's console) --------------------------------
#
# WHY same backend, different page: the admin console is just another thin
# client of the same data (principle 3 again). A second server would double
# the deployment work for zero benefit at this stage. Access control is a
# shared secret from .env sent as an X-Admin-Key header — simple, and the
# shape is right: when real client logins arrive, this becomes a role check.

def require_admin(x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
                  authorization: str | None = Header(default=None)):
    problem = auth.admin_password_problem()
    if problem:
        # The reason goes to the server log, not to whoever is knocking: an
        # anonymous caller shouldn't learn that admin is misconfigured or how.
        print(f"  [admin] admin console disabled: {problem}")
        raise HTTPException(status_code=503, detail="Admin console unavailable")
    if is_admin(bearer_user(authorization)):
        return
    if x_admin_key:
        throttle("admin")
        if auth.admin_password_matches(x_admin_key):
            return
        wrong_guess("admin")
    raise HTTPException(status_code=401, detail="Admin access only")


@app.post("/api/admin/login")
def admin_login(req: AdminLoginRequest):
    # Pass both arguments: called directly (not via Depends), the defaults
    # would be FastAPI Header() objects, which crashed this endpoint (R6a).
    require_admin(x_admin_key=req.password, authorization=None)
    return {"ok": True}


@app.get("/api/admin/overview", dependencies=[Depends(require_admin)])
def admin_overview():
    """Everything the platform owner needs in one response: totals across all
    clients, a health row per business, and the latest calls platform-wide."""
    clients, all_calls = [], []
    totals = {"clients": 0, "calls": 0, "minutes": 0.0, "bookings": 0, "leads": 0}
    for entry in storage.all_clients():          # cached parses, no re-globbing
        cfg = entry["config"]
        client_id = entry["client_id"]
        calls = storage.read_call_logs(client_id)
        minutes = round(sum(c["seconds"] for c in calls) / 60, 1)
        n_bookings = sum(b["status"] == "confirmed" for b in storage.read_bookings(client_id))
        n_leads = len(storage.read_leads(client_id))
        billing_block = cfg.get("billing") or {}
        clients.append({
            "client_id": client_id,
            "business_name": cfg.get("business_name", client_id),
            "access_key": cfg.get("access_key", "—"),
            "plan": billing_block.get("plan", "free"),
            "paid_until": billing_block.get("paid_until"),
            "renewal_requested": billing_block.get("renewal_requested"),
            "active": billing._is_active(billing_block),   # config already in hand
            "phone": cfg.get("phone", ""),
            "calls": len(calls),
            "minutes": minutes,
            "bookings": n_bookings,
            "leads": n_leads,
            "last_activity": calls[0]["started"] if calls else None,
        })
        for c in calls:
            all_calls.append({**c, "business_name": cfg.get("business_name", client_id)})
        totals["clients"] += 1
        totals["calls"] += len(calls)
        totals["minutes"] = round(totals["minutes"] + minutes, 1)
        totals["bookings"] += n_bookings
        totals["leads"] += n_leads
    all_calls.sort(key=lambda c: c["started"], reverse=True)
    recent = [{
        "business_name": c["business_name"],
        "started": c["started"],
        "channel": c["channel"],
        "seconds": c["seconds"],
        "turns": c["turns"],
        **record_outcome(c),
    } for c in all_calls[:12]]
    return {"totals": totals, "clients": clients, "recent_calls": recent,
            "password_resets": auth.pending_resets(),
            # "connected" only when calls can actually be answered.
            "twilio_configured": telephony.is_configured() and telephony.live_calls_enabled(),
            "status": {
                "gemini_key": bool(os.getenv("GEMINI_API_KEY")),
                "twilio": telephony.is_configured() and telephony.live_calls_enabled(),
                "live_calls": telephony.live_calls_enabled(),
                "twilio_keys": telephony.is_configured(),
                # Why new bookings are paused (D5: Sheet not imported yet, or a
                # broken bookings.csv), or null. Shown as its own status row.
                "bookings_paused": storage.bookings_paused_reason(),
                # Green only when the Sheet can actually be used (credentials present).
                "sheets": storage.sheets_usable(),
                # Each of these rings or messages real people: off by default.
                "handoff": telephony.handoff_enabled(),
                "callbacks": telephony.callbacks_enabled(),
                "whatsapp": telephony.whatsapp_enabled(),
                "sms": telephony.sms_enabled(),
            }}


@app.get("/api/admin/perf", dependencies=[Depends(require_admin)])
def admin_perf():
    """Latency percentiles, counters and gauges measured inside this process
    (perf.py). Durations only — no transcripts, names or numbers."""
    perf.gauge("sessions.active", len(sessions))
    return perf.snapshot()


@app.post("/api/admin/activate", dependencies=[Depends(require_admin)])
def admin_activate(req: ActivateRequest):
    """The owner paid — extend their plan by N months."""
    try:
        paid_until = billing.set_paid_until(req.client_id, max(1, req.months))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True, "paid_until": paid_until}


@app.post("/api/admin/call", dependencies=[Depends(require_admin)])
def admin_outbound_call(req: OutboundCallRequest):
    """Ring a customer's number; the agent takes the call when they answer."""
    try:
        sid = telephony.start_outbound_call(req.client_id, req.to)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Twilio error: {e}")
    return {"ok": True, "call_sid": sid}


# ---------- pages & business management ----------------------------------------

@app.get("/", response_class=HTMLResponse)
def index():
    return _page("index.html")


@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    return _page("admin.html")


@app.get("/logo.svg")
def logo():
    return Response(
        content=_page("logo.svg").encode("utf-8"),
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/api/clients", dependencies=[Depends(require_admin)])
def list_clients():
    return [{"client_id": e["client_id"],
             "business_name": e["config"].get("business_name", e["client_id"])}
            for e in storage.all_clients()]


def _with_business_name(session: dict) -> dict:
    if session.get("client_id"):
        cfg = storage.read_client_config(session["client_id"]) or {}
        session["business_name"] = cfg.get("business_name", session["client_id"])
    return session


@app.post("/api/auth/signup")
def auth_signup(req: CredentialsRequest):
    """New business owner creates an account; onboarding comes next."""
    try:
        return _with_business_name(auth.signup(req.email, req.password))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.post("/api/auth/login")
def auth_login(req: CredentialsRequest):
    throttle("password-login")
    try:
        return _with_business_name(auth.login(req.email, req.password))
    except PermissionError as e:
        wrong_guess("password-login")
        raise HTTPException(status_code=401, detail=str(e))


@app.post("/api/auth/forgot")
def auth_forgot(req: ForgotRequest):
    """Start a password reset. The response is identical whether or not the
    email exists, so nobody can probe for accounts."""
    code = auth.create_reset(req.email)
    emailed = bool(code) and auth.send_reset_email(req.email.strip().lower(), code)
    return {"ok": True, "emailed": emailed,
            "message": ("Check your email for the reset code."
                        if emailed else
                        "If this account exists, a reset code was created — "
                        "ask the Atithi team for it, then enter it below.")}


@app.post("/api/auth/reset")
def auth_reset(req: ResetRequest):
    throttle("reset")
    try:
        return _with_business_name(auth.reset_password(req.email, req.code, req.new_password))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except PermissionError as e:
        wrong_guess("reset")
        raise HTTPException(status_code=401, detail=str(e))


@app.post("/api/portal/login")
def portal_login(req: PortalLoginRequest):
    """A business owner logs in with their business code."""
    throttle("code-login")
    code = req.access_key.strip()
    if code:
        for entry in storage.all_clients():
            cfg = entry["config"]
            if cfg.get("access_key") and same_secret(code, cfg["access_key"]):
                return {"client_id": entry["client_id"],
                        "business_name": cfg.get("business_name", entry["client_id"])}
    wrong_guess("code-login")
    raise HTTPException(status_code=401, detail="That code doesn't match any business")


@app.post("/api/business")
def create_business(req: BusinessRequest,
                    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
                    authorization: str | None = Header(default=None)):
    # Admin can create any number of businesses; a signed-up owner exactly one
    # (their own — it gets linked to their account and starts a free trial).
    user = bearer_user(authorization)
    as_admin = is_admin(user) or auth.admin_password_matches(x_admin_key)
    if not as_admin:
        if user is None:
            raise HTTPException(status_code=401, detail="Sign in to create your business")
        if user["client_id"]:
            raise HTTPException(status_code=403, detail="Your account already has a business")

    services = [s for s in req.services if s.name.strip()]
    if not req.business_name.strip() or not services:
        raise HTTPException(status_code=422, detail="Business name and at least one service are required")

    client_id = re.sub(r"[^a-z0-9]+", "_", req.business_name.lower()).strip("_")[:40]
    path = BASE_DIR / "clients" / f"{client_id}.yaml"
    if path.exists():
        raise HTTPException(status_code=409, detail=f"A business '{client_id}' already exists")

    config = {
        "client_id": client_id,
        # The owner's login code — shown once to the admin at creation.
        "access_key": storage.new_access_code(),
        "business_name": req.business_name.strip(),
        "address": req.address.strip(),
        "phone": req.phone.strip(),
        "timings": req.timings.strip(),
        "services": [{"name": s.name.strip(), "price": s.price.strip()} for s in services],
        "faq": [{"q": f.q.strip(), "a": f.a.strip()} for f in req.faq if f.q.strip()],
        "policies": [p.strip() for p in req.policies if p.strip()],
        "fallback": req.fallback.strip() or DEFAULT_FALLBACK,
        "languages": _clean_languages(req.languages),
        "sms_confirmations": bool(req.sms_confirmations),
        "business_type": req.business_type.strip(),
        "booking_word": _clean_booking_word(req.booking_word),
        # Every new business starts on a free trial; after that the owner
        # pays and the admin activates (see billing.py).
        "billing": billing.new_trial(),
        # Store the RULE, not dated slots: dated slots silently expired and
        # left the agent unable to book anything (see scheduling.py).
        "schedule": scheduling.schedule_from_form(
            req.slot_days, req.slot_ranges, req.slot_gap_min
        ),
    }
    config["schedule"]["closed"] = _clean_closed(req.closed_dates)
    # Through storage so the config caches invalidate with the write.
    storage.write_client_config(client_id, config)
    if not as_admin:
        auth.attach_client(user["email"], client_id)
    return {"client_id": client_id, "business_name": config["business_name"],
            "access_key": config["access_key"]}


# ---------- talking to the agent (the Test-agent widget) ------------------------

# ---------- business settings (the owner edits what onboarding created) ----------

def _settings_view(cfg: dict) -> dict:
    """The editable part of a client YAML, in the onboarding form's shape."""
    sched = cfg.get("schedule") or {}
    ranges = [list(r) for r in sched.get("ranges") or []][:2]
    return {
        "business_name": cfg.get("business_name", ""),
        "phone": cfg.get("phone", ""),
        "address": cfg.get("address", ""),
        "timings": cfg.get("timings", ""),
        "services": [{"name": s.get("name", ""), "price": str(s.get("price", ""))}
                     for s in cfg.get("services") or []],
        "faq": [{"q": f.get("q", ""), "a": f.get("a", "")} for f in cfg.get("faq") or []],
        "policies": list(cfg.get("policies") or []),
        "fallback": cfg.get("fallback", DEFAULT_FALLBACK),
        "slot_days": list(sched.get("days") or []),
        "slot_ranges": ranges,
        "slot_gap_min": int(sched.get("gap_min") or 30),
        "languages": list(cfg.get("languages") or ["en"]),
        "sms_confirmations": cfg.get("sms_confirmations", True) is not False,
        "closed_dates": list(sched.get("closed") or []),
        "website_chat": bool(cfg.get("website_chat")),
        "business_type": cfg.get("business_type", ""),
        "booking_word": cfg.get("booking_word") or "appointment",
        "handoff_phone": cfg.get("handoff_phone", ""),
        "missed_call_mode": bool(cfg.get("missed_call_mode")),
        "callback_when_busy": cfg.get("callback_when_busy", True) is not False,
        "widget_key": cfg.get("widget_key", "") if cfg.get("website_chat") else "",
    }


@app.get("/api/business/{client_id}/settings")
def get_settings(client_id: str,
                 x_client_key: str | None = Header(default=None, alias="X-Client-Key"),
                 x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
                 authorization: str | None = Header(default=None)):
    authorize_client(client_id, x_client_key, x_admin_key, authorization)
    cfg = storage.read_client_config(client_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"No client '{client_id}'")
    return _settings_view(cfg)


@app.put("/api/business/{client_id}/settings")
def save_settings(client_id: str, req: BusinessRequest,
                  x_client_key: str | None = Header(default=None, alias="X-Client-Key"),
                  x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
                  authorization: str | None = Header(default=None)):
    """Update what the receptionist knows. Everything else in the YAML (the
    owner's code, billing, phone-number mapping, client id) is kept as is.
    A test call already open keeps the old details; the next one gets these."""
    authorize_client(client_id, x_client_key, x_admin_key, authorization)
    current = storage.read_client_config(client_id)
    if current is None:
        raise HTTPException(status_code=404, detail=f"No client '{client_id}'")
    services = [s for s in req.services if s.name.strip()]
    if not req.business_name.strip() or not services:
        raise HTTPException(status_code=422, detail="Business name and at least one service are required")
    schedule = scheduling.schedule_from_form(
        req.slot_days, req.slot_ranges, req.slot_gap_min,
        horizon_days=(current.get("schedule") or {}).get("horizon_days",
                                                         scheduling.DEFAULT_HORIZON_DAYS))
    if not schedule["days"] or not schedule["ranges"]:
        raise HTTPException(status_code=422, detail="Choose at least one open day and one time range")
    schedule["closed"] = _clean_closed(req.closed_dates)
    cfg = copy.deepcopy(current)          # the cached parse is shared: never mutate it
    cfg.update({
        "business_name": req.business_name.strip(),
        "address": req.address.strip(),
        "phone": req.phone.strip(),
        "timings": req.timings.strip(),
        "services": [{"name": s.name.strip(), "price": s.price.strip()} for s in services],
        "faq": [{"q": f.q.strip(), "a": f.a.strip()} for f in req.faq if f.q.strip()],
        "policies": [p.strip() for p in req.policies if p.strip()],
        "fallback": req.fallback.strip() or DEFAULT_FALLBACK,
        "schedule": schedule,
        "languages": _clean_languages(req.languages),
        "sms_confirmations": bool(req.sms_confirmations),
        "website_chat": bool(req.website_chat),
        "business_type": req.business_type.strip(),
        "booking_word": _clean_booking_word(req.booking_word),
        "handoff_phone": _clean_handoff_phone(req.handoff_phone),
        "missed_call_mode": bool(req.missed_call_mode),
        "callback_when_busy": bool(req.callback_when_busy),
    })
    if cfg["website_chat"] and not cfg.get("widget_key"):
        # A PUBLIC key, separate from the owner's login code: it only opens chats.
        cfg["widget_key"] = "wk_" + secrets.token_urlsafe(12)
    cfg.pop("slots", None)                 # a saved rule replaces any legacy dated slots
    storage.write_client_config(client_id, cfg)
    return _settings_view(cfg)


@app.post("/api/session")
def create_session(req: SessionRequest,
                   x_client_key: str | None = Header(default=None, alias="X-Client-Key"),
                   x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
                   authorization: str | None = Header(default=None)):
    authorize_client(req.client_id, x_client_key, x_admin_key, authorization)
    if not billing.client_active(req.client_id):
        raise HTTPException(status_code=402,
                            detail="This business's plan has ended — activate it to continue")
    purge_idle_sessions()
    try:
        agent = ReceptionistAgent(req.client_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"No client '{req.client_id}'")
    session_id = _open_session(req.client_id, agent, "web-test", MAX_SESSIONS_PER_BUSINESS)
    return {"session_id": session_id, "business_name": agent.config["business_name"]}


def _open_session(client_id: str, agent, channel: str, cap: int) -> str:
    """Register a conversation; each (business, channel) has its own pool, so
    website visitors can never push out the owner's test calls."""
    session_id = uuid.uuid4().hex
    now = dt.datetime.now()
    with _sessions_lock:      # count and insert together, or two requests both fit
        if len(sessions) >= MAX_SESSIONS:
            raise HTTPException(status_code=429,
                                detail="Too many conversations are open right now — try again shortly.")
        mine = [(v["last_activity"], sid) for sid, v in sessions.items()
                if v["client_id"] == client_id and v.get("channel", "web-test") == channel]
        if len(mine) >= cap:
            # Make room by dropping this business's OWN oldest idle session
            # (its call record is already on disk). Refusing instead locked
            # an owner out for 2 hours after 20 demo clicks. A session that
            # is mid-reply is never dropped, and no other business's is.
            idle = [(t, sid) for t, sid in mine if not sessions[sid]["lock"].locked()]
            if not idle:
                raise HTTPException(status_code=429,
                                    detail="This business has too many test calls open — "
                                           "close one or wait a while.")
            del sessions[min(idle)[1]]
        sessions[session_id] = {
            "agent": agent,
            "client_id": client_id,
            "channel": channel,
            "call_id": now.strftime("%Y%m%d_%H%M%S_") + session_id[:6],
            "started": now,
            "last_activity": now,
            "lock": threading.Lock(),
        }
    return session_id


class EndSessionRequest(BaseModel):
    session_id: str = Field(max_length=64)


@app.post("/api/session/end")
def end_session(req: EndSessionRequest):
    """The owner closed the test widget: free its slot now, not after 2 h idle.
    Like /api/chat, knowing the random session id is the permission, so it
    travels in the body, never the URL (URLs end up in access logs). The call
    record is already saved; a reply still being generated finishes normally."""
    with _sessions_lock:
        sessions.pop(req.session_id, None)
    return {"ok": True}


FRONT_DESK_LINE = ("Sorry, our line is very busy right now — the front desk "
                   "will call you back shortly.")


@app.post("/api/chat")
def chat(req: ChatRequest):
    session = get_session(req.session_id)
    with one_turn_at_a_time(session):
        return _chat_turn(session, req.message)


def _chat_turn(session: dict, message: str) -> dict:
    agent = session["agent"]
    before = len(agent.history)
    # A model outage or rate limit must never show the customer an error page.
    try:
        return run_turn(session, message)
    except Exception as e:
        print(f"  [chat] degraded reply for {session['client_id']}: {type(e).__name__}: {e}")
        # agent.chat records the customer's message before calling the model,
        # so only add it if the failure happened before that.
        if not any(m["role"] == "user" for m in agent.history[before:]):
            agent.history.append({"role": "user", "text": message, "at": agent.now()})
        agent.history.append({"role": "assistant", "text": FRONT_DESK_LINE, "at": agent.now()})
        return {"reply": FRONT_DESK_LINE, "tools": [], "degraded": True}


@app.post("/api/voice")
def voice(session_id: str = Form(...), audio: UploadFile = File(...)):
    """Browser-recorded audio in -> transcript + agent reply out."""
    session = _owner_session(session_id)
    data = audio.file.read(MAX_VOICE_BYTES + 1)
    if len(data) > MAX_VOICE_BYTES:
        raise HTTPException(status_code=413, detail="Recording too long — keep a turn under a minute")
    mime = MIME_FIX.get(audio.content_type, audio.content_type) or "audio/wav"
    with one_turn_at_a_time(session):
        if turn_cap_reached(session):        # don't pay for a transcription past the cap
            return {"heard": "", **run_turn(session, "")}
        # Same bound as a typed turn: the transcript is re-sent every later turn.
        heard = session["agent"].llm.transcribe(data, mime_type=mime)[:MAX_CHAT_CHARS]
        if not heard:
            return {"heard": "", "reply": "", "tools": []}
        return {"heard": heard, **run_turn(session, heard)}


@app.post("/api/tts")
def speak(req: TTSRequest):
    """Reply text in -> mp3 speech out (voice auto-picked by script, see tts.py).

    Requires a live test-call session: without one this endpoint was a free,
    unlimited text-to-speech proxy for anyone who found the URL (audit M4).
    """
    _owner_session(req.session_id)
    clean = re.sub(r"[*_#`]", "", req.text)
    # Straight from the network into the response — no temp file round trip.
    try:
        audio = tts.synthesize_bytes(clean)
    except TTSTimeout:
        perf.event("timeout.tts")
        raise HTTPException(status_code=504, detail="Voice reply took too long — the text reply stands.")
    return Response(content=audio, media_type="audio/mpeg")


# ---------- dashboard data -------------------------------------------------------

def record_outcome(call: dict) -> dict:
    """Did this call book, or save a lead? Records written since the perf
    audit store the tools' real results; older ones fall back to the old
    transcript rule, which also counted FAILED attempts (audit M1)."""
    stored = call.get("outcome")
    if isinstance(stored, dict):
        return {"booked": bool(stored.get("booked")), "lead": bool(stored.get("lead"))}
    text = call.get("transcript", "")
    return {"booked": "book_appointment" in text, "lead": "save_lead" in text}


def _with_outcome(calls: list[dict]) -> list[dict]:
    # Copies: call records come from storage's shared cache (read-only).
    return [{**c, "outcome": record_outcome(c)} for c in calls]


def _stats_from(calls, bookings, leads) -> dict:
    """Stats from data already in hand — no second pass over the disk."""
    n_calls = len(calls)
    # Conversion = share of calls whose booking actually succeeded.
    booked_calls = sum(1 for c in calls if record_outcome(c)["booked"])
    return {
        "calls": n_calls,
        "minutes": round(sum(c["seconds"] for c in calls) / 60, 1),
        "bookings": sum(b["status"] == "confirmed" for b in bookings),
        "leads": len(leads),
        "conversion": round(100 * booked_calls / n_calls) if n_calls else 0,
        "proof": _proof_totals(calls),
    }


def _proof_totals(calls) -> dict:
    """Proof, not promises, across calls: claims made, claims a record
    backs, false claims stopped before the customer heard them, and calls
    the owner should look at. Calls saved before proof.py have no report."""
    reports = [c["proof"] for c in calls if isinstance(c.get("proof"), dict)]
    return {
        "claims": sum(p.get("claims", 0) for p in reports),
        "backed": sum(p.get("backed", 0) for p in reports),
        "caught": sum(len(p.get("caught") or []) for p in reports),
        "flagged_calls": sum(p.get("verdict") == "flagged" for p in reports),
    }


DASHBOARD_CALL_LIMIT = 200


def _phone_status(client_id: str) -> dict:
    cfg = storage.read_client_config(client_id) or {}
    number = cfg.get("twilio_number") or telephony.twilio_config()["number"] or None
    return {"connected": telephony.live_calls_enabled() and telephony.is_configured()
                         and bool(number),
            "number": number}


@app.get("/api/dashboard")
def dashboard(client_id: str, response: Response,
              x_client_key: str | None = Header(default=None, alias="X-Client-Key"),
              x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
              authorization: str | None = Header(default=None),
              if_none_match: str | None = Header(default=None)):
    """Everything one dashboard screen needs, in a single request.

    The page used to fire six authenticated requests (stats, calls, bookings,
    leads, billing, phone) that between them read the same files four times
    over. This reads each source once and serves an ETag, so the 20-second
    refresh costs an empty 304 whenever nothing has actually changed.
    """
    authorize_client(client_id, x_client_key, x_admin_key, authorization)
    version = storage.data_version(client_id)
    if if_none_match and if_none_match == version:
        return Response(status_code=304, headers={"ETag": version})

    with perf.span("dashboard.read"):
        calls = storage.read_call_logs(client_id)
        bookings = storage.read_bookings(client_id)
        leads = storage.leads_with_followups(client_id)
    response.headers["ETag"] = version
    return {
        # Stats count every call ever; the list ships only the recent ones so
        # the payload stays small for a busy client (transcripts are long).
        "stats": _stats_from(calls, bookings, leads),
        "calls": _with_outcome(calls[:DASHBOARD_CALL_LIMIT]),
        "bookings": list(reversed(bookings)),
        "leads": list(reversed(leads)),
        "billing": billing.status(client_id),
        "phone": _phone_status(client_id),
        "open_questions": len(storage.open_questions(client_id)),
        "callbacks": storage.read_callbacks(client_id, 30),
    }


class CallbackDoneRequest(BaseModel):
    client_id: str
    callback_id: int


@app.post("/api/callbacks/handled")
def callback_handled(req: CallbackDoneRequest,
                     x_client_key: str | None = Header(default=None, alias="X-Client-Key"),
                     x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
                     authorization: str | None = Header(default=None)):
    """The owner rang the customer themselves: Atithi must not call too."""
    authorize_client(req.client_id, x_client_key, x_admin_key, authorization)
    pending = {c["id"] for c in storage.read_callbacks(req.client_id, 200) if c["status"] == "pending"}
    if req.callback_id not in pending or not storage.mark_callback(
            req.callback_id, "dismissed", "handled by the team", client_id=req.client_id):
        raise HTTPException(status_code=404, detail="No pending callback with that id")
    return {"ok": True}


class CancelRequest(BaseModel):
    client_id: str
    booking_id: int


@app.post("/api/bookings/cancel")
def owner_cancel_booking(req: CancelRequest,
                         x_client_key: str | None = Header(default=None, alias="X-Client-Key"),
                         x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
                         authorization: str | None = Header(default=None)):
    """The owner cancels a booking from the Bookings page (the customer
    phoned, or the slot can't be kept). The slot becomes free again."""
    authorize_client(req.client_id, x_client_key, x_admin_key, authorization)
    done = storage.cancel_booking(req.client_id, booking_id=req.booking_id)
    if done is None:
        raise HTTPException(status_code=404, detail="That booking is not confirmed any more")
    notify.booking_event(req.client_id, "cancelled", done)
    return {"ok": True, "booking": done}


# ---------- website chat (public: the business's own customers) ------------------
#
# The business pastes <script src=".../widget.js" data-atithi="wk_..."> into its
# website. That adds a button which opens /chat in an iframe served from HERE,
# so every request below is same-origin and the owner's login code never
# appears on a public page. These endpoints need no login, so everything is
# capped: sessions per visitor IP, conversations per business, messages per
# business per day, message length.

WIDGET_SESSIONS_PER_BUSINESS = 30
WIDGET_MAX_CHARS = 500
WIDGET_DAILY_TURNS = 300                    # per business; `widget_daily_limit` overrides
WIDGET_NEW_SESSIONS_PER_IP = 10             # per WIDGET_IP_WINDOW
WIDGET_IP_WINDOW = dt.timedelta(minutes=10)
_widget_lock = threading.Lock()
_widget_ips: dict[str, list[dt.datetime]] = {}
_widget_turns: dict[tuple[str, str], int] = {}


def _widget_business(key: str) -> dict:
    """The business a public widget key belongs to, if its website chat is on."""
    for entry in storage.all_clients():
        cfg = entry["config"]
        if key and cfg.get("widget_key") and same_secret(key, cfg["widget_key"]):
            if not cfg.get("website_chat"):
                break
            return entry
    raise HTTPException(status_code=404, detail="This chat isn't available")


def _ip_allowed(ip: str) -> bool:
    now = dt.datetime.now()
    with _widget_lock:
        if len(_widget_ips) > 10_000:                       # bounded memory
            _widget_ips.clear()
        recent = [t for t in _widget_ips.get(ip, []) if now - t < WIDGET_IP_WINDOW]
        if len(recent) >= WIDGET_NEW_SESSIONS_PER_IP:
            _widget_ips[ip] = recent
            return False
        _widget_ips[ip] = recent + [now]
        return True


def _count_turn(client_id: str, limit: int) -> bool:
    """Count one website message; False once today's limit is reached."""
    day = dt.date.today().isoformat()
    with _widget_lock:
        for key in [k for k in _widget_turns if k[1] != day]:
            del _widget_turns[key]                          # yesterday's counts
        n = _widget_turns.get((client_id, day), 0)
        if n >= limit:
            return False
        _widget_turns[(client_id, day)] = n + 1
        return True


class PublicSessionRequest(BaseModel):
    key: str = Field(max_length=64)


class PublicChatRequest(BaseModel):
    session_id: str = Field(max_length=64)
    message: str = Field(max_length=WIDGET_MAX_CHARS)


@app.get("/chat", response_class=HTMLResponse)
def chat_page():
    return _page("chat.html")


@app.get("/widget.js")
def widget_js():
    return Response(content=_page("widget.js"), media_type="application/javascript",
                    headers={"Cache-Control": "public, max-age=3600"})


@app.post("/api/public/session")
def public_session(req: PublicSessionRequest, request: Request):
    entry = _widget_business(req.key)
    client_id, cfg = entry["client_id"], entry["config"]
    if not billing.client_active(client_id):
        raise HTTPException(status_code=404, detail="This chat isn't available")
    if not _ip_allowed(_client_ip(request)):
        raise HTTPException(status_code=429, detail="Too many chats started — please wait a few minutes.")
    agent = ReceptionistAgent(client_id)
    agent.set_channel("public")       # anyone on the internet: no look-ups, capped bookings
    session_id = _open_session(client_id, agent, "website", WIDGET_SESSIONS_PER_BUSINESS)
    return {"session_id": session_id, "business_name": cfg.get("business_name", "")}


@app.post("/api/public/chat")
def public_chat(req: PublicChatRequest):
    session = get_session(req.session_id)
    if session.get("channel") != "website":
        raise HTTPException(status_code=404, detail="Unknown or expired session")
    cfg = storage.read_client_config(session["client_id"]) or {}
    limit = int(cfg.get("widget_daily_limit") or WIDGET_DAILY_TURNS)
    with one_turn_at_a_time(session):
        if not _count_turn(session["client_id"], limit):
            phone = cfg.get("phone", "").strip()
            return {"reply": "We're getting a lot of messages right now — please call us"
                             + (f" on {phone}" if phone else "") + ". Thank you!", "busy": True}
        out = _chat_turn(session, req.message)
        return {"reply": out["reply"], **({"ended": True} if out.get("ended") else {})}


# ---------- questions the receptionist couldn't answer -----------------------

class QuestionAction(BaseModel):
    client_id: str
    question_id: int
    answer: str = Field(default="", max_length=1000)


@app.get("/api/questions")
def list_questions(client_id: str,
                   x_client_key: str | None = Header(default=None, alias="X-Client-Key"),
                   x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
                   authorization: str | None = Header(default=None)):
    authorize_client(client_id, x_client_key, x_admin_key, authorization)
    return storage.open_questions(client_id)


@app.post("/api/questions/answer")
def answer_question(req: QuestionAction,
                    x_client_key: str | None = Header(default=None, alias="X-Client-Key"),
                    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
                    authorization: str | None = Header(default=None)):
    """The owner answers once; it becomes an FAQ the receptionist uses from
    the next conversation on."""
    authorize_client(req.client_id, x_client_key, x_admin_key, authorization)
    answer = req.answer.strip()
    if not answer:
        raise HTTPException(status_code=422, detail="Type the answer first")
    current = storage.read_client_config(req.client_id)
    if current is None:
        raise HTTPException(status_code=404, detail=f"No client '{req.client_id}'")
    row = storage.close_question(req.client_id, req.question_id, answer)
    if row is None:
        raise HTTPException(status_code=404, detail="That question is no longer open")
    cfg = copy.deepcopy(current)           # the cached parse is shared: never mutate it
    cfg["faq"] = list(cfg.get("faq") or []) + [{"q": row["question"], "a": answer}]
    storage.write_client_config(req.client_id, cfg)
    return {"ok": True, "faq": {"q": row["question"], "a": answer}}


@app.post("/api/questions/dismiss")
def dismiss_question(req: QuestionAction,
                     x_client_key: str | None = Header(default=None, alias="X-Client-Key"),
                     x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
                     authorization: str | None = Header(default=None)):
    authorize_client(req.client_id, x_client_key, x_admin_key, authorization)
    if storage.close_question(req.client_id, req.question_id, None) is None:
        raise HTTPException(status_code=404, detail="That question is no longer open")
    return {"ok": True}


# ---------- lead follow-ups and exports ------------------------------------------

class LeadUpdate(BaseModel):
    client_id: str
    timestamp: str
    phone: str
    status: str
    note: str = Field(default="", max_length=500)
    callback_on: str = ""


@app.post("/api/leads/update")
def update_lead(req: LeadUpdate,
                x_client_key: str | None = Header(default=None, alias="X-Client-Key"),
                x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
                authorization: str | None = Header(default=None)):
    authorize_client(req.client_id, x_client_key, x_admin_key, authorization)
    try:
        found = storage.update_lead_followup(req.client_id, req.timestamp, req.phone, req.status,
                                             req.note.strip(), req.callback_on.strip())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if not found:
        raise HTTPException(status_code=404, detail="No such lead")
    return {"ok": True}


def _csv_safe(value):
    """A cell starting with = @ (or + - followed by more than a phone number)
    would run as a formula in Excel: prefix it so it stays text. Phone
    numbers like +91 98430 12345 are left alone."""
    v = str(value)
    if v[:1] in "=@" or (v[:1] in "+-" and not re.fullmatch(r"[+-][\d\s()-]*", v)):
        return "'" + v
    return value


_EXPORT_COLUMNS = {
    "bookings": ["date", "time", "name", "phone", "service", "status", "timestamp"],
    "leads": ["timestamp", "name", "phone", "interest", "note", "status", "callback_on",
              "followup_note", "has_booked"],
}


@app.get("/api/export/{kind}.csv")
def export_csv(kind: str, client_id: str,
               x_client_key: str | None = Header(default=None, alias="X-Client-Key"),
               x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
               authorization: str | None = Header(default=None)):
    """Download bookings or leads as a CSV the owner opens in Excel or Sheets."""
    authorize_client(client_id, x_client_key, x_admin_key, authorization)
    if kind not in _EXPORT_COLUMNS:
        raise HTTPException(status_code=404, detail="Unknown export")
    import csv
    import io
    rows = storage.read_bookings(client_id) if kind == "bookings" else storage.leads_with_followups(client_id)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=_EXPORT_COLUMNS[kind], extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: _csv_safe(v) for k, v in r.items()})
    # BOM so Excel reads ₹ and Indian-language names correctly.
    return Response(content="\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{client_id}-{kind}.csv"'})


@app.get("/api/stats")
def stats(client_id: str,
          x_client_key: str | None = Header(default=None, alias="X-Client-Key"),
          x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
          authorization: str | None = Header(default=None)):
    authorize_client(client_id, x_client_key, x_admin_key, authorization)
    return _stats_from(storage.read_call_logs(client_id),
                       storage.read_bookings(client_id),
                       storage.read_leads(client_id))


@app.get("/api/calls")
def calls(client_id: str,
          x_client_key: str | None = Header(default=None, alias="X-Client-Key"),
          x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
          authorization: str | None = Header(default=None)):
    authorize_client(client_id, x_client_key, x_admin_key, authorization)
    return _with_outcome(storage.read_call_logs(client_id))


@app.get("/api/bookings")
def bookings(client_id: str,
             x_client_key: str | None = Header(default=None, alias="X-Client-Key"),
             x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
             authorization: str | None = Header(default=None)):
    authorize_client(client_id, x_client_key, x_admin_key, authorization)
    return list(reversed(storage.read_bookings(client_id)))  # newest first


@app.get("/api/leads")
def leads(client_id: str,
          x_client_key: str | None = Header(default=None, alias="X-Client-Key"),
          x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
          authorization: str | None = Header(default=None)):
    authorize_client(client_id, x_client_key, x_admin_key, authorization)
    return list(reversed(storage.read_leads(client_id)))


@app.get("/api/billing_status")
def billing_status(client_id: str,
                   x_client_key: str | None = Header(default=None, alias="X-Client-Key"),
                   x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
                   authorization: str | None = Header(default=None)):
    """Plan info for the client dashboard's billing banner."""
    authorize_client(client_id, x_client_key, x_admin_key, authorization)
    return billing.status(client_id)


@app.post("/api/billing/renew")
def billing_renew(req: SessionRequest,
                  x_client_key: str | None = Header(default=None, alias="X-Client-Key"),
                  x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
                  authorization: str | None = Header(default=None)):
    """The owner clicked 'I've paid' — flag it for the admin to confirm."""
    authorize_client(req.client_id, x_client_key, x_admin_key, authorization)
    try:
        return billing.request_renewal(req.client_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/phone_status")
def phone_status(client_id: str,
                 x_client_key: str | None = Header(default=None, alias="X-Client-Key"),
                 x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
                 authorization: str | None = Header(default=None)):
    """Is the phone line live for this business? Shown on the client dashboard."""
    authorize_client(client_id, x_client_key, x_admin_key, authorization)
    return _phone_status(client_id)


@app.get("/api/transcript/{session_id}")
def transcript(session_id: str):
    agent = get_session(session_id)["agent"]
    return PlainTextResponse(
        agent.transcript_text(),
        headers={"Content-Disposition": "attachment; filename=atithi_transcript.txt"},
    )


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description="Atithi business portal")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1",
                        help="use 0.0.0.0 when hosting publicly / behind ngrok")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    url = f"http://127.0.0.1:{args.port}"
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    print(f"Atithi portal: {url}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
