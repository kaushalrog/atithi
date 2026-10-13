"""server.py — the VoxAgent business portal.

This is the page a BUSINESS OWNER uses (the clinic, salon, institute):
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
import datetime as dt
import os
import re
import secrets
import threading
import uuid
import webbrowser
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel

import auth
import billing
import llm as llm_module
import scheduling
import storage
import telephony
from agent import ReceptionistAgent
from tts import EdgeTTS

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="VoxAgent")
app.include_router(telephony.router)  # /twilio/voice + /twilio/stream (phone calls)
tts = EdgeTTS()


@app.on_event("startup")
def _warm_up():
    """Build the Gemini client while the server boots.

    It costs ~780 ms to construct. Doing it here means the first caller — who
    is on a live phone line — doesn't wait for it.
    """
    llm_module.warm_up()


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
# call log JSON on disk is the durable record. Idle sessions are purged so a
# long-running server doesn't accumulate dead agents.
sessions: dict[str, dict] = {}
SESSION_IDLE_LIMIT = dt.timedelta(hours=2)

MIME_FIX = {"audio/mpeg": "audio/mp3", "audio/x-wav": "audio/wav",
            "application/octet-stream": "audio/wav"}

WEEKDAYS = scheduling.WEEKDAYS   # one definition, shared with the scheduler

DEFAULT_FALLBACK = (
    "If you are unsure about anything, or the customer asks something not "
    "covered in the business information, say that the front desk will call "
    "them back with the exact details. NEVER guess or invent prices, offers, "
    "or medical advice."
)


# ---------- request models ----------------------------------------------------

class SessionRequest(BaseModel):
    client_id: str = "demo_clinic"


class ChatRequest(BaseModel):
    session_id: str
    message: str


class TTSRequest(BaseModel):
    text: str


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


def client_access_key(client_id: str) -> str | None:
    cfg = storage.read_client_config(client_id)
    return cfg.get("access_key") if cfg else None


def authorize_client(client_id: str, client_key: str | None, admin_key: str | None,
                     authorization: str | None = None):
    user = bearer_user(authorization)
    if user and (user["role"] == "admin" or user["client_id"] == client_id):
        return
    admin_password = os.getenv("ADMIN_PASSWORD", "")
    if admin_password and admin_key == admin_password:
        return
    expected = client_access_key(client_id)
    if expected and client_key == expected:
        return
    raise HTTPException(status_code=401, detail="Not authorized for this business")


# ---------- helpers ------------------------------------------------------------

def get_session(session_id: str) -> dict:
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown or expired session")
    return session


def purge_idle_sessions():
    now = dt.datetime.now()
    for sid in [s for s, v in sessions.items()
                if now - v["last_activity"] > SESSION_IDLE_LIMIT]:
        del sessions[sid]


def run_turn(session: dict, message: str) -> dict:
    """One customer turn; also reports which tools fired so the UI can show them."""
    agent = session["agent"]
    before = len(agent.history)
    reply = agent.chat(message)
    tools = []
    for msg in agent.history[before:]:
        if msg["role"] == "assistant" and msg.get("tool_calls"):
            for call in msg["tool_calls"]:
                tools.append({"name": call["name"], "args": call["args"]})
    session["last_activity"] = dt.datetime.now()
    storage.log_call_from_agent(agent, "web-test", session["started"],
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
    user = bearer_user(authorization)
    if user and user["role"] == "admin":
        return
    admin_password = os.getenv("ADMIN_PASSWORD", "")
    if not admin_password:
        raise HTTPException(status_code=503, detail="Set ADMIN_PASSWORD in .env to use the admin console")
    if x_admin_key != admin_password:
        raise HTTPException(status_code=401, detail="Admin access only")


@app.post("/api/admin/login")
def admin_login(req: AdminLoginRequest):
    require_admin(x_admin_key=req.password)
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
        n_bookings = len(storage.read_bookings(client_id))
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
        "booked": "book_appointment" in c["transcript"],
        "lead": "save_lead" in c["transcript"],
    } for c in all_calls[:12]]
    return {"totals": totals, "clients": clients, "recent_calls": recent,
            "password_resets": auth.pending_resets(),
            "twilio_configured": telephony.is_configured(),
            "status": {
                "gemini_key": bool(os.getenv("GEMINI_API_KEY")),
                "twilio": telephony.is_configured(),
                "sheets": bool(os.getenv("SHEET_ID")),
            }}


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
    try:
        return _with_business_name(auth.login(req.email, req.password))
    except PermissionError as e:
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
                        "ask the VoxAgent team for it, then enter it below.")}


@app.post("/api/auth/reset")
def auth_reset(req: ResetRequest):
    try:
        return _with_business_name(auth.reset_password(req.email, req.code, req.new_password))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))


@app.post("/api/portal/login")
def portal_login(req: PortalLoginRequest):
    """A business owner logs in with their business code."""
    code = req.access_key.strip()
    if code:
        for entry in storage.all_clients():
            cfg = entry["config"]
            if cfg.get("access_key") and cfg["access_key"] == code:
                return {"client_id": entry["client_id"],
                        "business_name": cfg.get("business_name", entry["client_id"])}
    raise HTTPException(status_code=401, detail="That code doesn't match any business")


@app.post("/api/business")
def create_business(req: BusinessRequest,
                    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
                    authorization: str | None = Header(default=None)):
    # Admin can create any number of businesses; a signed-up owner exactly one
    # (their own — it gets linked to their account and starts a free trial).
    user = bearer_user(authorization)
    is_admin = (user and user["role"] == "admin") or (
        os.getenv("ADMIN_PASSWORD", "") and x_admin_key == os.getenv("ADMIN_PASSWORD"))
    if not is_admin:
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
        "access_key": "VX-" + secrets.token_hex(3).upper(),
        "business_name": req.business_name.strip(),
        "address": req.address.strip(),
        "phone": req.phone.strip(),
        "timings": req.timings.strip(),
        "services": [{"name": s.name.strip(), "price": s.price.strip()} for s in services],
        "faq": [{"q": f.q.strip(), "a": f.a.strip()} for f in req.faq if f.q.strip()],
        "policies": [p.strip() for p in req.policies if p.strip()],
        "fallback": req.fallback.strip() or DEFAULT_FALLBACK,
        # Every new business starts on a free trial; after that the owner
        # pays and the admin activates (see billing.py).
        "billing": billing.new_trial(),
        # Store the RULE, not dated slots: dated slots silently expired and
        # left the agent unable to book anything (see scheduling.py).
        "schedule": scheduling.schedule_from_form(
            req.slot_days, req.slot_ranges, req.slot_gap_min
        ),
    }
    # Through storage so the config caches invalidate with the write.
    storage.write_client_config(client_id, config)
    if not is_admin:
        auth.attach_client(user["email"], client_id)
    return {"client_id": client_id, "business_name": config["business_name"],
            "access_key": config["access_key"]}


# ---------- talking to the agent (the Test-agent widget) ------------------------

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
    session_id = uuid.uuid4().hex
    now = dt.datetime.now()
    sessions[session_id] = {
        "agent": agent,
        "client_id": req.client_id,
        "call_id": now.strftime("%Y%m%d_%H%M%S_") + session_id[:6],
        "started": now,
        "last_activity": now,
    }
    return {"session_id": session_id, "business_name": agent.config["business_name"]}


FRONT_DESK_LINE = ("Sorry, our line is very busy right now — the front desk "
                   "will call you back shortly.")


@app.post("/api/chat")
def chat(req: ChatRequest):
    session = get_session(req.session_id)
    # A model outage or rate limit must never show the customer an error page.
    try:
        return run_turn(session, req.message)
    except Exception as e:
        print(f"  [chat] degraded reply for {session['client_id']}: {type(e).__name__}: {e}")
        session["agent"].history.append({"role": "user", "text": req.message})
        session["agent"].history.append({"role": "assistant", "text": FRONT_DESK_LINE})
        return {"reply": FRONT_DESK_LINE, "tools": [], "degraded": True}


@app.post("/api/voice")
def voice(session_id: str = Form(...), audio: UploadFile = File(...)):
    """Browser-recorded audio in -> transcript + agent reply out."""
    session = get_session(session_id)
    mime = MIME_FIX.get(audio.content_type, audio.content_type) or "audio/wav"
    heard = session["agent"].llm.transcribe(audio.file.read(), mime_type=mime)
    if not heard:
        return {"heard": "", "reply": "", "tools": []}
    return {"heard": heard, **run_turn(session, heard)}


@app.post("/api/tts")
def speak(req: TTSRequest):
    """Reply text in -> mp3 speech out (voice auto-picked by script, see tts.py)."""
    clean = re.sub(r"[*_#`]", "", req.text)
    # Straight from the network into the response — no temp file round trip.
    return Response(content=tts.synthesize_bytes(clean), media_type="audio/mpeg")


# ---------- dashboard data -------------------------------------------------------

def _stats_from(calls, bookings, leads) -> dict:
    """Stats from data already in hand — no second pass over the disk."""
    n_calls = len(calls)
    # Conversion = share of calls that produced a booking. Each call's transcript
    # records its tool calls, so a booking made during the call is visible there.
    booked_calls = sum(1 for c in calls if "book_appointment" in c.get("transcript", ""))
    return {
        "calls": n_calls,
        "minutes": round(sum(c["seconds"] for c in calls) / 60, 1),
        "bookings": len(bookings),
        "leads": len(leads),
        "conversion": round(100 * booked_calls / n_calls) if n_calls else 0,
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

    calls = storage.read_call_logs(client_id)
    bookings = storage.read_bookings(client_id)
    leads = storage.read_leads(client_id)
    response.headers["ETag"] = version
    return {
        # Stats count every call ever; the list ships only the recent ones so
        # the payload stays small for a busy client (transcripts are long).
        "stats": _stats_from(calls, bookings, leads),
        "calls": calls[:DASHBOARD_CALL_LIMIT],
        "bookings": list(reversed(bookings)),
        "leads": list(reversed(leads)),
        "billing": billing.status(client_id),
        "phone": _phone_status(client_id),
    }


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
    return storage.read_call_logs(client_id)


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
        headers={"Content-Disposition": "attachment; filename=voxagent_transcript.txt"},
    )


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description="VoxAgent business portal")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1",
                        help="use 0.0.0.0 when hosting publicly / behind ngrok")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    url = f"http://127.0.0.1:{args.port}"
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    print(f"VoxAgent portal: {url}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
