"""Storage layer: the bookings database, Sheets copy, test mode, CSV round-trips
and call logs."""

import csv
import datetime as dt
import threading

import pytest

import storage


def booking(client="clinic_a", name="Ravi", date="2026-07-09", time="09:30",
            status="confirmed"):
    return ["2026-07-07T10:00:00", client, name, "9876543210",
            "Cleaning", date, time, status]


def test_booking_roundtrip_and_client_filter(tmp_storage):
    where = storage.reserve_booking(booking())
    assert where == "bookings.db"   # test mode: no Sheets copy, ever
    rows = storage.read_bookings("clinic_a")
    assert rows == [dict(zip(storage.BOOKING_HEADER, booking()))]  # same shape as the CSV era
    assert storage.read_bookings("other_client") == []
    assert storage.booked_pairs("clinic_a") == {("2026-07-09", "09:30")}


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

    names = [r["name"] for r in storage.read_bookings("clinic_a")]
    assert names == ["First", "Other"]                 # duplicate skipped, not fatal
    assert storage.BOOKINGS_CSV.read_bytes() == before

    storage.reserve_booking(booking(time="12:00", name="New"))
    assert storage.BOOKINGS_CSV.read_bytes() == before  # never written again
    storage._db_prepared.discard(str(storage.BOOKINGS_DB))  # simulate a restart
    storage._db_local.conn = None
    assert len(storage.read_bookings("clinic_a")) == 3     # not re-imported


class FakeWorksheet:
    def __init__(self, fail=False):
        self.rows, self.fail = [], fail

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

    def use(sheet):
        monkeypatch.setattr(storage, "_sheet_handle", lambda *a: sheet)
        return sheet
    return use


def test_sheet_gets_a_copy_but_is_never_the_source_of_truth(sheets_on):
    """Audit H3: in Sheets mode the booking used to go ONLY to the Sheet, so
    availability and the dashboard (reading the CSV) never saw it."""
    sheet = sheets_on(FakeWorksheet())
    assert storage.reserve_booking(booking()) == "bookings.db + Google Sheet copy"
    assert sheet.rows == [booking()]
    assert storage.booked_pairs("clinic_a") == {("2026-07-09", "09:30")}
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
