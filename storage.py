"""storage.py — every byte VoxAgent persists, in one file.

WHY this layer exists: agent.py used to write CSVs and talk to Google Sheets
itself, and server.py had its own call-log code. Persistence scattered across
files means every new feature reinvents it. Now the rule is simple: anything
that touches disk (or Sheets) lives here, and nothing else knows file paths.
When real scale demands a database, THIS is the only file that changes.

What we store:
    bookings  -> Google Sheet if configured, bookings.csv fallback
    leads     -> leads.csv        (callers who didn't book — follow-up gold)
    calls     -> calls/<client_id>/<call_id>.json  (one file per conversation)
"""

import csv
import datetime as dt
import json
import os
import threading
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
BOOKINGS_CSV = BASE_DIR / "bookings.csv"
LEADS_CSV = BASE_DIR / "leads.csv"
CALLS_DIR = BASE_DIR / "calls"

BOOKING_HEADER = [
    "timestamp", "client_id", "name", "phone", "service", "date", "time", "status",
]
LEAD_HEADER = ["timestamp", "client_id", "name", "phone", "interest", "note"]

# The web server handles requests on multiple threads; two simultaneous writes
# to the same CSV would interleave rows. One lock keeps appends atomic.
_write_lock = threading.Lock()


# ---- bookings ------------------------------------------------------------------

def save_booking(row: list) -> str:
    """Persist one booking row. Returns a human-readable 'where it went'."""
    where = _save_to_google_sheet(row)
    if where is None:
        _append_csv(BOOKINGS_CSV, BOOKING_HEADER, row)
        where = "bookings.csv (local fallback)"
    return where


def read_bookings(client_id: str) -> list[dict]:
    return [r for r in _read_csv(BOOKINGS_CSV) if r.get("client_id") == client_id]


def _save_to_google_sheet(row: list) -> str | None:
    """Returns 'Google Sheet' on success, None to trigger the CSV fallback.

    WHY the fallback: a live demo must never die because of a missing
    credentials file or a flaky network. Losing the booking is the only
    unacceptable failure.
    """
    creds_path = os.getenv("GOOGLE_SHEETS_CREDENTIALS_PATH", "")
    sheet_id = os.getenv("SHEET_ID", "")
    if not creds_path or not sheet_id:
        print("  [warning] Google Sheets not configured (.env) — using bookings.csv.")
        return None
    if not Path(creds_path).is_absolute():
        creds_path = str(BASE_DIR / creds_path)
    if not os.path.exists(creds_path):
        print(f"  [warning] {creds_path} not found — using bookings.csv.")
        return None
    try:
        import gspread  # imported here so everything runs without gspread installed

        gc = gspread.service_account(filename=creds_path)
        worksheet = gc.open_by_key(sheet_id).sheet1
        if not worksheet.get_values("A1:H1"):
            worksheet.append_row(BOOKING_HEADER)
        worksheet.append_row(row)
        return "Google Sheet"
    except Exception as e:
        print(f"  [warning] Google Sheets failed ({e}) — using bookings.csv.")
        return None


# ---- leads ---------------------------------------------------------------------

def save_lead(client_id: str, name: str, phone: str, interest: str, note: str = ""):
    row = [
        dt.datetime.now().isoformat(timespec="seconds"),
        client_id, name, phone, interest, note,
    ]
    _append_csv(LEADS_CSV, LEAD_HEADER, row)


def read_leads(client_id: str) -> list[dict]:
    return [r for r in _read_csv(LEADS_CSV) if r.get("client_id") == client_id]


# ---- call logs -----------------------------------------------------------------

def log_call_from_agent(agent, channel: str, started: dt.datetime,
                        call_id: str | None = None):
    """Write (or rewrite) the call record for one conversation.

    Works for every channel: the web server calls this after each turn with a
    stable call_id; the terminal/voice/live wrappers call it once on exit.
    Conversations with zero customer turns are not calls, so nothing is logged.
    """
    turns = sum(1 for m in agent.history if m["role"] == "user")
    if turns == 0:
        return
    if call_id is None:
        call_id = started.strftime("%Y%m%d_%H%M%S_") + channel
    now = dt.datetime.now()
    record = {
        "call_id": call_id,
        "client_id": agent.client_id,
        "channel": channel,
        "started": started.isoformat(timespec="seconds"),
        "ended": now.isoformat(timespec="seconds"),
        "seconds": int((now - started).total_seconds()),
        "turns": turns,
        "transcript": agent.transcript_text(),
    }
    folder = CALLS_DIR / agent.client_id
    with _write_lock:
        folder.mkdir(parents=True, exist_ok=True)
        with open(folder / f"{call_id}.json", "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=1)


def read_call_logs(client_id: str) -> list[dict]:
    folder = CALLS_DIR / client_id
    if not folder.exists():
        return []
    records = []
    for path in folder.glob("*.json"):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue  # one corrupt file must not break the dashboard
    return sorted(records, key=lambda r: r["started"], reverse=True)


# ---- shared CSV helpers ----------------------------------------------------------

def _append_csv(path: Path, header: list, row: list):
    with _write_lock:
        is_new = not path.exists()
        with open(path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if is_new:
                writer.writerow(header)
            writer.writerow(row)


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))
