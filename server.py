"""server.py — the receptionist as a web page.

WHY this is thin (architecture principle 3): the browser is just another
channel, like the terminal (main.py) and the mic loop (voice_main.py). Every
endpoint here only translates HTTP <-> ReceptionistAgent calls; zero business
logic lives in this file. FastAPI was chosen because it's the same stack as
Stage 3's telephony webhooks will need, so this file grows into that role.

Run:  python server.py            (opens http://127.0.0.1:8765 in your browser)
      python server.py --no-browser --port 8765
"""

import argparse
import csv
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

from agent import ReceptionistAgent
from tts import EdgeTTS

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="VoxAgent")
tts = EdgeTTS()

# One browser tab = one session = one ReceptionistAgent (in memory only —
# restart the server and conversations reset; bookings survive on disk).
sessions: dict[str, ReceptionistAgent] = {}

# Browsers name the upload mime differently than Gemini expects.
MIME_FIX = {"audio/mpeg": "audio/mp3", "audio/x-wav": "audio/wav",
            "application/octet-stream": "audio/wav"}


class SessionRequest(BaseModel):
    client_id: str = "demo_clinic"


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ResetRequest(BaseModel):
    session_id: str


class TTSRequest(BaseModel):
    text: str


def get_agent(session_id: str) -> ReceptionistAgent:
    agent = sessions.get(session_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Unknown or expired session")
    return agent


def run_turn(agent: ReceptionistAgent, message: str) -> dict:
    """One customer turn; also reports which tools fired so the UI can show them."""
    before = len(agent.history)
    reply = agent.chat(message)
    tools = []
    for msg in agent.history[before:]:
        if msg["role"] == "assistant" and msg.get("tool_calls"):
            for call in msg["tool_calls"]:
                tools.append({"name": call["name"], "args": call["args"]})
    return {"reply": reply, "tools": tools}


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


@app.post("/api/session")
def create_session(req: SessionRequest):
    try:
        agent = ReceptionistAgent(req.client_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"No client '{req.client_id}'")
    session_id = uuid.uuid4().hex
    sessions[session_id] = agent
    cfg = agent.config
    return {
        "session_id": session_id,
        "business_name": cfg["business_name"],
        "address": cfg["address"],
        "timings": cfg["timings"],
        "phone": cfg.get("phone", ""),
        "services": cfg["services"],
    }


@app.post("/api/chat")
def chat(req: ChatRequest):
    return run_turn(get_agent(req.session_id), req.message)


@app.post("/api/voice")
def voice(session_id: str = Form(...), audio: UploadFile = File(...)):
    """Browser-recorded audio in -> transcript + agent reply out."""
    agent = get_agent(session_id)
    mime = MIME_FIX.get(audio.content_type, audio.content_type) or "audio/wav"
    heard = agent.llm.transcribe(audio.file.read(), mime_type=mime)
    if not heard:
        return {"heard": "", "reply": "", "tools": []}
    return {"heard": heard, **run_turn(agent, heard)}


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


@app.get("/api/bookings")
def bookings():
    path = BASE_DIR / "bookings.csv"
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return list(reversed(rows))  # newest first


@app.post("/api/reset")
def reset(req: ResetRequest):
    get_agent(req.session_id).reset()
    return {"ok": True}


@app.get("/api/transcript/{session_id}")
def transcript(session_id: str):
    agent = get_agent(session_id)
    return PlainTextResponse(
        agent.transcript_text(),
        headers={"Content-Disposition": "attachment; filename=voxagent_transcript.txt"},
    )


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description="VoxAgent web frontend")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    url = f"http://127.0.0.1:{args.port}"
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    print(f"VoxAgent web UI: {url}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
