"""Phase 0 audit reproductions. Offline: FakeLLM, temp storage, temp auth DB.
Run from the repo root:  python docs/audit_repro.py
(never touches project data files: storage + auth DB point at a temp dir)
Each check prints REPRODUCED / NOT REPRODUCED with the observed evidence."""
import asyncio, datetime as dt, os, shutil, sys, tempfile
from pathlib import Path

import dotenv

# The project's modules call load_dotenv() at import; a real .env would put
# SHEET_ID/keys back after we clear them below. Disable it before any import.
dotenv.load_dotenv = lambda *a, **k: False

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for k in ("GEMINI_API_KEY", "SHEET_ID", "TWILIO_AUTH_TOKEN", "ADMIN_PASSWORD", "ADMIN_EMAIL"):
    os.environ.pop(k, None)
os.environ["VOXAGENT_ENV"] = "test"   # storage refuses real-data writes (post-Phase-0.5 code)

import storage, auth, scheduling  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="vox_audit_"))
storage.BOOKINGS_CSV = TMP / "bookings.csv"
storage.BOOKINGS_DB = TMP / "bookings.db"   # ignored by pre-Phase-0.5 code
storage.LEADS_CSV = TMP / "leads.csv"
storage.CALLS_DIR = TMP / "calls"
auth.DB_FILE = TMP / "voxagent.db"
# Client configs: a temp COPY, so nothing here can write the real clients/.
shutil.copytree(storage.CLIENTS_DIR, TMP / "clients")
storage.CLIENTS_DIR = TMP / "clients"
storage.clear_caches()

from agent import ReceptionistAgent  # noqa: E402


class FakeLLM:
    def __init__(self, script=()):
        self.script = list(script)
    def send(self, messages, tools=None):
        return self.script.pop(0) if self.script else {"text": "ok", "tool_calls": []}
    def transcribe(self, *a, **k):
        return ""


def reset_bookings():
    """Fresh, empty booking storage for the next scenario (CSV era and DB era)."""
    for p in list(TMP.glob("*.csv")) + list(TMP.glob("bookings.db*")):
        p.unlink()
    if hasattr(storage, "_db_prepared"):
        storage._db_prepared.clear()
        storage._db_local.conn = None
    storage.clear_caches()


def report(name, reproduced, evidence):
    print(f"[{'REPRODUCED' if reproduced else 'NOT REPRODUCED'}] {name}\n    {evidence}")


def first_open():
    cfg = storage.read_client_config("demo_clinic")
    slots = scheduling.available_slots(cfg, set())
    d = next(d for d in sorted(slots) if slots[d])
    return d, slots[d][0]


# R1: two concurrent conversations can book the same slot.
storage.clear_caches()
d, t = first_open()
a1 = ReceptionistAgent("demo_clinic", llm=FakeLLM())
a2 = ReceptionistAgent("demo_clinic", llm=FakeLLM())   # both built before either books
r1 = a1._book_appointment("Asha", "9876543210", "Cleaning", d, t)["status"]
r2 = a2._book_appointment("Bala", "9876543211", "Cleaning", d, t)["status"]
rows = [r for r in storage.read_bookings("demo_clinic") if (r["date"], r["time"]) == (d, t)]
report("R1 double-booking across concurrent conversations", r1 == r2 == "confirmed" and len(rows) == 2,
       f"agent1={r1}, agent2={r2}, confirmed rows for {d} {t}: {len(rows)}")

# R2: when Sheets is the booking store, availability and dashboard never see the booking.
reset_bookings()
if hasattr(storage, "_save_to_google_sheet"):                 # pre-Phase-0.5 code
    orig = ("_save_to_google_sheet", storage._save_to_google_sheet)
    storage._save_to_google_sheet = lambda row: "Google Sheet"   # simulate a working Sheet
else:                                                            # Sheets is now a copy
    class _FakeSheet:                     # a readable, empty Sheet (nothing to migrate)
        def append_row(self, row): pass
        def get_all_records(self): return []
    orig = ("_sheet_handle", storage._sheet_handle)
    storage._sheet_handle = lambda *a: _FakeSheet()
    _real_in_test_mode = storage.in_test_mode
    storage.in_test_mode = lambda: False   # lift test mode for the mirror only; restored below
    os.environ["GOOGLE_SHEETS_CREDENTIALS_PATH"] = __file__
    os.environ["SHEET_ID"] = "fake"
a = ReceptionistAgent("demo_clinic", llm=FakeLLM())
res = a._book_appointment("Asha", "9876543210", "Cleaning", d, t)
fresh = ReceptionistAgent("demo_clinic", llm=FakeLLM())
still_offered = t in fresh._check_availability(d)["available_slots"]
report("R2 Sheets bookings invisible to availability + dashboard",
       "Google Sheet" in res.get("saved_to", "") and still_offered
       and storage.read_bookings("demo_clinic") == [],
       f"saved_to={res['saved_to']!r}; new conversation still offers {d} {t}: {still_offered}; "
       f"dashboard bookings={len(storage.read_bookings('demo_clinic'))}")
setattr(storage, *orig)
if "in_test_mode" in vars(storage):
    storage.in_test_mode = _real_in_test_mode     # re-arm the real-data write guard
os.environ.pop("SHEET_ID", None)

# R3: conversion metric counts FAILED booking attempts as conversions.
import server  # noqa: E402
reset_bookings()
a = ReceptionistAgent("demo_clinic", llm=FakeLLM([
    {"text": None, "tool_calls": [{"name": "book_appointment", "args": {
        "customer_name": "X", "phone": "123", "service": "Cleaning", "date": d, "time": t}}]},
    {"text": "Could you confirm your 10-digit number?", "tool_calls": []},
]))
a.chat("book me")
storage.log_call_from_agent(a, "web-test", dt.datetime.now(), call_id="r3")
stats = server._stats_from(storage.read_call_logs("demo_clinic"),
                           storage.read_bookings("demo_clinic"), storage.read_leads("demo_clinic"))
report("R3 conversion counts failed booking attempts", stats["conversion"] == 100 and stats["bookings"] == 0,
       f"stats={stats}")

# R4: phone/live channel never records tool calls -> phone bookings invisible to conversion.
import telephony  # noqa: E402
import shutil
shutil.rmtree(storage.CALLS_DIR, ignore_errors=True)
reset_bookings()


class FakeLive:
    def __init__(self, evs): self.evs = evs; self.results = []
    async def send_tool_results(self, r): self.results.append(r)
    async def events(self):
        for e in self.evs:
            yield e


agent = ReceptionistAgent("demo_clinic", llm=FakeLLM())
live = FakeLive([
    {"type": "user_text", "text": "Book cleaning, Asha 9876543210"},
    {"type": "tool_calls", "calls": [{"id": "1", "name": "book_appointment", "args": {
        "customer_name": "Asha", "phone": "9876543210", "service": "Cleaning", "date": d, "time": t}}]},
    {"type": "agent_text", "text": "Booked!"}, {"type": "turn_complete"}])
async def _noop(m): pass
bridge = telephony.TwilioBridge(agent, live, _noop, caller="+919876543210")
asyncio.run(bridge.pump_gemini())
bridge.finish()
stats = server._stats_from(storage.read_call_logs("demo_clinic"),
                           storage.read_bookings("demo_clinic"), storage.read_leads("demo_clinic"))
log = storage.read_call_logs("demo_clinic")[0]
report("R4 phone-call bookings missing from transcript + conversion",
       stats["bookings"] == 1 and stats["conversion"] == 0,
       f"bookings={stats['bookings']}, conversion={stats['conversion']}%, turns={log['turns']} "
       f"(caller-id line counted as a customer turn), 'book_appointment' in transcript: "
       f"{'book_appointment' in log['transcript']}")

# R5..R8 via HTTP.
from fastapi.testclient import TestClient  # noqa: E402
c = TestClient(server.app)
server.tts.synthesize_bytes = lambda text: b"ID3" + str(len(text)).encode()
r = c.post("/api/tts", json={"text": "x" * 200_000})
report("R5 /api/tts needs no auth and has no size bound", r.status_code == 200,
       f"unauthenticated 200 KB request -> HTTP {r.status_code}")

# R6 + R7: admin endpoints and a 2 MB chat message
server.ReceptionistAgent = lambda cid: ReceptionistAgent(cid, llm=FakeLLM())
c500 = TestClient(server.app, raise_server_exceptions=False)
STRONG = "audit-admin-password-ok"   # passes any password policy, so R6a/R7 test their own bug
os.environ["ADMIN_PASSWORD"] = STRONG
r = c500.post("/api/admin/login", json={"password": STRONG})
report("R6a /api/admin/login crashes for every input", r.status_code == 500,
       f"POST /api/admin/login (correct password) -> HTTP {r.status_code}")
os.environ["ADMIN_PASSWORD"] = "choose_a_strong_password"
r = c.get("/api/admin/overview", headers={"X-Admin-Key": "choose_a_strong_password"})
report("R6b .env.example placeholder admin password is accepted verbatim", r.status_code == 200,
       f"GET /api/admin/overview with the placeholder -> HTTP {r.status_code}; "
       f"response exposes access_keys: {'access_key' in r.text}")
os.environ["ADMIN_PASSWORD"] = STRONG
sid = c.post("/api/session", json={"client_id": "demo_clinic"},
             headers={"X-Admin-Key": STRONG}).json()["session_id"]
r = c.post("/api/chat", json={"session_id": sid, "message": "A" * 2_000_000})
report("R7 /api/chat accepts unbounded message size", r.status_code == 200,
       f"2 MB message -> HTTP {r.status_code}; it would be forwarded to the LLM on every later turn")

# R8 + R9 run with the phone line FULLY ENABLED and configured — the attacker's
# best case. (On post-Phase-0.5 code, live calls are off by default; testing
# only that default would hide whether the gates themselves work.)
from twilio.request_validator import RequestValidator  # noqa: E402
os.environ.update({"ENABLE_LIVE_CALLS": "true", "TWILIO_AUTH_TOKEN": "audit-token",
                   "PUBLIC_BASE_URL": "https://example.test"})


def signed_post(path, data):
    """POST exactly as Twilio would: correctly signed with the auth token."""
    req = c.build_request("POST", path, data=data)
    url = str(req.url).replace("http://", "https://", 1)
    req.headers["X-Twilio-Signature"] = RequestValidator("audit-token").compute_signature(url, data)
    return c.send(req)


# R8: TwiML built by string interpolation -> XML injection.
r = signed_post('/twilio/voice?client_id=demo_clinic"/><Dial>+15550000000</Dial><X a="',
                {"To": "+1", "From": "+2", "CallSid": "CA8"})
report("R8a TwiML injection through client_id (signed request)",
       "<Dial>+15550000000</Dial>" in r.text,
       f"injected <Dial> present: {'<Dial>' in r.text} (unknown client fails billing check first)")
r = signed_post("/twilio/voice", {"To": "+1", "CallSid": "CA8", "From":
                '+2"/></Stream></Connect><Dial>+15550000000</Dial><Connect><Stream url="x">'
                '<Parameter name="a" value="'})
report("R8b TwiML injection through unescaped From (signed request)",
       "<Dial>+15550000000</Dial>" in r.text,
       f"HTTP {r.status_code}; injected <Dial> present: {'<Dial>' in r.text}")

# R9: the phone websocket has no auth and skips the billing check done in /twilio/voice.
cfg = dict(storage.read_client_config("demo_clinic"))
import billing  # noqa: E402
expired_dir = TMP / "clients"   # the temp copy made at the top
import yaml  # noqa: E402
cfg["billing"] = {"plan": "trial", "paid_until": "2000-01-01"}
(expired_dir / "expired_biz.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
storage.CLIENTS_DIR = expired_dir
storage.clear_caches()
created = []


class SpyLive:
    def __init__(self): created.append(self)
    async def connect(self, *a): pass
    async def close(self): pass
    async def send_text(self, t): pass
    async def send_audio(self, b): pass
    async def events(self):
        if False:
            yield {}


import llm  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402
llm.GeminiLive = SpyLive
telephony.ReceptionistAgent = lambda cid: ReceptionistAgent(cid, llm=FakeLLM())
outcome = "accepted"
try:   # an attacker: no Twilio signature, no ticket, an expired business
    with c.websocket_connect("/twilio/stream") as ws:
        ws.send_json({"event": "start", "start": {"streamSid": "MZ1", "callSid": "CA9",
                      "customParameters": {"client_id": "expired_biz"}}})
        ws.send_json({"event": "stop"})
except WebSocketDisconnect as e:
    outcome = f"rejected (close code {e.code})"
report("R9 /twilio/stream opens a paid model session for an EXPIRED client, unauthenticated",
       billing.client_active("expired_biz") is False and len(created) == 1,
       f"client_active=False, connection {outcome}, Gemini Live sessions opened: {len(created)}")
print(f"\n(temp dir: {TMP})")
