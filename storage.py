"""storage.py — every byte VoxAgent persists, in one file.

WHY this layer exists: agent.py used to write CSVs and talk to Google Sheets
itself, and server.py had its own call-log code. Persistence scattered across
files means every new feature reinvents it. Now the rule is simple: anything
that touches disk (or Sheets) lives here, and nothing else knows file paths.
When real scale demands a database, THIS is the only file that changes.

What we store:
    bookings  -> bookings.db (SQLite) — the ONLY source of truth for bookings.
                 Google Sheets, if configured, gets a one-way copy after each
                 booking commits, queued for a background thread so the
                 caller never waits for Google. It's read exactly once, by the
                 explicit `python storage.py import-sheet` upgrade step.
    leads     -> leads.csv        (callers who didn't book — follow-up gold)
    calls     -> calls/<client_id>/<call_id>.json  (one file per conversation)

WHY bookings moved from CSV to SQLite (audit H2/H3): two conversations used to
be able to book the same slot, because each checked its own snapshot of
availability and then appended to a file nothing could lock. And in Sheets
mode the booking went to the Sheet while availability was read from the CSV,
so a booked slot kept being offered. Now one database owns bookings, and a
UNIQUE index makes "one confirmed booking per slot" a rule the database
enforces, not a hope the code maintains. The old bookings.csv is imported
on first open (and re-imported, without duplicates, only if it changes —
the rollback/roll-forward path); this code never writes it.

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

import atexit
import csv
import datetime as dt
import json
import os
import queue
import re
import sqlite3
import threading
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv

import perf
import scheduling

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
BOOKINGS_DB = BASE_DIR / "bookings.db"
BOOKINGS_CSV = BASE_DIR / "bookings.csv"   # legacy: read once by the import, never written
LEADS_CSV = BASE_DIR / "leads.csv"
CALLS_DIR = BASE_DIR / "calls"
NOTIFY_LOG = BASE_DIR / "notifications.jsonl"   # every customer SMS, sent or dry-run
CLIENTS_DIR = BASE_DIR / "clients"

# The real data locations, captured before tests repoint the paths above.
_REAL_DATA = (BOOKINGS_DB, BOOKINGS_CSV, LEADS_CSV, CALLS_DIR, CLIENTS_DIR, NOTIFY_LOG)


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


# ---- background work (never on the call path) -------------------------------------

class _BackgroundQueue:
    """One daemon thread draining a BOUNDED queue.

    WHY: work that is not the source of truth (the Google Sheet copy, the perf
    log) must never make a caller wait, and must never pile up without limit
    while its destination is slow or down. put() never blocks: when the queue
    is full the item is dropped and counted, so memory stays capped whatever
    the network does. The thread starts on first use, so importing storage
    (tests, CLI commands) starts nothing.
    """

    def __init__(self, name: str, handle, maxsize: int):
        self.name, self.handle = name, handle
        self.queue: queue.Queue = queue.Queue(maxsize=maxsize)
        self.dropped = 0
        self._thread = None
        self._start_lock = threading.Lock()

    def put(self, item) -> bool:
        """Queue an item; False (and counted) when the queue is full."""
        self._ensure_thread()
        try:
            self.queue.put_nowait(item)
            return True
        except queue.Full:
            self.dropped += 1
            return False

    def pending(self) -> int:
        """Items queued or being handled right now."""
        return self.queue.unfinished_tasks

    def drain(self, timeout: float) -> int:
        """Wait up to `timeout` seconds for the work to finish; returns what's left."""
        deadline = time.monotonic() + timeout
        while self.pending() and time.monotonic() < deadline:
            time.sleep(0.02)
        return self.pending()

    def _ensure_thread(self):
        if self._thread is not None and self._thread.is_alive():
            return
        with self._start_lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
                self._thread.start()

    def _run(self):
        while True:
            item = self.queue.get()
            try:
                self.handle(item)
            except Exception as e:
                # A background worker must survive any error in its handler,
                # or every later item would silently wait forever.
                print(f"  [{self.name}] {type(e).__name__}: {e}")
            finally:
                self.queue.task_done()


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
CREATE INDEX IF NOT EXISTS bookings_by_client ON bookings(client_id, id);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
-- Questions the receptionist couldn't answer from the business info. One row
-- per distinct question (normalised); 'asked' counts repeats.
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY, client_id TEXT NOT NULL, question TEXT NOT NULL,
    norm TEXT NOT NULL, asked INTEGER NOT NULL DEFAULT 1,
    first_asked TEXT NOT NULL, last_asked TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open', answer TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_question
    ON questions(client_id, norm) WHERE status = 'open';
"""

# One connection per thread (SQLite connections must not be shared across
# threads; FastAPI serves sync endpoints from a thread pool) — same pattern
# as auth.py. Schema + the one-time CSV import run once per database file.
_db_local = threading.local()
_db_prepared: set[str] = set()
_db_prepare_lock = threading.Lock()


class BookingsUnavailable(RuntimeError):
    """New bookings are paused. Either a configured Google Sheet's old bookings
    haven't been imported yet (run `python storage.py import-sheet`), or
    bookings.csv couldn't be imported. Booking now could double-book one of
    those customers, so the agent offers a callback instead."""


# Per database file: why its legacy CSV import failed (bookings pause, reads don't).
_csv_import_errors: dict[str, str] = {}


def _bookings_db() -> sqlite3.Connection:
    path = str(BOOKINGS_DB)                  # tests repoint BOOKINGS_DB at a tmp file
    conn = getattr(_db_local, "conn", None)
    if conn is not None and getattr(_db_local, "path", None) == path:
        return conn
    if conn is not None:
        conn.close()
    # Guard the exact path about to be opened (opening creates the file),
    # not the global again: it can change between the two reads.
    _guard_write(Path(path))
    # isolation_level=None: autocommit. Normal writes are ONE statement (atomic
    # on its own); the imports below open explicit transactions.
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    with _db_prepare_lock:
        if path not in _db_prepared:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_BOOKINGS_SCHEMA)
            # No network here, ever: this runs on the first request, possibly
            # in the middle of a phone call. Only the local CSV is imported.
            try:
                _import_legacy_csv(conn)
                _csv_import_errors.pop(path, None)
            except Exception as e:
                # A broken CSV must not take the dashboard and availability
                # down with it: reads keep working, NEW bookings pause.
                _csv_import_errors[path] = f"{type(e).__name__}: {e}"
                print(f"  [storage] bookings.csv could not be imported ({e}); new bookings "
                      "are paused — fix or move the file, then restart.")
            _db_prepared.add(path)
    _db_local.conn = conn
    _db_local.path = path
    return conn


_INSERT_BOOKING = ("INSERT INTO bookings "
                   "(timestamp, client_id, name, phone, service, date, time, status) "
                   "VALUES (?,?,?,?,?,?,?,?)")


def _normalize_row(r: dict) -> tuple:
    """A legacy row (CSV or Sheet) in BOOKING_HEADER order, cleaned so the
    slot guard can see it: trimmed, status lowercased, date YYYY-MM-DD, time
    HH:MM. A row whose date/time can't be read is still a real customer: it
    keeps its raw values with status 'invalid' (visible, exported, but not
    blocking a slot nobody can identify)."""
    vals = {k: str(r.get(k) if r.get(k) is not None else "").strip() for k in BOOKING_HEADER}
    # A row with no status is treated as booked: blocking a free slot is the
    # recoverable mistake; double-booking a customer is not.
    vals["status"] = vals["status"].lower() or "confirmed"
    time_of_day = scheduling.parse_time(vals["time"])
    try:
        day = dt.date.fromisoformat(vals["date"])
    except ValueError:
        day = None
    if day is None or time_of_day is None or not vals["client_id"]:
        vals["status"] = "invalid"
    else:
        vals["date"] = day.isoformat()
        vals["time"] = time_of_day.strftime("%H:%M")
    return tuple(vals[k] for k in BOOKING_HEADER)


def _import_rows(conn: sqlite3.Connection, rows) -> tuple[int, int, int, int]:
    """Insert legacy rows; returns (imported, conflicts, invalid, already_present).

    Idempotent: a row identical to one already in the database (every field
    but status) is skipped, so re-importing a
    file — e.g. after a rollback and roll-forward — never duplicates anyone.
    A second confirmed booking for an already-booked slot is the old
    double-booking bug's leftover: a REAL customer, kept as status 'conflict'.
    """
    imported = conflicts = invalid = present = 0
    for r in rows:
        row = _normalize_row(r)
        status = row[-1]
        # "Identical" = every field except status (an exported row may have
        # been confirmed then, conflict now): two DIFFERENT customers in one
        # slot differ by name/phone, so both are kept.
        if conn.execute(
            "SELECT 1 FROM bookings WHERE timestamp=? AND client_id=? AND name=? "
            "AND phone=? AND service=? AND date=? AND time=?", row[:-1],
        ).fetchone():
            present += 1
            continue
        if status == "invalid":
            invalid += 1
        try:
            conn.execute(_INSERT_BOOKING, row)
            imported += status != "invalid"
        except sqlite3.IntegrityError:
            conn.execute(_INSERT_BOOKING, row[:-1] + ("conflict",))
            conflicts += 1
    return imported, conflicts, invalid, present


def _import_once(conn: sqlite3.Connection, marker: str, version: str, load_rows):
    """Run one import unless `marker` already records this `version` of the
    source — exactly once per version, across threads AND processes.

    BEGIN IMMEDIATE takes the database's write lock, so a second process
    (main.py next to server.py) waits here, then sees the marker and skips.
    One transaction means a crash mid-import leaves no rows behind. Returns
    None if this version was already imported."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        done = conn.execute("SELECT value FROM meta WHERE key=?", (marker,)).fetchone()
        if done and done["value"] == version:
            conn.execute("COMMIT")
            return None
        counts = _import_rows(conn, load_rows())
        conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (marker, version))
        conn.execute("COMMIT")
        return counts
    except BaseException:
        if conn.in_transaction:   # SQLite may already have rolled back (disk full)
            conn.execute("ROLLBACK")
        raise


def _report_import(source: str, counts):
    if not counts or not any(counts):
        return
    imported, conflicts, invalid, present = counts
    print(f"  [storage] imported {imported} booking(s) from {source}"
          + (f"; {conflicts} double-booked row(s) kept as status 'conflict'" if conflicts else "")
          + (f"; {invalid} unreadable row(s) kept as status 'invalid'" if invalid else "")
          + (f"; {present} already present" if present else "")
          + (" — check them on the dashboard" if conflicts or invalid else ""))


def _read_legacy_csv() -> list[dict]:
    """bookings.csv rows. Excel on Windows saves CSV as cp1252, not UTF-8."""
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            with open(BOOKINGS_CSV, newline="", encoding=encoding) as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("csv", b"", 0, 1, "bookings.csv is neither UTF-8 nor cp1252")


def _import_legacy_csv(conn: sqlite3.Connection):
    """Import bookings.csv, and import it again whenever it changes.

    It's normally read once and never written again. But after a rollback
    (export-csv, older code appends to bookings.csv) and a roll-forward, the
    file has new rows: the marker stores the file's (mtime, size), so a
    changed file is re-imported — idempotently, so nothing is duplicated."""
    stamp = _stamp(BOOKINGS_CSV)
    version = json.dumps(stamp)
    rows = _read_legacy_csv if stamp else list
    _report_import("bookings.csv", _import_once(conn, "csv_imported", version, rows))


def _sheet_configured() -> bool:
    """A Google Sheet is configured (whether or not it's reachable right now)."""
    return bool(os.getenv("SHEET_ID", "").strip()) and not in_test_mode()


def bookings_paused_reason() -> str | None:
    """Why new bookings are paused, for /admin and the startup log; None if not."""
    conn = _bookings_db()
    error = _csv_import_errors.get(str(BOOKINGS_DB))
    if error:
        return f"bookings.csv could not be imported ({error}) — fix or move it, then restart"
    if _sheet_configured() and not conn.execute(
            "SELECT 1 FROM meta WHERE key='sheet_imported'").fetchone():
        return ("the Google Sheet's existing bookings aren't imported yet — run "
                "`python storage.py import-sheet` (or `import-sheet --skip` if it has none)")
    return None


def import_sheet(skip: bool = False):
    """One explicit, operator-run step: copy the bookings that only ever lived
    in the configured Google Sheet (the old code wrote them there INSTEAD of
    bookings.csv) into the database. Until this has run, new bookings pause.

    WHY a command and not automatic: an automatic import put Google's network
    on the path of live phone calls, and one wrong SHEET_ID silently froze
    every business's bookings. A command runs once, in a terminal, and fails
    loudly. `skip=True` records that there is nothing to import.
    Returns the import counts, or None if it was already done."""
    conn = _bookings_db()
    if skip:
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('sheet_imported', 'skipped')")
        _invalidate(BOOKINGS_DB)
        return None
    target = _sheets_target()
    if target is None:
        raise RuntimeError("No usable Google Sheet: set SHEET_ID and point "
                           "GOOGLE_SHEETS_CREDENTIALS_PATH at an existing credentials file.")
    # get_all_values returns text exactly as shown — get_all_records would turn
    # '+919876543210' into the number 919876543210.
    values = _sheet_handle(*target).get_all_values()
    header = [str(h).strip() for h in (values[0] if values else [])]
    records = [dict(zip(header, row)) for row in values[1:]]
    counts = _import_once(conn, "sheet_imported", "imported", lambda: records)
    _report_import("the Google Sheet", counts)
    _invalidate(BOOKINGS_DB)
    return counts


# Bookings from this process take turns at the INSERT. Correctness doesn't
# need it (the UNIQUE index decides every race, across processes too); speed
# does. Phone tools run on parallel threads, and two simultaneous INSERTs on
# separate connections make SQLite's busy handler sleep in millisecond steps
# (bench: insert max 4-12 ms; with this lock 1.3-1.6 ms). A Python lock hands
# over instantly. Held only for the one statement.
_booking_insert_lock = threading.Lock()
# ...but never wait on it for long: if another process holds the database,
# the thread holding this lock sits in SQLite's 10 s busy wait, and bookings
# queued behind it would wait 10 s EACH. Past this, take SQLite's own turn.
BOOKING_LOCK_WAIT_S = 1.0


def reserve_booking(row: list) -> str | None:
    """Atomically book one slot. Returns where it was saved, or None if that
    slot already has a confirmed booking (another conversation won the race).

    `row` follows BOOKING_HEADER. The UNIQUE index decides the race inside the
    database, so two callers can never both succeed — no check-then-write gap.
    Raises BookingsUnavailable while bookings are paused (see
    bookings_paused_reason); that check is local only, never a network call.
    """
    conn = _bookings_db()
    if bookings_paused_reason():
        raise BookingsUnavailable(
            "Bookings are paused for a moment — apologise and offer to have the "
            "front desk call the customer back to confirm a slot."
        )
    with perf.span("db.booking_insert"):
        locked = _booking_insert_lock.acquire(timeout=BOOKING_LOCK_WAIT_S)
        try:
            conn.execute(_INSERT_BOOKING, tuple(row))
        except sqlite3.IntegrityError:
            return None
        finally:
            if locked:
                _booking_insert_lock.release()
    _invalidate(BOOKINGS_DB)   # keep the dashboard's counters and ETag honest
    # The booking is committed: it's real now, whatever happens next. The
    # Sheet copy is queued, never awaited — it used to run right here, so a
    # slow Google API made the caller (and, on the phone, every other
    # caller) wait for a spreadsheet. See docs/PERFORMANCE_AUDIT.md F1.
    if _sheets_target(quiet=True) is not None:
        _queue_sheet_copy(row)
    return "bookings.db"


def export_bookings_csv(path, force: bool = False) -> int:
    """Write every booking to a CSV in the old bookings.csv format.

    The rollback path: the pre-database code reads bookings.csv, so run
    `python storage.py export-csv bookings.csv --force` before reverting.
    An existing file is never lost: it's kept as <name>.bak-<time> first.
    For a Sheets deployment the Sheet import is also re-armed, so after a
    roll-forward bookings pause until `import-sheet` picks up whatever the
    older code wrote to the Sheet meanwhile."""
    path = Path(path)
    if path.exists():
        if not force:
            raise FileExistsError(f"{path} exists — pass force=True (--force) to replace it")
        backup = path.with_name(f"{path.name}.bak-{dt.datetime.now():%Y%m%d-%H%M%S}")
        _guard_write(backup)
        path.rename(backup)
    _guard_write(path)
    conn = _bookings_db()
    rows = conn.execute(
        "SELECT timestamp, client_id, name, phone, service, date, time, status "
        "FROM bookings ORDER BY id").fetchall()
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(BOOKING_HEADER)
        writer.writerows([tuple(r) for r in rows])
    if _sheet_configured():
        conn.execute("DELETE FROM meta WHERE key='sheet_imported'")
    return len(rows)


def read_bookings(client_id: str) -> list[dict]:
    """This client's bookings, oldest first, as {header: value} dicts (plus
    the row id, which the owner's cancel button refers to)."""
    rows = _bookings_db().execute(
        "SELECT id, timestamp, client_id, name, phone, service, date, time, status "
        "FROM bookings WHERE client_id=? ORDER BY id", (client_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---- cancel and reschedule -------------------------------------------------------
#
# A booking is never deleted: it changes status, so the owner can see what
# happened. 'cancelled' and 'rescheduled' rows are ignored by the
# double-booking guard (the UNIQUE index only covers 'confirmed'), which is
# what frees the slot for someone else.

def find_bookings(client_id: str, phone: str) -> list[dict]:
    """This caller's upcoming confirmed bookings (phone matched on its last
    10 digits, so +91 98..., 098... and 98... are the same person)."""
    want = _phone10(phone)
    if len(want) < 10:
        return []
    rows = _bookings_db().execute(
        "SELECT id, name, phone, service, date, time FROM bookings "
        "WHERE client_id=? AND status='confirmed' AND date >= ? ORDER BY date, time",
        (client_id, dt.date.today().isoformat()),
    ).fetchall()
    return [dict(r) for r in rows if _phone10(r["phone"]) == want]


def _locate(conn, client_id, booking_id=None, date=None, time_=None, phone=None):
    """The confirmed booking an owner (by id) or a caller (by slot + phone)
    means; None if there isn't exactly that booking."""
    if booking_id is not None:
        row = conn.execute("SELECT * FROM bookings WHERE id=? AND client_id=? AND status='confirmed'",
                           (booking_id, client_id)).fetchone()
        return row
    row = conn.execute("SELECT * FROM bookings WHERE client_id=? AND date=? AND time=? "
                       "AND status='confirmed'", (client_id, date, time_)).fetchone()
    if row is None or _phone10(row["phone"]) != _phone10(phone) or len(_phone10(phone)) < 10:
        return None          # a caller can only change a booking made with their number
    return row


def _transaction(conn):
    """BEGIN IMMEDIATE ... COMMIT, rolled back on any error."""
    class _Tx:
        def __enter__(self):
            conn.execute("BEGIN IMMEDIATE")
        def __exit__(self, exc_type, exc, tb):
            conn.execute("ROLLBACK" if exc_type else "COMMIT")
            return False
    return _Tx()


def cancel_booking(client_id: str, booking_id: int | None = None, date: str | None = None,
                   time_: str | None = None, phone: str | None = None) -> dict | None:
    """Cancel one confirmed booking; returns it, or None if there's no such
    booking (wrong slot, wrong number, already cancelled)."""
    conn = _bookings_db()
    with perf.span("db.booking_cancel"), _transaction(conn):
        row = _locate(conn, client_id, booking_id, date, time_, phone)
        if row is None:
            return None
        conn.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (row["id"],))
    _invalidate(BOOKINGS_DB)
    done = dict(row) | {"status": "cancelled"}
    if _sheets_target(quiet=True) is not None:      # the Sheet is a log: append the change
        _queue_sheet_copy([dt.datetime.now().isoformat(timespec="seconds"), client_id, row["name"],
                           row["phone"], row["service"], row["date"], row["time"], "cancelled"])
    return done


def reschedule_booking(client_id: str, new_date: str, new_time: str, booking_id: int | None = None,
                       date: str | None = None, time_: str | None = None,
                       phone: str | None = None) -> tuple[str, dict | None]:
    """Move one confirmed booking to a new slot, atomically.

    Returns ("rescheduled", new booking), ("not_found", None) or
    ("taken", None) when the new slot already has a confirmed booking — in
    which case nothing changed and the old booking still stands."""
    if bookings_paused_reason():
        raise BookingsUnavailable(
            "Bookings are paused for a moment — apologise and offer to have the "
            "front desk call the customer back to change the appointment.")
    conn = _bookings_db()
    with perf.span("db.booking_reschedule"):
        try:
            with _transaction(conn):
                row = _locate(conn, client_id, booking_id, date, time_, phone)
                if row is None:
                    return "not_found", None
                if (row["date"], row["time"]) == (new_date, new_time):
                    return "rescheduled", dict(row)
                conn.execute("UPDATE bookings SET status='rescheduled' WHERE id=?", (row["id"],))
                new = [dt.datetime.now().isoformat(timespec="seconds"), client_id, row["name"],
                       row["phone"], row["service"], new_date, new_time, "confirmed"]
                conn.execute(_INSERT_BOOKING, tuple(new))   # the UNIQUE index decides
        except sqlite3.IntegrityError:
            return "taken", None          # rolled back: the old booking is untouched
    _invalidate(BOOKINGS_DB)
    if _sheets_target(quiet=True) is not None:
        _queue_sheet_copy(new)
    return "rescheduled", dict(zip(BOOKING_HEADER, new))


# ---- questions the receptionist couldn't answer -------------------------------

def _norm_question(q: str) -> str:
    """Same question however it's punctuated or spaced (any script)."""
    return " ".join(re.sub(r"[^\w\s]", "", q.lower()).split())


def note_question(client_id: str, question: str) -> int:
    """Record (or count again) an unanswered question; returns how many times
    it has been asked."""
    q = " ".join(str(question or "").split())[:300]
    if not q:
        return 0
    now = dt.datetime.now().isoformat(timespec="seconds")
    conn = _bookings_db()
    with _transaction(conn):
        conn.execute(
            "INSERT INTO questions (client_id, question, norm, first_asked, last_asked) "
            "VALUES (?,?,?,?,?) ON CONFLICT(client_id, norm) WHERE status='open' "
            "DO UPDATE SET asked = asked + 1, last_asked = excluded.last_asked",
            (client_id, q, _norm_question(q), now, now))
        n = conn.execute("SELECT asked FROM questions WHERE client_id=? AND norm=? AND status='open'",
                         (client_id, _norm_question(q))).fetchone()[0]
    _invalidate(BOOKINGS_DB)
    return n


def open_questions(client_id: str) -> list[dict]:
    """Open questions, most asked first."""
    rows = _bookings_db().execute(
        "SELECT id, question, asked, first_asked, last_asked FROM questions "
        "WHERE client_id=? AND status='open' ORDER BY asked DESC, last_asked DESC", (client_id,)).fetchall()
    return [dict(r) for r in rows]


def close_question(client_id: str, question_id: int, answer: str | None) -> dict | None:
    """Mark a question answered (with its answer) or dismissed (answer None)."""
    conn = _bookings_db()
    with _transaction(conn):
        row = conn.execute("SELECT * FROM questions WHERE id=? AND client_id=? AND status='open'",
                           (question_id, client_id)).fetchone()
        if row is None:
            return None
        conn.execute("UPDATE questions SET status=?, answer=? WHERE id=?",
                     ("answered" if answer else "dismissed", answer, question_id))
    _invalidate(BOOKINGS_DB)
    return dict(row)


def booked_pairs(client_id: str) -> set[tuple[str, str]]:
    """{(date, time)} already confirmed from today on — what the agent must not
    offer. Past dates are never offered anyway, so they're not even read: this
    runs on every availability check, and history only grows."""
    rows = _bookings_db().execute(
        "SELECT date, time FROM bookings "
        "WHERE client_id=? AND status='confirmed' AND date >= ?",
        (client_id, dt.date.today().isoformat()),
    ).fetchall()
    return {(r["date"], r["time"]) for r in rows}


SHEETS_QUEUE_MAX = 1000          # copies waiting; beyond this they're dropped (and counted)
SHEETS_RETRY_WAITS_S = (2, 8, 30)  # backoff between tries: 4 tries in all
SHEETS_TIMEOUT_S = (5, 10)         # gspread (connect, read); its default is no timeout at all
SHEETS_EXIT_DRAIN_S = 5


def _copy_to_sheet(row: list):
    """The Sheets worker: copy one COMMITTED booking to the owner's Sheet.

    Runs on the background thread, never on a call. The booking is already
    safe in bookings.db, so a missing credentials file or a Google outage
    only costs the Sheet a row (retried, then logged and counted), never the
    booking. Edits made in the Sheet do not reach VoxAgent (it's read only by
    the one-time import-sheet step). Off entirely in test mode.
    """
    target = _sheets_target()
    if target is None:
        return
    error = None
    for wait in (0, *SHEETS_RETRY_WAITS_S):
        if wait:
            time.sleep(wait)
        try:
            sheet = _sheet_handle(*target)     # a failure here never reached the append
        except Exception as e:
            _reset_sheet_handle()
            error = e
            continue
        try:
            with perf.span("sheets.copy"):
                sheet.append_row(row)
            return
        except Exception as e:
            _reset_sheet_handle()       # a stale handle may be the problem
            error = e
            if _may_have_landed(e):
                # Google may have applied the append and answered too late.
                # append_row is not idempotent: retrying could put the
                # booking in the owner's Sheet twice, which reads as a
                # double booking. Say so instead of guessing.
                perf.event("sheets.unconfirmed")
                print(f"  [warning] Google Sheet copy may or may not have landed ({type(e).__name__}) "
                      f"— check the Sheet for {row[1]} {row[5]} {row[6]}; it is safe in bookings.db.")
                return
    perf.event("sheets.dropped")
    # Which booking, without the customer's name or number in the log.
    print(f"  [warning] Google Sheet copy dropped after {1 + len(SHEETS_RETRY_WAITS_S)} tries "
          f"({type(error).__name__}) — {row[1]} {row[5]} {row[6]} is safe in bookings.db; "
          "the Sheet is missing that row.")


def _may_have_landed(error: Exception) -> bool:
    """A read timeout: the request reached Google, the answer didn't reach us.
    (requests' ReadTimeout, which gspread raises, matched by name so this
    file needs no requests import.) Connection errors, 429s and 5xx never
    landed and are safe to retry."""
    return any(c.__name__ in ("ReadTimeout", "ReadTimeoutError")
               for c in type(error).__mro__)


_sheets_queue = _BackgroundQueue("sheets-copy", _copy_to_sheet, maxsize=SHEETS_QUEUE_MAX)


def _queue_sheet_copy(row: list):
    if not _sheets_queue.put(list(row)):
        perf.event("sheets.dropped")
        print(f"  [warning] Google Sheet copy queue full ({SHEETS_QUEUE_MAX}) — "
              f"{row[1]} {row[5]} {row[6]} is safe in bookings.db; the Sheet is missing that row.")
    perf.gauge("sheets.queue", _sheets_queue.pending())


def _drain_sheets_at_exit():
    """On shutdown, give queued copies a few seconds, then say what's left."""
    if not _sheets_queue.pending():
        return
    left = _sheets_queue.drain(SHEETS_EXIT_DRAIN_S)
    if left:
        print(f"  [warning] {left} Google Sheet cop(ies) not written at shutdown — "
              "the bookings are safe in bookings.db.")


atexit.register(_drain_sheets_at_exit)


def sheets_usable() -> bool:
    """Is a Google Sheet configured AND its credentials file present? (For
    /admin's status row — quiet, because the dashboard polls it.)"""
    return _sheets_target(quiet=True) is not None


def _sheets_target(quiet: bool = False) -> tuple[str, str] | None:
    """(credentials path, sheet id) when a Google Sheet is configured and
    usable; None otherwise. Always None in test mode, whatever SHEET_ID says."""
    if in_test_mode():
        return None
    creds_path = os.getenv("GOOGLE_SHEETS_CREDENTIALS_PATH", "")
    sheet_id = os.getenv("SHEET_ID", "")
    if not creds_path or not sheet_id:
        return None
    if not Path(creds_path).is_absolute():
        creds_path = str(BASE_DIR / creds_path)
    if not os.path.exists(creds_path):
        if not quiet:
            print(f"  [warning] {creds_path} not found — Google Sheet not used.")
        return None
    return creds_path, sheet_id


_sheet = None  # authorised worksheet, reused across bookings


def _sheet_handle(creds_path: str, sheet_id: str):
    """Authorising with Google and opening the sheet costs several network
    round trips — do it once, not on every booking."""
    global _sheet
    if _sheet is None:
        import gspread  # imported here so everything runs without gspread installed

        client = gspread.service_account(filename=creds_path)
        client.set_timeout(SHEETS_TIMEOUT_S)
        worksheet = client.open_by_key(sheet_id).sheet1
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
                        call_id: str | None = None, caller: str | None = None,
                        ended: dt.datetime | None = None):
    """Write (or rewrite) the call record for one conversation.

    Works for every channel: the web server calls this after each turn with a
    stable call_id; the terminal/voice/live wrappers call it once on exit.
    A conversation with no customer turn AND no tool action is not a call, so
    nothing is logged. (Tools count: on a phone line the speech transcript can
    come back empty while a booking still happened.)

    Also writes the call's TRACE (see _write_trace) next to it, in a traces/
    subfolder: the dashboard ships whole call records to the browser and
    read_call_logs counts every *.json in the folder as a call, so the trace
    must live elsewhere.
    """
    turns = sum(1 for m in agent.history if m["role"] == "user")
    if turns == 0 and not any(m["role"] == "tool" for m in agent.history):
        return
    if call_id is None:
        call_id = started.strftime("%Y%m%d_%H%M%S_") + channel
    now = ended or dt.datetime.now()   # a re-save keeps the original hang-up time
    record = {
        "call_id": call_id,
        "client_id": agent.client_id,
        "channel": channel,
        "started": started.isoformat(timespec="seconds"),
        "ended": now.isoformat(timespec="seconds"),
        "seconds": int((now - started).total_seconds()),
        "turns": turns,
        "transcript": agent.transcript_text(),
        # What the call actually achieved, from the tools' own results. The
        # dashboard used to guess from the transcript, so a FAILED booking
        # attempt counted as a booked call (audit M1).
        "outcome": call_outcome(agent.history),
    }
    if caller:
        # Who called is metadata, not something the customer said (audit M2).
        record["caller"] = caller
        record["transcript"] = f"Caller: {caller}\n\n" + record["transcript"]
    folder = CALLS_DIR / agent.client_id
    path = folder / f"{call_id}.json"
    perf_id = getattr(agent, "perf_id", None)
    with perf.span("call_log.write", call=perf_id, channel=channel):
        _write_json_atomic(path, record)
    _invalidate(path)
    try:
        with perf.span("trace.write", call=perf_id, channel=channel):
            _write_trace(agent, channel, started, call_id, caller,
                         folder / "traces" / f"{call_id}.json")
    except Exception as e:
        # A trace bug must never cost the business its call record. The
        # checker reports a call without a trace as "skipped", never as clean.
        print(f"  (trace for call {call_id} not written: {type(e).__name__}: {e})")


# ---- call traces (the evidence voxcheck reads) ------------------------------------

TRACE_VERSION = 1
# How VoxAgent's tools map onto the neutral action types the checker reasons
# about. Kept in step with voxcheck's built-in mapping (docs/ARCHITECTURE.md §3).
_TOOL_TYPES = {"check_availability": "availability", "book_appointment": "book",
               "save_lead": "lead", "find_booking": "lookup", "cancel_booking": "cancel",
               "note_unanswered_question": "question",
               "reschedule_booking": "reschedule"}
_OK_STATUS = {"book": "confirmed", "lead": "saved", "cancel": "cancelled",
              "reschedule": "rescheduled"}


def call_outcome(history: list[dict]) -> dict:
    """{"booked", "lead"}: did a booking / lead tool SUCCEED in this call?"""
    done = set()
    for m in history:
        if m["role"] == "tool":
            kind = _TOOL_TYPES.get(m["name"])
            if kind in ("book", "lead") and _action_ok(kind, m["result"]):
                done.add(kind)
    return {"booked": "book" in done, "lead": "lead" in done}


def _phone10(phone) -> str:
    """Last 10 digits: the same number written +91 98..., 098... or 98... ."""
    return re.sub(r"\D", "", str(phone or ""))[-10:]


def tool_raised(result: dict) -> bool:
    """Did the tool raise? run_tool turns an exception into {"error": ...}
    with no "status"; a tool's own validation failure carries a status.
    One rule, used by the trace, the call outcome and the perf counters."""
    return "error" in result and "status" not in result


def _action_ok(kind: str, result: dict) -> bool:
    if tool_raised(result):
        return False
    if kind in _OK_STATUS:
        return result.get("status") == _OK_STATUS[kind]
    return True  # availability answers have no status: an answer is success


def _trace_turns_and_actions(history: list[dict]):
    """Split agent.history into spoken turns and tool actions.

    Each action belongs to the reply it was made for, so its turn_index is the
    index of the NEXT agent turn (len(turns) if the call ended first). The
    checker counts an action as "at or before" a claim when its turn_index is
    not after the claim's turn.
    """
    turns, actions, pending = [], [], []
    calls_by_name: dict[str, list] = {}
    for msg in history:
        if msg["role"] == "user":
            turns.append({"index": len(turns), "speaker": "caller", "text": msg["text"], "at": msg.get("at")})
        elif msg["role"] == "assistant":
            for call in msg.get("tool_calls") or []:
                calls_by_name.setdefault(call["name"], []).append(call)
            # Text that came WITH a tool call was never shown to the customer
            # (agent.chat only returns the final text-only reply), so it is not
            # something the agent said.
            if msg.get("text") and not msg.get("tool_calls"):
                for action in pending:
                    action["turn_index"] = len(turns)
                pending = []
                turns.append({"index": len(turns), "speaker": "agent", "text": msg["text"], "at": msg.get("at")})
        elif msg["role"] == "tool":
            queue = calls_by_name.get(msg["name"])
            call = queue.pop(0) if queue else {}
            kind = _TOOL_TYPES.get(msg["name"], "other")
            result = msg.get("result") or {}
            action = {"turn_index": None, "at": msg.get("at"), "type": kind, "name": msg["name"],
                      "args": call.get("args", {}), "ok": _action_ok(kind, result), "result": result}
            actions.append(action)
            pending.append(action)
    for action in pending:
        action["turn_index"] = len(turns)
    return turns, actions


def _write_trace(agent, channel: str, started: dt.datetime, call_id: str,
                 caller: str | None, path: Path):
    """The machine-readable record of one call: what was said, which tools ran
    and what they returned, plus the business's booking rows as of call end.

    The snapshot is what makes the verdict reproducible: a booking edited next
    week cannot change what this call is judged against. It holds full rows
    only for this call's own phone numbers; other customers' same-day
    bookings appear as taken slots (date, time, status) with no name or phone.
    """
    tz = agent.tz
    turns, actions = _trace_turns_and_actions(agent.history)
    ended = dt.datetime.now(tz).isoformat(timespec="seconds")

    dates, phones = set(), {_phone10(caller)} - {""}
    for a in actions:
        for source in (a["args"], a["result"]):
            if isinstance(source, dict):
                if source.get("date"):
                    dates.add(str(source["date"]))
                if a["type"] in ("book", "lead") and source.get("phone"):
                    phones.add(_phone10(source["phone"]))
    snapshot = []
    if dates:
        marks = ",".join("?" * len(dates))
        rows = _bookings_db().execute(
            "SELECT timestamp, name, phone, service, date, time, status FROM bookings "
            f"WHERE client_id=? AND status='confirmed' AND date IN ({marks}) ORDER BY id",
            (agent.client_id, *sorted(dates)),
        ).fetchall()
        for r in rows:
            if _phone10(r["phone"]) in phones:
                snapshot.append(dict(r, kind="booking"))
            else:
                # Another customer's booking: the checker only needs to know
                # the slot was taken, so their name and number stay out of
                # this call's trace (traces are kept even when a booking is
                # later deleted).
                snapshot.append({"kind": "booking", "date": r["date"], "time": r["time"],
                                 "status": r["status"]})
    if phones:
        snapshot += [dict(r, kind="lead") for r in read_leads(agent.client_id)
                     if _phone10(r.get("phone")) in phones]

    trace = {
        "trace_version": TRACE_VERSION,
        "call_id": call_id,
        "client_id": agent.client_id,
        "channel": channel,
        "caller": caller or "",
        "started_at": started.astimezone(tz).isoformat(timespec="seconds"),
        "ended_at": ended,
        "timezone": agent.tz_name,
        "turns": turns,
        "actions": actions,
        "records_as_of": ended,
        "records_snapshot": snapshot,
    }
    _write_json_atomic(path, trace)


# Windows refuses to rename over a file another handle has open (e.g. the
# dashboard reading that call record right now); such a hold lasts
# milliseconds, so retry briefly instead of failing the customer's turn.
_REPLACE_TRIES = 5
_REPLACE_RETRY_S = 0.02


def _write_json_atomic(path: Path, data):
    """Write a JSON file so a reader never sees half of it.

    The web test call rewrites its record and trace after every turn; a crash
    or a full disk mid-write used to leave a truncated file. Writing a temp
    file in the same folder and renaming it over the old one is atomic: the
    reader sees either the old version or the new one.
    """
    _guard_write(path)
    tmp = path.with_name(path.name + ".tmp")
    with _write_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            for attempt in range(_REPLACE_TRIES):
                try:
                    os.replace(tmp, path)
                    break
                except PermissionError:
                    if attempt == _REPLACE_TRIES - 1:
                        raise
                    time.sleep(_REPLACE_RETRY_S)
        finally:
            tmp.unlink(missing_ok=True)


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


# ---- customer notifications log -------------------------------------------------

def log_notification(entry: dict):
    """Append one notification record (sent, dry-run, failed, skipped)."""
    _guard_write(NOTIFY_LOG)
    with _write_lock:
        with open(NOTIFY_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_notifications() -> list[dict]:
    """Every notification record, oldest first (small file; read on demand)."""
    if not NOTIFY_LOG.exists():
        return []
    with open(NOTIFY_LOG, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


BackgroundQueue = _BackgroundQueue      # for other modules' off-the-call-path work


# ---- the optional perf log (VOXAGENT_PERF_LOG) -------------------------------------
# perf.py measures but never touches disk; when a path is configured, every
# finished span is appended here as one JSON line, on the background thread.

PERF_LOG_MAX_BYTES = 20 * 1024 * 1024   # then rolled to <name>.1 (one backup kept)


def _append_perf_line(item):
    path, line = item
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.stat().st_size >= PERF_LOG_MAX_BYTES:
            os.replace(path, path.with_name(path.name + ".1"))
    except FileNotFoundError:
        pass
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


_perf_log = _BackgroundQueue("perf-log", _append_perf_line, maxsize=10_000)


def enable_perf_log(path: str | Path | None):
    """Append every perf span to `path` as JSON lines; None/"" turns it off."""
    if not path:
        perf.set_sink(None)
        return
    path = Path(path)
    if not path.is_absolute():
        path = BASE_DIR / path
    _guard_write(path)   # refuse now, at startup, rather than silently later

    def sink(rec: dict):
        if not _perf_log.put((path, json.dumps(rec, ensure_ascii=False))):
            perf.event("perf_log.dropped")

    perf.set_sink(sink)


enable_perf_log(os.getenv("VOXAGENT_PERF_LOG", "").strip())


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


def main(argv=None) -> int:
    """`python storage.py export-csv PATH [--force]` / `import-sheet [--skip]`.
    Expected problems (no credentials, file exists) print one clear line and
    exit 1 — an operator command shouldn't answer with a Python traceback."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="VoxAgent storage tools")
    sub = parser.add_subparsers(dest="cmd", required=True)
    export = sub.add_parser("export-csv", help="write all bookings to a CSV (rollback path)")
    export.add_argument("path")
    export.add_argument("--force", action="store_true",
                        help="replace an existing file (it is backed up first)")
    sheet = sub.add_parser("import-sheet",
                           help="one-time import of bookings from the configured Google Sheet")
    sheet.add_argument("--skip", action="store_true",
                       help="record that the Sheet has no bookings to import")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "export-csv":
            count = export_bookings_csv(args.path, force=args.force)
            print(f"exported {count} booking(s) to {args.path}")
        elif args.cmd == "import-sheet":
            import_sheet(skip=args.skip)
            print("Sheet import " + ("skipped" if args.skip else "done") + "; new bookings are open.")
    except (RuntimeError, FileExistsError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
