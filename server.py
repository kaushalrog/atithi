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
import re
import tempfile
import threading
import uuid
import webbrowser
from pathlib import Path

import yaml
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel

import storage
from agent import ReceptionistAgent
from tts import EdgeTTS

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="VoxAgent")
tts = EdgeTTS()

# One test-call session = one agent + one call-log entry. In memory only; the
# call log JSON on disk is the durable record. Idle sessions are purged so a
# long-running server doesn't accumulate dead agents.
sessions: dict[str, dict] = {}
SESSION_IDLE_LIMIT = dt.timedelta(hours=2)

MIME_FIX = {"audio/mpeg": "audio/mp3", "audio/x-wav": "audio/wav",
            "application/octet-stream": "audio/wav"}

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

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
    """Turn 'open Mon-Sat, 10-1 and 4-8, every 30 min' into concrete slots for
    the next 7 days. Static demo data — a real calendar replaces this at a
    later stage, behind the same check_availability tool."""
    slots = {}
    today = dt.date.today()
    for i in range(7):
        day = today + dt.timedelta(days=i)
        times = []
        if WEEKDAYS[day.weekday()] in days:
            for start, end in ranges:
                if not start or not end:
                    continue
                t = dt.datetime.combine(day, dt.time.fromisoformat(start))
                stop = dt.datetime.combine(day, dt.time.fromisoformat(end))
                while t < stop:
                    times.append(t.strftime("%H:%M"))
                    t += dt.timedelta(minutes=max(gap_min, 5))
        slots[day.isoformat()] = times
    return slots


# ---------- pages & business management ----------------------------------------

@app.get("/", response_class=HTMLResponse)
def index():
    return (BASE_DIR / "web" / "index.html").read_text(encoding="utf-8")


@app.get("/api/clients")
def list_clients():
    out = []
    for path in sorted((BASE_DIR / "clients").glob("*.yaml")):
        with open(path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        out.append({"client_id": path.stem,
                    "business_name": cfg.get("business_name", path.stem)})
    return out


@app.post("/api/business")
def create_business(req: BusinessRequest):
    services = [s for s in req.services if s.name.strip()]
    if not req.business_name.strip() or not services:
        raise HTTPException(status_code=422, detail="Business name and at least one service are required")

    client_id = re.sub(r"[^a-z0-9]+", "_", req.business_name.lower()).strip("_")[:40]
    path = BASE_DIR / "clients" / f"{client_id}.yaml"
    if path.exists():
        raise HTTPException(status_code=409, detail=f"A business '{client_id}' already exists")

    config = {
        "client_id": client_id,
        "business_name": req.business_name.strip(),
        "address": req.address.strip(),
        "phone": req.phone.strip(),
        "timings": req.timings.strip(),
        "services": [{"name": s.name.strip(), "price": s.price.strip()} for s in services],
        "faq": [{"q": f.q.strip(), "a": f.a.strip()} for f in req.faq if f.q.strip()],
        "policies": [p.strip() for p in req.policies if p.strip()],
        "fallback": req.fallback.strip() or DEFAULT_FALLBACK,
        "slots": generate_slots(req.slot_days, req.slot_ranges, req.slot_gap_min),
    }
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)
    return {"client_id": client_id, "business_name": config["business_name"]}


# ---------- talking to the agent (the Test-agent widget) ------------------------

@app.post("/api/session")
def create_session(req: SessionRequest):
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


@app.post("/api/chat")
def chat(req: ChatRequest):
    return run_turn(get_session(req.session_id), req.message)


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
    out_path = Path(tempfile.gettempdir()) / f"voxagent_web_{uuid.uuid4().hex}.mp3"
    try:
        tts.synthesize(clean, str(out_path))
        return Response(content=out_path.read_bytes(), media_type="audio/mpeg")
    finally:
        out_path.unlink(missing_ok=True)


# ---------- dashboard data -------------------------------------------------------

@app.get("/api/stats")
def stats(client_id: str):
    calls = storage.read_call_logs(client_id)
    n_calls = len(calls)
    # Conversion = share of calls that produced a booking. Each call's transcript
    # records its tool calls, so a booking made during the call is visible there.
    booked_calls = sum(1 for c in calls if "book_appointment" in c["transcript"])
    return {
        "calls": n_calls,
        "minutes": round(sum(c["seconds"] for c in calls) / 60, 1),
        "bookings": len(storage.read_bookings(client_id)),
        "leads": len(storage.read_leads(client_id)),
        "conversion": round(100 * booked_calls / n_calls) if n_calls else 0,
    }


@app.get("/api/calls")
def calls(client_id: str):
    return storage.read_call_logs(client_id)


@app.get("/api/bookings")
def bookings(client_id: str):
    return list(reversed(storage.read_bookings(client_id)))  # newest first


@app.get("/api/leads")
def leads(client_id: str):
    return list(reversed(storage.read_leads(client_id)))


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
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    url = f"http://127.0.0.1:{args.port}"
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    print(f"VoxAgent portal: {url}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
