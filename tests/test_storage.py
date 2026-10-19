"""Storage layer: the bookings database, Sheets copy, test mode, CSV round-trips
and call logs."""

import csv
import datetime as dt
import threading
import time

import pytest

import storage


# A date that is always in the future: availability ignores past bookings.
FUTURE = (dt.date.today() + dt.timedelta(days=30)).isoformat()


def booking(client="clinic_a", name="Ravi", date=FUTURE, time="09:30",
            status="confirmed"):
    return ["2026-07-07T10:00:00", client, name, "9876543210",
            "Cleaning", date, time, status]


def test_booking_roundtrip_and_client_filter(tmp_storage):
    where = storage.reserve_booking(booking())
    assert where == "bookings.db"   # test mode: no Sheets copy, ever
    rows = storage.read_bookings("clinic_a")
    # Same fields as the CSV era, plus the row id the owner's cancel button uses.
    assert [{k: r[k] for k in storage.BOOKING_HEADER} for r in rows] == \
        [dict(zip(storage.BOOKING_HEADER, booking()))]
    assert isinstance(rows[0]["id"], int)
    assert storage.read_bookings("other_client") == []
    assert storage.booked_pairs("clinic_a") == {(FUTURE, "09:30")}


def test_second_confirmed_booking_for_same_slot_is_refused(tmp_storage):
    assert storage.reserve_booking(booking(name="A")) is not None
    assert storage.reserve_booking(booking(name="B")) is None
    assert [r["name"] for r in storage.read_bookings("clinic_a")] == ["A"]
    # The guard is per business and per slot, and ignores cancelled rows.
    assert storage.reserve_booking(booking(client="clinic_b", name="C")) is not None
    assert storage.reserve_booking(booking(time="10:00", name="D")) is not None
    assert storage.reserve_booking(booking(name="E", status="cancelled")) is not None


def test_concurrent_reservations_for_one_slot_allow_exactly_one(tmp_storage):
    """Audit H2: many threads (each with its own SQLite connection, like
    FastAPI's thread pool) race for one slot. At most one may win."""
    results, start = [], threading.Barrier(20)

    def attempt(i):
        start.wait()
        results.append(storage.reserve_booking(booking(name=f"caller{i}")))

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(r is not None for r in results) == 1
    assert len(storage.read_bookings("clinic_a")) == 1


def test_legacy_csv_is_imported_once_and_left_untouched(tmp_storage):
    with open(storage.BOOKINGS_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(storage.BOOKING_HEADER)
        w.writerow(booking(name="First"))
        w.writerow(booking(name="DoubleBooked"))      # the old bug's leftovers
        w.writerow(booking(time="11:00", name="Other"))
    before = storage.BOOKINGS_CSV.read_bytes()

    rows = [(r["name"], r["status"]) for r in storage.read_bookings("clinic_a")]
    # the old bug's double-booking is kept for the owner to sort out, not dropped
    assert rows == [("First", "confirmed"), ("DoubleBooked", "conflict"), ("Other", "confirmed")]
    assert storage.BOOKINGS_CSV.read_bytes() == before

    storage.reserve_booking(booking(time="12:00", name="New"))
    assert storage.BOOKINGS_CSV.read_bytes() == before  # never written again
    storage._db_prepared.discard(str(storage.BOOKINGS_DB))  # simulate a restart
    storage._db_local.conn = None
    assert len(storage.read_bookings("clinic_a")) == 4     # not re-imported


class FakeWorksheet:
    def __init__(self, fail=False):
        self.rows, self.fail = [], fail

    def get_all_values(self):
        return [list(storage.BOOKING_HEADER)]   # header only: nothing to migrate

    def append_row(self, row):
        if self.fail:
            raise ConnectionError("network down")
        self.rows.append(list(row))


@pytest.fixture
def sheets_on(tmp_storage, monkeypatch):
    """Sheets configured and test mode lifted for the mirror only. The worksheet
    is a fake object: no network handle can be created."""
    creds = tmp_storage / "credentials.json"
    creds.write_text("{}")
    monkeypatch.setenv("GOOGLE_SHEETS_CREDENTIALS_PATH", str(creds))
    monkeypatch.setenv("SHEET_ID", "fake-sheet")
    monkeypatch.setattr(storage, "in_test_mode", lambda: False)

    def use(sheet, imported=True):
        monkeypatch.setattr(storage, "_sheet_handle", lambda *a: sheet)
        if imported:                       # most tests start after the one-time step
            storage.import_sheet(skip=True)
        return sheet
    return use


def test_sheet_gets_a_copy_but_is_never_the_source_of_truth(sheets_on):
    """Audit H3: in Sheets mode the booking used to go ONLY to the Sheet, so
    availability and the dashboard (reading the CSV) never saw it."""
    sheet = sheets_on(FakeWorksheet())
    assert storage.reserve_booking(booking()) == "bookings.db"
    assert storage._sheets_queue.drain(2) == 0
    assert sheet.rows == [booking()]
    assert storage.booked_pairs("clinic_a") == {(FUTURE, "09:30")}
    assert len(storage.read_bookings("clinic_a")) == 1
    assert storage.reserve_booking(booking(name="B")) is None   # still guarded
    assert len(sheet.rows) == 1                                 # refused row not copied


def test_sheet_failure_keeps_the_booking(sheets_on, monkeypatch):
    monkeypatch.setattr(storage, "SHEETS_RETRY_WAITS_S", (0.01, 0.01, 0.01))
    sheets_on(FakeWorksheet(fail=True))
    assert storage.reserve_booking(booking()) == "bookings.db"
    assert len(storage.read_bookings("clinic_a")) == 1
    assert storage._sheets_queue.drain(2) == 0


class SlowWorksheet(FakeWorksheet):
    """A Google API that takes `delay` seconds per append, and can fail a few
    times first. Records when each append started, to prove ordering."""

    def __init__(self, delay=0.0, fail_times=0):
        super().__init__()
        self.delay, self.fail_times, self.calls = delay, fail_times, 0

    def append_row(self, row):
        self.calls += 1
        # The booking is committed BEFORE any copy is attempted.
        assert storage.read_bookings(row[1]), "copy ran before the booking committed"
        time.sleep(self.delay)
        if self.calls <= self.fail_times:
            raise ConnectionError("Google said no")
        self.rows.append(list(row))


def test_a_slow_sheet_never_delays_the_booking(sheets_on):
    """Audit F1: the copy ran inside the booking, so a 1 s Google API made
    every phone caller on the server wait (5 s TTFA with 5 calls)."""
    sheet = sheets_on(SlowWorksheet(delay=1.5))
    t0 = time.perf_counter()
    assert storage.reserve_booking(booking()) == "bookings.db"
    # gstack-timing-ok: inline copy would take >= 1.5 s; the bound is 5x looser than normal
    assert time.perf_counter() - t0 < 0.5
    assert sheet.rows == []                      # still copying...
    assert storage._sheets_queue.drain(5) == 0
    assert sheet.rows == [booking()]             # ...and then it lands


def test_a_failing_copy_is_retried_then_dropped_and_counted(sheets_on, monkeypatch, capsys):
    import perf
    perf.reset()
    monkeypatch.setattr(storage, "SHEETS_RETRY_WAITS_S", (0.01, 0.01, 0.01))
    sheet = sheets_on(SlowWorksheet(fail_times=99))
    storage.reserve_booking(booking())
    assert storage._sheets_queue.drain(3) == 0
    assert sheet.calls == 4                      # 1 try + 3 retries
    assert perf.snapshot()["events"]["sheets.dropped"] == 1
    log = capsys.readouterr().out
    assert "dropped after 4 tries" in log and "safe in bookings.db" in log
    assert "Ravi" not in log and "9876543210" not in log      # no customer details


def test_a_flaky_copy_succeeds_on_retry(sheets_on, monkeypatch):
    monkeypatch.setattr(storage, "SHEETS_RETRY_WAITS_S", (0.01, 0.01, 0.01))
    sheet = sheets_on(SlowWorksheet(fail_times=2))
    storage.reserve_booking(booking())
    assert storage._sheets_queue.drain(3) == 0
    assert sheet.rows == [booking()] and sheet.calls == 3


def test_a_full_copy_queue_drops_without_blocking(sheets_on, monkeypatch, capsys):
    import perf
    perf.reset()
    gate = threading.Event()

    class Stuck(FakeWorksheet):
        def append_row(self, row):
            gate.wait(5)
            self.rows.append(list(row))

    small = storage._BackgroundQueue("sheets-test", storage._copy_to_sheet, maxsize=1)
    monkeypatch.setattr(storage, "_sheets_queue", small)
    sheet = sheets_on(Stuck())
    t0 = time.perf_counter()
    times = [f"{9 + i}:00".zfill(5) for i in range(4)]
    for t in times:
        assert storage.reserve_booking(booking(time=t)) == "bookings.db"
    assert time.perf_counter() - t0 < 0.5        # never waited for the stuck Sheet
    assert len(storage.read_bookings("clinic_a")) == 4   # every booking is real
    assert perf.snapshot()["events"]["sheets.dropped"] >= 2
    assert "queue full" in capsys.readouterr().out
    gate.set()
    assert small.drain(3) == 0
    assert 1 <= len(sheet.rows) <= 2


def test_test_mode_never_copies_to_sheets_even_with_sheet_id(tmp_storage, monkeypatch):
    monkeypatch.setenv("GOOGLE_SHEETS_CREDENTIALS_PATH", __file__)  # exists
    monkeypatch.setenv("SHEET_ID", "a-real-business-sheet")
    touched = []
    monkeypatch.setattr(storage, "_sheet_handle", lambda *a: touched.append(a))
    assert storage.reserve_booking(booking()) == "bookings.db"
    assert touched == []


@pytest.mark.parametrize("attr", ["BOOKINGS_DB", "LEADS_CSV", "CALLS_DIR", "CLIENTS_DIR"])
def test_test_mode_refuses_to_write_real_data(tmp_storage, monkeypatch, attr):
    real = dict(zip(["BOOKINGS_DB", "BOOKINGS_CSV", "LEADS_CSV", "CALLS_DIR", "CLIENTS_DIR"],
                    storage._REAL_DATA))[attr]
    monkeypatch.setattr(storage, attr, real)
    storage._db_local.conn = None
    write = {
        "BOOKINGS_DB": lambda: storage.reserve_booking(booking()),
        "LEADS_CSV": lambda: storage.save_lead("clinic_a", "K", "9998887776", "x"),
        "CALLS_DIR": lambda: storage.log_call_from_agent(StubAgent(1), "terminal", dt.datetime.now()),
        "CLIENTS_DIR": lambda: storage.write_client_config("zz_never_written", {}),
    }[attr]
    with pytest.raises(RuntimeError, match="VOXAGENT_ENV=test"):
        write()


def test_past_bookings_are_not_read_for_availability(tmp_storage):
    """Availability runs on every tool call; history only grows, so the query
    is bounded to today onwards (past slots are never offered anyway)."""
    past = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    storage.reserve_booking(booking(date=past))
    assert storage.booked_pairs("clinic_a") == set()
    assert len(storage.read_bookings("clinic_a")) == 1      # history still kept


def test_dashboard_etag_changes_after_a_booking(tmp_storage):
    first = storage.data_version("clinic_a")
    assert storage.data_version("clinic_a") == first           # stable when idle
    storage.reserve_booking(booking())
    assert storage.data_version("clinic_a") != first


def test_lead_roundtrip(tmp_storage):
    storage.save_lead("clinic_a", "Kiran", "9998887776", "braces", "evening call")
    lead = storage.read_leads("clinic_a")[0]
    assert lead["phone"] == "9998887776" and lead["note"] == "evening call"


class StubAgent:
    client_id = "clinic_a"

    def __init__(self, user_turns):
        self.history = [{"role": "user", "text": f"msg {i}"} for i in range(user_turns)]

    def transcript_text(self):
        return "Customer: hello\n\nAgent: hi\n"


def test_call_log_skips_empty_conversations(tmp_storage):
    storage.log_call_from_agent(StubAgent(0), "terminal", dt.datetime.now())
    assert storage.read_call_logs("clinic_a") == []


def test_call_log_roundtrip_newest_first(tmp_storage):
    t0 = dt.datetime.now()
    storage.log_call_from_agent(StubAgent(2), "terminal", t0, call_id="older")
    storage.log_call_from_agent(StubAgent(3), "web-test", t0 + dt.timedelta(minutes=5), call_id="newer")
    logs = storage.read_call_logs("clinic_a")
    assert [c["call_id"] for c in logs] == ["newer", "older"]
    assert logs[0]["turns"] == 3 and "Customer:" in logs[0]["transcript"]


def test_test_mode_refuses_the_real_accounts_database(monkeypatch):
    import auth

    monkeypatch.setattr(auth, "DB_FILE", auth._REAL_DB_FILE)
    monkeypatch.setattr(auth._local, "conn", None, raising=False)
    with pytest.raises(RuntimeError, match="VOXAGENT_ENV=test"):
        auth._db()


# ---- review fixes: migration safety (approved D1 #1-#4) -----------------------------

import sqlite3  # noqa: E402
import time as _time  # noqa: E402


def write_legacy_csv(rows):
    with open(storage.BOOKINGS_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(storage.BOOKING_HEADER)
        for r in rows:
            w.writerow(r)


def reopen():
    """What a restart (or another process) sees: no prepared DB, no connection."""
    storage._db_prepared.discard(str(storage.BOOKINGS_DB))
    storage._db_local.conn = None


def test_csv_import_is_all_or_nothing(tmp_storage, monkeypatch):
    """#1: a crash mid-import (after the first row went in) must leave nothing
    behind, so the retry can't duplicate the rows that had already gone in."""
    write_legacy_csv([booking(name="A", status="cancelled"),
                      booking(time="10:00", name="B", status="cancelled")])
    real, calls = storage._normalize_row, []

    def crash_on_second(r):
        calls.append(r)
        if len(calls) == 2:
            raise ValueError("crash after the first insert")
        return real(r)
    monkeypatch.setattr(storage, "_normalize_row", crash_on_second)
    storage.read_bookings("clinic_a")          # reads still work; the import failed
    assert storage.read_bookings("clinic_a") == []          # first insert rolled back
    monkeypatch.setattr(storage, "_normalize_row", real)
    reopen()
    assert sorted(r["name"] for r in storage.read_bookings("clinic_a")) == ["A", "B"]


def test_second_process_waits_for_an_import_in_progress(tmp_storage):
    """#1: another process is mid-import (holding the write lock). Opening the
    database here must wait for it and then NOT import again or crash."""
    write_legacy_csv([booking(name="A", status="cancelled")])
    other = sqlite3.connect(str(storage.BOOKINGS_DB), isolation_level=None, timeout=10,
                            check_same_thread=False)    # committed from another thread
    other.execute("PRAGMA journal_mode=WAL")
    other.executescript(storage._BOOKINGS_SCHEMA)
    other.execute("BEGIN IMMEDIATE")
    other.execute("INSERT INTO bookings (timestamp, client_id, name, phone, service, date, time,"
                  " status) VALUES (?,?,?,?,?,?,?,?)", tuple(booking(name="A", status="cancelled")))
    other.execute("INSERT INTO meta VALUES ('csv_imported', 'other process')")

    def finish_later():
        _time.sleep(0.3)
        other.execute("COMMIT")
    finisher = threading.Thread(target=finish_later)
    finisher.start()
    try:
        reopen()
        rows = storage.read_bookings("clinic_a")      # must not raise
        assert [r["name"] for r in rows] == ["A"]     # imported exactly once
    finally:
        finisher.join()
        other.close()


def test_legacy_double_bookings_are_kept_as_conflicts(tmp_storage):
    """#2: the old bug left two confirmed rows for one slot. Both customers
    are real; the second must stay visible (status 'conflict'), not vanish."""
    write_legacy_csv([booking(name="A"), booking(name="B")])
    rows = storage.read_bookings("clinic_a")
    assert {(r["name"], r["status"]) for r in rows} == {("A", "confirmed"), ("B", "conflict")}
    assert storage.booked_pairs("clinic_a") == {(FUTURE, "09:30")}


def test_legacy_rows_are_normalised_on_import(tmp_storage):
    """#2: hand-edited CSVs ('Confirmed ', ' 9:30') must still block the slot."""
    write_legacy_csv([["2026-07-07T10:00:00", " clinic_a ", "Ravi", "9876543210",
                       "Cleaning", f" {FUTURE} ", " 9:30 ", " Confirmed "]])
    assert storage.booked_pairs("clinic_a") == {(FUTURE, "09:30")}
    assert storage.reserve_booking(booking(name="New")) is None


class SheetWithHistory(FakeWorksheet):
    def __init__(self, rows=()):
        super().__init__()
        self.values = [list(storage.BOOKING_HEADER)] + [list(r) for r in rows]

    def get_all_values(self):
        return [list(r) for r in self.values]


def test_bookings_pause_until_the_sheet_import_has_run(sheets_on):
    """D5: SHEET_ID set and its old bookings not yet imported -> new bookings
    pause (they could double-book one of them); reads keep working; the
    reason is visible for /admin. No network call is ever made here."""
    sheets_on(SheetWithHistory([booking(name="FromSheet")]), imported=False)
    with pytest.raises(storage.BookingsUnavailable):
        storage.reserve_booking(booking(time="11:00", name="New"))
    assert storage.read_bookings("clinic_a") == []
    assert "import-sheet" in storage.bookings_paused_reason()


def test_import_sheet_brings_in_sheet_only_bookings_with_text_intact(sheets_on):
    """D5: the old code wrote bookings ONLY to the Sheet. Values are read as
    text (get_all_values), so '+91...' phone numbers survive."""
    row = booking(name="FromSheet")
    row[3] = "+919876543210"
    sheets_on(SheetWithHistory([row]), imported=False)
    assert storage.import_sheet()[0] == 1
    assert storage.bookings_paused_reason() is None
    got = storage.read_bookings("clinic_a")
    assert [(r["name"], r["phone"]) for r in got] == [("FromSheet", "+919876543210")]
    assert storage.reserve_booking(booking(name="Late")) is None      # slot is taken
    assert storage.import_sheet() is None                              # already done


def test_import_sheet_skip_resumes_bookings_without_importing(sheets_on):
    sheets_on(SheetWithHistory([booking(name="FromSheet")]), imported=False)
    storage.import_sheet(skip=True)
    assert storage.reserve_booking(booking(name="New")) is not None
    assert [r["name"] for r in storage.read_bookings("clinic_a")] == ["New"]


def test_missing_credentials_keep_bookings_paused(sheets_on, monkeypatch):
    """Cycle-2 finding: missing credentials.json used to let bookings through."""
    sheets_on(SheetWithHistory([booking(name="FromSheet")]), imported=False)
    monkeypatch.setenv("GOOGLE_SHEETS_CREDENTIALS_PATH", "/nonexistent/credentials.json")
    with pytest.raises(storage.BookingsUnavailable):
        storage.reserve_booking(booking(name="New"))
    with pytest.raises(RuntimeError, match="credentials"):
        storage.import_sheet()


def test_export_csv_backs_up_and_round_trips(tmp_storage):
    """Rollback path: export every booking (all columns); never lose an
    existing file — it is backed up before being replaced."""
    storage.reserve_booking(booking(name="A"))
    storage.reserve_booking(booking(time="10:00", name="B"))
    out = tmp_storage / "export.csv"
    out.write_text("previous contents")
    with pytest.raises(FileExistsError):
        storage.export_bookings_csv(out)                 # never overwrite silently
    assert storage.export_bookings_csv(out, force=True) == 2
    backups = list(tmp_storage.glob("export.csv.bak-*"))
    assert len(backups) == 1 and backups[0].read_text() == "previous contents"
    with open(out, newline="", encoding="utf-8") as f:
        assert list(csv.DictReader(f)) == [{k: r[k] for k in storage.BOOKING_HEADER}
                                           for r in storage.read_bookings("clinic_a")]


def test_roll_forward_after_rollback_picks_up_new_csv_rows(tmp_storage):
    """Cycle-2 finding: after export -> old code appends to bookings.csv ->
    upgrade again, those new bookings were never imported (marker)."""
    storage.reserve_booking(booking(name="A"))
    storage.export_bookings_csv(storage.BOOKINGS_CSV, force=True)
    with open(storage.BOOKINGS_CSV, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(booking(time="10:00", name="DuringRollback"))
    reopen()
    names = [r["name"] for r in storage.read_bookings("clinic_a")]
    assert names == ["A", "DuringRollback"]           # new row in, A not duplicated
    assert (FUTURE, "10:00") in storage.booked_pairs("clinic_a")


def test_excel_saved_csv_still_imports(tmp_storage):
    """Windows Excel saves CSV as cp1252, not UTF-8."""
    with open(storage.BOOKINGS_CSV, "w", newline="", encoding="cp1252") as f:
        w = csv.writer(f)
        w.writerow(storage.BOOKING_HEADER)
        w.writerow(booking(name="Ren\u00e9e"))
    assert [r["name"] for r in storage.read_bookings("clinic_a")] == ["Ren\u00e9e"]


def test_unreadable_csv_pauses_bookings_but_not_reads(tmp_storage, monkeypatch):
    """Cycle-2 finding: a broken bookings.csv made the whole database unusable."""
    write_legacy_csv([booking(name="A")])

    def broken_reader(f):
        raise csv.Error("line contains NUL")
    monkeypatch.setattr(storage.csv, "DictReader", broken_reader)
    assert storage.read_bookings("clinic_a") == []
    assert "bookings.csv" in storage.bookings_paused_reason()
    with pytest.raises(storage.BookingsUnavailable):
        storage.reserve_booking(booking(time="11:00", name="New"))


def test_unparseable_legacy_rows_are_kept_not_dropped(tmp_storage):
    """A date Excel rewrote (10/07/2026) is still a real customer: keep the
    row as status 'invalid' (visible, exported) instead of dropping it."""
    write_legacy_csv([["t", "clinic_a", "Kiran", "9876543210", "Cleaning",
                       "10/07/2026", "10:00", "confirmed"]])
    rows = storage.read_bookings("clinic_a")
    assert [(r["name"], r["status"], r["date"]) for r in rows] == [("Kiran", "invalid", "10/07/2026")]
    assert storage.booked_pairs("clinic_a") == set()


def test_legacy_dates_are_stored_in_canonical_form(tmp_storage):
    compact = FUTURE.replace("-", "")                  # e.g. 20261113, valid ISO
    write_legacy_csv([["t", "clinic_a", "Ravi", "9876543210", "Cleaning",
                       compact, "09:30", "confirmed"]])
    assert storage.booked_pairs("clinic_a") == {(FUTURE, "09:30")}


# ---- QA findings (browser QA of the hardened branch) -----------------------------

def test_storage_cli_reports_errors_without_a_traceback(sheets_on, monkeypatch, capsys):
    """QA: `python storage.py import-sheet` without credentials printed a raw
    Python traceback; an operator command should say what to fix."""
    sheets_on(SheetWithHistory(), imported=False)
    monkeypatch.setenv("GOOGLE_SHEETS_CREDENTIALS_PATH", "/nonexistent/credentials.json")
    assert storage.main(["import-sheet"]) == 1
    out = capsys.readouterr()
    assert "Error:" in out.err and "credentials" in out.err and "Traceback" not in out.err
    assert storage.main(["import-sheet", "--skip"]) == 0


def test_sheets_usable_requires_the_credentials_file(sheets_on, monkeypatch):
    """QA: /admin showed Google Sheets green with SHEET_ID set but no credentials."""
    sheets_on(SheetWithHistory())
    assert storage.sheets_usable() is True
    monkeypatch.setenv("GOOGLE_SHEETS_CREDENTIALS_PATH", "/nonexistent/credentials.json")
    assert storage.sheets_usable() is False


# ---- call traces (eng review E3, D7) --------------------------------------------------

import json  # noqa: E402

from agent import ReceptionistAgent  # noqa: E402
from conftest import open_day, open_times  # noqa: E402


def booked_conversation(fake_llm, name="Ravi", phone="+91 98765 43210"):
    date = open_day()
    slot = open_times(date=date)[0]
    agent = ReceptionistAgent("demo_clinic", llm=fake_llm([
        {"text": None, "tool_calls": [{"name": "check_availability", "args": {"date": date}}]},
        {"text": f"{slot} is free.", "tool_calls": []},
        {"text": None, "tool_calls": [{"name": "book_appointment", "args": {
            "customer_name": name, "phone": phone, "service": "Cleaning",
            "date": date, "time": slot}}]},
        {"text": "You're booked!", "tool_calls": []},
    ]))
    agent.chat("any slots?")
    agent.chat("book the first one")
    return agent, date, slot


def read_trace(call_id="c1"):
    return json.loads((storage.CALLS_DIR / "demo_clinic" / "traces" / f"{call_id}.json").read_text())


def test_trace_records_turns_actions_and_the_booking_snapshot(tmp_storage, fake_llm):
    agent, date, slot = booked_conversation(fake_llm)
    storage.save_lead("demo_clinic", "Ravi", "9876543210", "whitening", "")
    storage.log_call_from_agent(agent, "web-test", dt.datetime.now(), call_id="c1")

    trace = read_trace()
    assert trace["trace_version"] == 1 and trace["timezone"] == "Asia/Kolkata"
    assert dt.datetime.fromisoformat(trace["started_at"]).utcoffset() is not None
    assert [t["speaker"] for t in trace["turns"]] == ["caller", "agent", "caller", "agent"]
    book = trace["actions"][1]
    assert (book["type"], book["ok"], book["args"]["time"]) == ("book", True, slot)
    # The booking belongs to the agent turn that announces it ("You're booked!").
    assert trace["turns"][book["turn_index"]]["text"] == "You're booked!"
    kinds = [(r["kind"], r["date"] if r["kind"] == "booking" else r["phone"])
             for r in trace["records_snapshot"]]
    assert ("booking", date) in kinds and ("lead", "9876543210") in kinds


def test_failed_booking_is_recorded_as_not_ok(tmp_storage, fake_llm):
    agent = ReceptionistAgent("demo_clinic", llm=fake_llm([
        {"text": None, "tool_calls": [{"name": "book_appointment", "args": {
            "customer_name": "A", "phone": "123", "service": "x", "date": open_day(),
            "time": "03:00"}}]},
        {"text": "That slot is taken.", "tool_calls": []},
    ]))
    agent.chat("book 3am")
    storage.log_call_from_agent(agent, "web-test", dt.datetime.now(), call_id="c1")
    action = read_trace()["actions"][0]
    assert action["type"] == "book" and action["ok"] is False
    assert read_trace()["records_snapshot"] == []


def test_traces_do_not_count_as_calls_or_reach_the_dashboard(tmp_storage, fake_llm):
    """Eng review D7: read_call_logs treats every *.json in the folder as a
    call, and the dashboard ships call records to the browser."""
    agent, _, _ = booked_conversation(fake_llm)
    storage.log_call_from_agent(agent, "web-test", dt.datetime.now(), call_id="c1")
    calls = storage.read_call_logs("demo_clinic")
    assert len(calls) == 1
    assert "actions" not in calls[0] and "records_snapshot" not in calls[0]


def test_a_trace_failure_never_costs_the_call_record(tmp_storage, fake_llm, monkeypatch, capsys):
    agent, _, _ = booked_conversation(fake_llm)

    def broken(*a, **k):
        raise RuntimeError("bug in trace builder")
    monkeypatch.setattr(storage, "_write_trace", broken)
    storage.log_call_from_agent(agent, "web-test", dt.datetime.now(), call_id="c1")
    assert len(storage.read_call_logs("demo_clinic")) == 1
    assert "trace for call c1 not written: RuntimeError" in capsys.readouterr().out


def test_text_sent_with_a_tool_call_is_not_a_spoken_turn(tmp_storage, fake_llm):
    """Review C1: Gemini can return text AND a function call in one reply.
    agent.chat never shows that text to the customer, so the trace must not
    record it as something the agent said (it would invent a claim and shift
    the booking to the wrong turn)."""
    date = open_day()
    slot = open_times(date=date)[0]
    agent = ReceptionistAgent("demo_clinic", llm=fake_llm([
        {"text": "I've booked you!", "tool_calls": [{"name": "book_appointment", "args": {
            "customer_name": "Ravi", "phone": "9876543210", "service": "Cleaning",
            "date": date, "time": slot}}]},
        {"text": "Done, see you then.", "tool_calls": []},
    ]))
    assert agent.chat("book me") == "Done, see you then."
    storage.log_call_from_agent(agent, "web-test", dt.datetime.now(), call_id="c1")
    trace = read_trace()
    assert [t["text"] for t in trace["turns"]] == ["book me", "Done, see you then."]
    assert trace["actions"][0]["turn_index"] == 1


def test_an_interrupted_rewrite_keeps_the_previous_record_and_trace(tmp_storage, fake_llm, monkeypatch):
    """Review I3: the web test call rewrites its call record and trace after
    every turn. A crash mid-write used to leave a truncated file, which the
    dashboard silently drops and the checker cannot read."""
    agent, _, _ = booked_conversation(fake_llm)
    storage.log_call_from_agent(agent, "web-test", dt.datetime.now(), call_id="c1")
    before = (storage.CALLS_DIR / "demo_clinic" / "c1.json").read_text()

    real_dump = json.dump

    def dies_halfway(obj, f, **kw):
        f.write('{"partial": ')
        raise OSError("disk full")
    monkeypatch.setattr(storage.json, "dump", dies_halfway)
    with pytest.raises(OSError):
        storage.log_call_from_agent(agent, "web-test", dt.datetime.now(), call_id="c1")
    monkeypatch.setattr(storage.json, "dump", real_dump)

    assert (storage.CALLS_DIR / "demo_clinic" / "c1.json").read_text() == before
    assert read_trace()["call_id"] == "c1"          # previous trace still parses
    assert not list((storage.CALLS_DIR / "demo_clinic").rglob("*.tmp"))


def test_snapshot_holds_only_this_business_this_call_s_dates_and_phones(tmp_storage, fake_llm):
    """Review I8: a trace must never carry another business's rows, cancelled
    bookings, other days, or leads from unrelated people."""
    agent, date, slot = booked_conversation(fake_llm)
    other_day = open_day(skip=1)
    now = dt.datetime.now().isoformat(timespec="seconds")
    other_slot = open_times(date=date)[1]
    storage.reserve_booking([now, "lakshmi_beauty_salon", "Other Biz", "9000000001", "x", date, slot, "confirmed"])
    storage.reserve_booking([now, "demo_clinic", "Cancelled", "9000000002", "x", date, other_slot, "cancelled"])
    storage.reserve_booking([now, "demo_clinic", "Other Day", "9000000003", "x", other_day, slot, "confirmed"])
    storage.save_lead("demo_clinic", "Stranger", "9000000004", "braces", "")
    storage.save_lead("demo_clinic", "Ravi again", "09876543210", "whitening", "")  # same number, other spelling
    storage.save_lead("lakshmi_beauty_salon", "Same phone, other biz", "9876543210", "hair", "")
    storage.log_call_from_agent(agent, "phone", dt.datetime.now(), call_id="c1", caller="+91 98765 43210")

    rows = read_trace()["records_snapshot"]
    names = sorted(r["name"] for r in rows)
    assert names == ["Ravi", "Ravi again"]
    assert {(r["kind"], r["date"] if r["kind"] == "booking" else r["phone"]) for r in rows} == {
        ("booking", date), ("lead", "09876543210")}


def test_other_customers_appear_in_the_snapshot_only_as_taken_slots(tmp_storage, fake_llm):
    """Review I1: the snapshot used to copy every same-day customer's name and
    phone into every trace, where deleting a booking never removed them. The
    checker only needs to know those slots were taken."""
    agent, date, slot = booked_conversation(fake_llm)
    other_slot = open_times(date=date)[1]
    now = dt.datetime.now().isoformat(timespec="seconds")
    storage.reserve_booking([now, "demo_clinic", "Meena", "9000000009", "Filling", date, other_slot, "confirmed"])
    storage.log_call_from_agent(agent, "web-test", dt.datetime.now(), call_id="c1")

    rows = {r["time"]: r for r in read_trace()["records_snapshot"] if r["kind"] == "booking"}
    assert rows[other_slot] == {"kind": "booking", "date": date, "time": other_slot, "status": "confirmed"}
    assert rows[slot]["name"] == "Ravi" and rows[slot]["phone"] == "+91 98765 43210"


@pytest.mark.parametrize("configured,tz_database", [("Not/AZone", True), (None, False)],
                         ids=["typo-in-yaml", "no-tz-database"])
def test_trace_names_the_timezone_by_its_iana_name(tmp_storage, fake_llm, monkeypatch,
                                                    configured, tz_database):
    """Review I2: the fallback wrote "IST" into the trace instead of the
    documented IANA name. Both a YAML typo and a machine without a timezone
    database (Windows without tzdata) must still say Asia/Kolkata, +05:30."""
    import agent as agent_module
    if not tz_database:
        def no_db(name):
            raise agent_module.ZoneInfoNotFoundError(name)
        monkeypatch.setattr(agent_module, "ZoneInfo", no_db)
    config = dict(storage.read_client_config("demo_clinic"))
    if configured:
        config["timezone"] = configured
    monkeypatch.setattr(storage, "read_client_config", lambda cid: config)
    agent, _, _ = booked_conversation(fake_llm)
    storage.log_call_from_agent(agent, "web-test", dt.datetime.now(), call_id="c1")
    trace = read_trace()
    assert trace["timezone"] == "Asia/Kolkata"
    assert dt.datetime.fromisoformat(trace["ended_at"]).utcoffset() == dt.timedelta(hours=5, minutes=30)


def test_trace_builder_pairs_calls_results_and_success_flags():
    """Review I7: two same-name tool calls in one reply each keep their own
    arguments; save_lead's "saved" is success; a raised tool is a failure."""
    history = [
        {"role": "user", "text": "slots on two days, and call me back", "at": "t0"},
        {"role": "assistant", "text": None, "at": "t1", "tool_calls": [
            {"name": "check_availability", "args": {"date": "2026-10-20"}},
            {"name": "check_availability", "args": {"date": "2026-10-21"}},
            {"name": "save_lead", "args": {"phone": "9876543210"}}]},
        {"role": "tool", "name": "check_availability", "result": {"date": "2026-10-20"}, "at": "t2"},
        {"role": "tool", "name": "check_availability", "result": {"error": "OperationalError: locked"}, "at": "t3"},
        {"role": "tool", "name": "save_lead", "result": {"status": "saved"}, "at": "t4"},
        {"role": "assistant", "text": "Done.", "at": "t5"},
    ]
    turns, actions = storage._trace_turns_and_actions(history)
    assert [t["speaker"] for t in turns] == ["caller", "agent"]
    assert [a["args"].get("date") for a in actions] == ["2026-10-20", "2026-10-21", None]
    assert [(a["type"], a["ok"]) for a in actions] == [
        ("availability", True), ("availability", False), ("lead", True)]
    assert all(a["turn_index"] == 1 for a in actions)


def test_atomic_write_survives_a_reader_holding_the_file_on_windows(tmp_storage, fake_llm, monkeypatch):
    """Cycle-2 review: on Windows, renaming over a file another handle has open
    raises PermissionError. The dashboard can be reading a call record at the
    moment /api/chat rewrites it; that must not turn a good reply into the
    "line is busy" fallback."""
    agent, _, _ = booked_conversation(fake_llm)
    real_replace, calls = storage.os.replace, []

    def busy_once(src, dst):
        calls.append(dst)
        if len(calls) == 1:
            raise PermissionError(13, "file in use")
        real_replace(src, dst)
    monkeypatch.setattr(storage.os, "replace", busy_once)
    monkeypatch.setattr(storage, "_REPLACE_RETRY_S", 0)
    storage.log_call_from_agent(agent, "web-test", dt.datetime.now(), call_id="c1")
    assert len(storage.read_call_logs("demo_clinic")) == 1
    assert read_trace()["call_id"] == "c1"


class ReadTimeout(Exception):
    """Same name as requests.exceptions.ReadTimeout, which gspread raises when
    Google takes longer than the read timeout to answer."""


def test_a_read_timeout_is_not_retried_so_the_sheet_never_gets_a_duplicate(
        sheets_on, monkeypatch, capsys):
    """Review D3: Google can apply an append and answer too late. Retrying
    then appended the booking twice, which reads as a double booking."""
    import perf
    perf.reset()
    monkeypatch.setattr(storage, "SHEETS_RETRY_WAITS_S", (0.01, 0.01, 0.01))

    class AppliedButSlow(FakeWorksheet):
        calls = 0

        def append_row(self, row):
            AppliedButSlow.calls += 1
            self.rows.append(list(row))          # Google applied it...
            if AppliedButSlow.calls == 1:
                raise ReadTimeout("read timed out")   # ...but answered too late

    sheet = sheets_on(AppliedButSlow())
    storage.reserve_booking(booking())
    assert storage._sheets_queue.drain(3) == 0
    assert sheet.rows == [booking()]             # once, not twice
    assert perf.snapshot()["events"]["sheets.unconfirmed"] == 1
    assert "may or may not have landed" in capsys.readouterr().out


def test_a_connection_error_is_still_retried(sheets_on, monkeypatch):
    monkeypatch.setattr(storage, "SHEETS_RETRY_WAITS_S", (0.01, 0.01, 0.01))
    sheet = sheets_on(SlowWorksheet(fail_times=1))   # ConnectionError: never reached Google
    storage.reserve_booking(booking())
    assert storage._sheets_queue.drain(3) == 0
    assert sheet.rows == [booking()] and sheet.calls == 2


def test_the_in_process_insert_lock_is_never_waited_on_for_long(tmp_storage, monkeypatch):
    """Review D4: the lock was held across SQLite's 10 s busy wait, so with an
    outside writer holding the database, bookings queued one behind another
    (N x 10 s). Waiting for the lock is capped; SQLite's own wait remains."""
    monkeypatch.setattr(storage, "BOOKING_LOCK_WAIT_S", 0.1)
    storage._bookings_db()                       # create the database first
    storage._booking_insert_lock.acquire()       # another booking thread is stuck
    try:
        t0 = time.perf_counter()
        assert storage.reserve_booking(booking()) == "bookings.db"
        assert time.perf_counter() - t0 < 1.0
    finally:
        storage._booking_insert_lock.release()


def test_the_write_guard_checks_the_path_actually_opened(tmp_storage, monkeypatch):
    """The guard used to re-read BOOKINGS_DB after the path was taken, so a
    path swapped in between (a late thread at a test boundary) slipped past."""
    real = storage._REAL_DATA[0]
    existed = real.exists()                        # a working checkout may have one
    reads = iter([real, tmp_storage / "elsewhere.db"])

    class Flip:                                    # first read: real, second: harmless
        def __fspath__(self):
            return str(next(reads))

        def __str__(self):
            return self.__fspath__()
    monkeypatch.setattr(storage, "BOOKINGS_DB", Flip())
    storage._db_local.__dict__.clear()
    with pytest.raises(RuntimeError, match="refuses"):
        storage._bookings_db()
    assert real.exists() == existed                # never created by a test


def test_a_timeout_while_opening_the_sheet_is_still_retried(sheets_on, monkeypatch):
    """Only an append can have landed; a read timeout while (re)opening the
    sheet never reached append_row, so it is retried like any failure."""
    monkeypatch.setattr(storage, "SHEETS_RETRY_WAITS_S", (0.01, 0.01, 0.01))
    sheet = FakeWorksheet()
    opens = []

    def handle(*a):
        opens.append(1)
        if len(opens) == 1:
            raise ReadTimeout("opening timed out")
        return sheet
    sheets_on(sheet)
    monkeypatch.setattr(storage, "_sheet_handle", handle)
    storage.reserve_booking(booking())
    assert storage._sheets_queue.drain(3) == 0
    assert sheet.rows == [booking()] and len(opens) == 2
