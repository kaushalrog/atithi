"""storage.py — every byte VoxAgent persists, in one file.

WHY this layer exists: agent.py used to write CSVs and talk to Google Sheets
itself, and server.py had its own call-log code. Persistence scattered across
files means every new feature reinvents it. Now the rule is simple: anything
that touches disk (or Sheets) lives here, and nothing else knows file paths.
When real scale demands a database, THIS is the only file that changes.

What we store:
    bookings  -> bookings.db (SQLite) — the ONLY source of truth for bookings.
                 Google Sheets, if configured, gets a one-way copy after the
                 booking commits and is never read back.
    leads     -> leads.csv        (callers who didn't book — follow-up gold)
    calls     -> calls/<client_id>/<call_id>.json  (one file per conversation)

WHY bookings moved from CSV to SQLite (audit H2/H3): two conversations used to
be able to book the same slot, because each checked its own snapshot of
availability and then appended to a file nothing could lock. And in Sheets
mode the booking went to the Sheet while availability was read from the CSV,
so a booked slot kept being offered. Now one database owns bookings, and a
UNIQUE index makes "one confirmed booking per slot" a rule the database
enforces, not a hope the code maintains. The old bookings.csv is imported
once on first open and then left untouched.

TEST MODE: VOXAGENT_ENV=test (set by tests/conftest.py and evals/) switches
off the Sheets copy entirely and makes every write to the repo's real data
files raise — tests and evals can never touch a business's real bookings.

CACHING (the reason this file is fast): parsing YAML cost ~5.7 ms and the
dashboard re-read every CSV and every call-log JSON on each of its requests.
Now each file is parsed once and reused until it actually changes. Freshness
is guaranteed two ways: our own writes invalidate the entry immediately
(exact, and immune to same-millisecond rewrites), and anything edited outside
the app is caught by an (mtime, size) check that costs one stat() call.

Cached values are shared, so callers must treat them as READ-ONLY. The two
places that mutate — the agent consuming a slot and billing editing a plan —
copy what they change first.
"""

import csv
import datetime as dt
import json
import os
import sqlite3
import threading
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
BOOKINGS_DB = BASE_DIR / "bookings.db"
BOOKINGS_CSV = BASE_DIR / "bookings.csv"   # legacy: read once by the import, never written
LEADS_CSV = BASE_DIR / "leads.csv"
CALLS_DIR = BASE_DIR / "calls"
CLIENTS_DIR = BASE_DIR / "clients"

# The real data locations, captured before tests repoint the paths above.
_REAL_DATA = (BOOKINGS_DB, BOOKINGS_CSV, LEADS_CSV, CALLS_DIR, CLIENTS_DIR)


def in_test_mode() -> bool:
    return os.getenv("VOXAGENT_ENV", "").strip().lower() == "test"


def _guard_write(path: Path):
    """Fail closed: in test mode, refuse to write any real business data."""
    if not in_test_mode():
        return
    target = Path(path).resolve()
    for real in _REAL_DATA:
        real = real.resolve()
        if target == real or real in target.parents:
            raise RuntimeError(
                f"VOXAGENT_ENV=test refuses to write real data at {target}. "
                "Point storage paths at a temp folder first (see tests/conftest.py)."
            )

BOOKING_HEADER = [
    "timestamp", "client_id", "name", "phone", "service", "date", "time", "status",
]
LEAD_HEADER = ["timestamp", "client_id", "name", "phone", "interest", "note"]

# The web server handles requests on multiple threads; two simultaneous writes
# to the same CSV would interleave rows. One lock keeps appends atomic.
_write_lock = threading.Lock()

# ---- the file cache ---------------------------------------------------------------

_cache_lock = threading.Lock()
_cache: dict[str, tuple] = {}   # path -> (stamp, value)
_version = 0                    # bumped on every write; powers cheap ETags


def _stamp(path: Path):
    """Cheap identity of a file's content: (mtime_ns, size). None if missing."""
    try:
        st = path.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _cached(path: Path, loader, missing=None):
    """loader(path) once, then reused until the file changes on disk."""
    key = str(path)
    stamp = _stamp(path)
    if stamp is None:
        with _cache_lock:
            _cache.pop(key, None)
        return missing
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and hit[0] == stamp:
            return hit[1]
    value = loader(path)
    with _cache_lock:
        _cache[key] = (stamp, value)
    return value


def _invalidate(path: Path):
    """Drop a cache entry after we write it ourselves.

    Needed on top of the mtime check because the web test-call rewrites the
    same call-log file every turn, which can land inside one filesystem
    timestamp tick — the stamp would look unchanged while the content changed.
    """
    global _version
    with _cache_lock:
        _cache.pop(str(path), None)
        _version += 1


def data_version(client_id: str | None = None) -> str:
    """A cheap token that changes whenever this client's data could have.

    Used for dashboard ETags so an unchanged 20-second poll costs a 304 with
    no body instead of re-serialising every transcript.
    """
    parts = [str(_version)]
    # Open (and, first time, create) the database BEFORE stamping it, or the
    # first request stamps "no file" and the next one sees a new file — a
    # spurious change. The stamps catch bookings written by another process
    # (e.g. main.py in a terminal); the -wal file is where SQLite writes land
    # first, so it changes on every booking even before the main file does.
    _bookings_db()
    for path in (BOOKINGS_DB, Path(str(BOOKINGS_DB) + "-wal"), LEADS_CSV):
        parts.append(str(_stamp(path)))
    if client_id:
        parts.append(str(_stamp(CLIENTS_DIR / f"{client_id}.yaml")))
        parts.append(str(_stamp(CALLS_DIR / client_id)))
    return "W/\"" + str(abs(hash(tuple(parts)))) + "\""


def clear_caches():
    """Used by tests, which point the module at fresh temp directories."""
    global _version
    with _cache_lock:
        _cache.clear()
        _version += 1


# ---- bookings ------------------------------------------------------------------

_BOOKINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL, client_id TEXT NOT NULL, name TEXT, phone TEXT,
    service TEXT, date TEXT NOT NULL, time TEXT NOT NULL, status TEXT NOT NULL);
-- The double-booking guard: at most ONE confirmed booking per slot per
-- business. A cancelled row doesn't count, so a cancelled slot can be rebooked.
CREATE UNIQUE INDEX IF NOT EXISTS one_confirmed_booking_per_slot
    ON bookings(client_id, date, time) WHERE status = 'confirmed';
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

# One connection per thread (SQLite connections must not be shared across
# threads; FastAPI serves sync endpoints from a thread pool) — same pattern
# as auth.py. Schema + the one-time CSV import run once per database file.
_db_local = threading.local()
_db_prepared: set[str] = set()
_db_prepare_lock = threading.Lock()


def _bookings_db() -> sqlite3.Connection:
    path = str(BOOKINGS_DB)                  # tests repoint BOOKINGS_DB at a tmp file
    conn = getattr(_db_local, "conn", None)
    if conn is not None and getattr(_db_local, "path", None) == path:
        return conn
    if conn is not None:
        conn.close()
    _guard_write(BOOKINGS_DB)                # opening creates the file
    # isolation_level=None: autocommit. Every write below is ONE statement,
    # and a single INSERT is atomic in SQLite — no transaction juggling needed.
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    with _db_prepare_lock:
        if path not in _db_prepared:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_BOOKINGS_SCHEMA)
            _import_legacy_csv(conn)
            _db_prepared.add(path)
    _db_local.conn = conn
    _db_local.path = path
    return conn


def _import_legacy_csv(conn: sqlite3.Connection):
    """Copy bookings.csv into the database exactly once, then never touch it.

    INSERT OR IGNORE because the old CSV can already hold two confirmed rows
    for one slot (the very bug this database prevents) — the first is kept,
    the rest are counted and reported instead of aborting the upgrade.
    """
    if conn.execute("SELECT 1 FROM meta WHERE key='csv_imported'").fetchone():
        return
    imported = skipped = 0
    if BOOKINGS_CSV.exists():
        with open(BOOKINGS_CSV, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if not (r.get("client_id") and r.get("date") and r.get("time")):
                    skipped += 1
                    continue
                cur = conn.execute(
                    "INSERT OR IGNORE INTO bookings "
                    "(timestamp, client_id, name, phone, service, date, time, status) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    tuple(r.get(k, "") or "" for k in BOOKING_HEADER),
                )
                imported += cur.rowcount
                skipped += 1 - cur.rowcount
        print(f"  [storage] imported {imported} booking(s) from bookings.csv"
              + (f"; skipped {skipped} duplicate/invalid row(s)" if skipped else ""))
    conn.execute("INSERT INTO meta VALUES ('csv_imported', ?)",
                 (dt.datetime.now().isoformat(timespec="seconds"),))


def reserve_booking(row: list) -> str | None:
    """Atomically book one slot. Returns where it was saved, or None if that
    slot already has a confirmed booking (another conversation won the race).

    `row` follows BOOKING_HEADER. The UNIQUE index decides the race inside the
    database, so two callers can never both succeed — no check-then-write gap.
    """
    try:
        _bookings_db().execute(
            "INSERT INTO bookings "
            "(timestamp, client_id, name, phone, service, date, time, status) "
            "VALUES (?,?,?,?,?,?,?,?)",
            tuple(row),
        )
    except sqlite3.IntegrityError:
        return None
    _invalidate(BOOKINGS_DB)   # keep the dashboard's counters and ETag honest
    if _mirror_to_google_sheet(row):
        return "bookings.db + Google Sheet copy"
    return "bookings.db"


def read_bookings(client_id: str) -> list[dict]:
    """This client's bookings, oldest first, as {header: value} dicts."""
    rows = _bookings_db().execute(
        "SELECT timestamp, client_id, name, phone, service, date, time, status "
        "FROM bookings WHERE client_id=? ORDER BY id", (client_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def booked_pairs(client_id: str) -> set[tuple[str, str]]:
    """{(date, time)} already confirmed — what the agent must not offer."""
    rows = _bookings_db().execute(
        "SELECT date, time FROM bookings WHERE client_id=? AND status='confirmed'",
        (client_id,),
    ).fetchall()
    return {(r["date"], r["time"]) for r in rows}


def _mirror_to_google_sheet(row: list) -> bool:
    """Best-effort copy of a COMMITTED booking to the owner's Google Sheet.

    The booking is already safe in bookings.db, so a missing credentials file
    or a flaky network only costs the Sheet a row (logged), never the booking.
    The Sheet is never read back: edits made in the Sheet do not reach
    VoxAgent. Off entirely in test mode, whatever SHEET_ID says.
    """
    if in_test_mode():
        return False
    creds_path = os.getenv("GOOGLE_SHEETS_CREDENTIALS_PATH", "")
    sheet_id = os.getenv("SHEET_ID", "")
    if not creds_path or not sheet_id:
        return False
    if not Path(creds_path).is_absolute():
        creds_path = str(BASE_DIR / creds_path)
    if not os.path.exists(creds_path):
        print(f"  [warning] {creds_path} not found — booking saved, Sheet not updated.")
        return False
    try:
        worksheet = _sheet_handle(creds_path, sheet_id)
        worksheet.append_row(row)
        return True
    except Exception as e:
        _reset_sheet_handle()
        print(f"  [warning] Google Sheets copy failed ({e}) — booking saved, Sheet not updated.")
        return False


_sheet = None  # authorised worksheet, reused across bookings


def _sheet_handle(creds_path: str, sheet_id: str):
    """Authorising with Google and opening the sheet costs several network
    round trips — do it once, not on every booking."""
    global _sheet
    if _sheet is None:
        import gspread  # imported here so everything runs without gspread installed

        worksheet = gspread.service_account(filename=creds_path).open_by_key(sheet_id).sheet1
        if not worksheet.get_values("A1:H1"):
            worksheet.append_row(BOOKING_HEADER)
        _sheet = worksheet
    return _sheet


def _reset_sheet_handle():
    global _sheet
    _sheet = None


# ---- leads ---------------------------------------------------------------------

def save_lead(client_id: str, name: str, phone: str, interest: str, note: str = ""):
    row = [
        dt.datetime.now().isoformat(timespec="seconds"),
        client_id, name, phone, interest, note,
    ]
    _append_csv(LEADS_CSV, LEAD_HEADER, row)


def read_leads(client_id: str) -> list[dict]:
    """READ-ONLY list of this client's leads."""
    return _by_client(LEADS_CSV).get(client_id) or []


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
    path = folder / f"{call_id}.json"
    _guard_write(path)
    with _write_lock:
        folder.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=1)
    _invalidate(path)


def read_call_logs(client_id: str) -> list[dict]:
    """READ-ONLY call records, newest first.

    Only files whose (mtime, size) changed are re-parsed, so a dashboard
    refresh costs one stat() per call file instead of reading them all.
    """
    folder = CALLS_DIR / client_id
    records = []
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return []
    for entry in entries:
        if not entry.name.endswith(".json"):
            continue
        record = _cached(Path(entry.path), _load_json)
        if record is not None:
            records.append(record)
    records.sort(key=lambda r: r.get("started", ""), reverse=True)
    return records


def _load_json(path: Path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None  # one corrupt file must not break the dashboard


# ---- client configs ---------------------------------------------------------------

def read_client_config(client_id: str) -> dict | None:
    """READ-ONLY parsed client YAML (cached — parsing costs ~6 ms)."""
    return _cached(CLIENTS_DIR / f"{client_id}.yaml", _load_yaml)


def write_client_config(client_id: str, cfg: dict):
    path = CLIENTS_DIR / f"{client_id}.yaml"
    _guard_write(path)
    with _write_lock, open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    _invalidate(path)
    _invalidate(CLIENTS_DIR)   # the client index may have changed


def _load_yaml(path: Path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def all_clients() -> list[dict]:
    """Every client config, cached. [{client_id, config}] sorted by id.

    The admin console and phone routing both need this; neither should be
    globbing and re-parsing the clients folder on every request.
    """
    index = _cached(CLIENTS_DIR, _scan_clients, missing=[])
    # Configs are cached individually so an edit to one doesn't re-read the rest.
    out = []
    for client_id in index:
        cfg = read_client_config(client_id)
        if cfg is not None:
            out.append({"client_id": client_id, "config": cfg})
    return out


def _scan_clients(folder: Path) -> list[str]:
    try:
        return sorted(e.name[:-5] for e in os.scandir(folder)
                      if e.name.endswith(".yaml"))
    except OSError:
        return []


def client_for_number(number: str) -> str | None:
    """Which business owns this phone number (cached — used per inbound call)."""
    if not number:
        return None
    wanted = number.strip()
    for entry in all_clients():
        if str(entry["config"].get("twilio_number", "")).strip() == wanted:
            return entry["client_id"]
    return None


# ---- shared CSV helpers ----------------------------------------------------------

def _append_csv(path: Path, header: list, row: list):
    _guard_write(path)
    with _write_lock:
        is_new = not path.exists()
        with open(path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if is_new:
                writer.writerow(header)
            writer.writerow(row)
    _invalidate(path)


def _by_client(path: Path) -> dict[str, list[dict]]:
    """Parsed CSV grouped by client_id — one pass, then cached."""
    return _cached(path, _group_csv, missing={}) or {}


def _group_csv(path: Path) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            grouped.setdefault(row.get("client_id", ""), []).append(row)
    return grouped


def _read_csv(path: Path) -> list[dict]:
    """Flat rows (kept for tests and ad-hoc use)."""
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))
