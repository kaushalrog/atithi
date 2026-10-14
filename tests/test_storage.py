"""Storage layer: the bookings database, Sheets copy, test mode, CSV round-trips
and call logs."""

import csv
import datetime as dt
import threading

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
    assert rows == [dict(zip(storage.BOOKING_HEADER, booking()))]  # same shape as the CSV era
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
    assert storage.reserve_booking(booking()) == "bookings.db + Google Sheet copy"
    assert sheet.rows == [booking()]
    assert storage.booked_pairs("clinic_a") == {(FUTURE, "09:30")}
    assert len(storage.read_bookings("clinic_a")) == 1
    assert storage.reserve_booking(booking(name="B")) is None   # still guarded
    assert len(sheet.rows) == 1                                 # refused row not copied


def test_sheet_failure_keeps_the_booking(sheets_on):
    sheets_on(FakeWorksheet(fail=True))
    assert storage.reserve_booking(booking()) == "bookings.db"
    assert len(storage.read_bookings("clinic_a")) == 1


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
        assert list(csv.DictReader(f)) == storage.read_bookings("clinic_a")


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
