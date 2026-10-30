"""Retention and deletion (owner decision 2026-10-21, docs/DATA_HANDLING.md).
Synthetic data in temp storage only: never real customer records."""

import datetime as dt
import json

import pytest

import storage
from agent import ReceptionistAgent
from conftest import FakeLLM, open_day, open_times

NOW = dt.datetime(2026, 10, 30, 12, 0)
OLD, NEW = NOW - dt.timedelta(days=400), NOW - dt.timedelta(days=5)
PRIYA, RAVI = "9876543210", "9123456789"


def write_call(cid, started, caller="", transcript=""):
    folder = storage.CALLS_DIR / "demo_clinic"
    (folder / "traces").mkdir(parents=True, exist_ok=True)
    rec = {"call_id": cid, "client_id": "demo_clinic", "started": started.isoformat(timespec="seconds"),
           "seconds": 10, "turns": 1, "transcript": transcript, "caller": caller}
    (folder / f"{cid}.json").write_text(json.dumps(rec))
    (folder / "traces" / f"{cid}.json").write_text("{}")


def add_lead(ts, phone):
    storage._append_csv(storage.LEADS_CSV, storage.LEAD_HEADER,
                        [ts.isoformat(timespec="seconds"), "demo_clinic", "X", phone, "braces", ""])


@pytest.fixture
def data(tmp_storage):
    write_call("old", OLD, transcript="Customer: hi")
    write_call("new", NEW, transcript="Customer: hi")
    add_lead(OLD, PRIYA)
    add_lead(NEW, RAVI)
    conn = storage._bookings_db()
    with storage._transaction(conn):
        for date, phone in (("2025-06-01", PRIYA), ("2026-10-25", RAVI)):
            conn.execute("INSERT INTO bookings (timestamp, client_id, name, phone, service, date, time, status) "
                         "VALUES ('t','demo_clinic','Name',?,'Cleaning',?,'10:00','confirmed')", (phone, date))
        conn.execute("INSERT INTO questions (client_id, question, norm, first_asked, last_asked) "
                     "VALUES ('demo_clinic','old?','old',?,?)", (OLD.isoformat(), OLD.isoformat()))
    storage.queue_callback("demo_clinic", PRIYA, "missed call", now=OLD)
    old_at = (NOW - dt.timedelta(days=60)).astimezone().isoformat(timespec="seconds")
    storage.log_notification({"at": old_at, "to": "+91" + PRIYA, "status": "dry-run"})
    storage.log_notification({"at": NOW.astimezone().isoformat(timespec="seconds"), "to": "+91" + RAVI,
                              "status": "dry-run"})
    storage.clear_caches()


def test_a_dry_run_counts_and_changes_nothing(data):
    counts = storage.purge_expired(NOW, dry_run=True)
    assert counts == {"calls": 1, "leads": 1, "booking_contact": 1, "questions": 1,
                      "callbacks": 1, "notifications": 1}
    assert len(storage.read_call_logs("demo_clinic")) == 2 and len(storage.read_leads("demo_clinic")) == 2


def test_purge_removes_only_what_is_past_retention(data):
    storage.purge_expired(NOW)
    assert [c["call_id"] for c in storage.read_call_logs("demo_clinic")] == ["new"]
    assert not (storage.CALLS_DIR / "demo_clinic" / "traces" / "old.json").exists()
    assert [l["phone"] for l in storage.read_leads("demo_clinic")] == [RAVI]
    rows = {r["date"]: (r["name"], r["phone"]) for r in storage.read_bookings("demo_clinic")}
    assert rows["2025-06-01"] == ("", "") and rows["2026-10-25"] == ("Name", RAVI)
    assert storage.open_questions("demo_clinic") == []
    assert storage.read_callbacks("demo_clinic") == []
    assert [n["to"] for n in storage.read_notifications()] == ["+91" + RAVI]
    assert all(v == 0 for v in storage.purge_expired(NOW).values())     # idempotent


def test_periods_can_be_changed_per_kind(data, monkeypatch):
    monkeypatch.setenv("VOXAGENT_RETAIN_CALLS_DAYS", "2")
    assert storage.retention_days()["calls"] == 2
    assert storage.purge_expired(NOW, dry_run=True)["calls"] == 2
    monkeypatch.setenv("VOXAGENT_RETAIN_CALLS_DAYS", "nonsense")
    assert storage.retention_days()["calls"] == 90


def test_deleting_a_customer_removes_them_everywhere(data):
    write_call("mentions", NEW, transcript="Customer: my number is 98765 43210")
    write_call("caller", NEW, caller="+919876543210")
    counts = storage.delete_customer("+91 98765 43210")
    assert counts["leads"] == 1 and counts["calls"] == 2 and counts["callbacks"] == 1
    assert counts["notifications"] == 1 and counts["bookings_anonymised"] == 1
    assert {c["call_id"] for c in storage.read_call_logs("demo_clinic")} == {"old", "new"}
    assert all(storage._phone10(l["phone"]) != PRIYA for l in storage.read_leads("demo_clinic"))
    assert all(storage._phone10(b["phone"]) != PRIYA for b in storage.read_bookings("demo_clinic"))
    assert [n["to"] for n in storage.read_notifications()] == ["+91" + RAVI]   # Ravi untouched


def test_a_future_booking_of_a_deleted_customer_is_cancelled(tmp_storage):
    day = open_day(); t = open_times(date=day)[0]
    a = ReceptionistAgent("demo_clinic", llm=FakeLLM([]))
    a.run_tool({"name": "book_appointment", "args": {"customer_name": "Priya", "phone": PRIYA,
                                                     "service": "Cleaning", "date": day, "time": t}})
    assert storage.delete_customer(PRIYA)["future_bookings_cancelled"] == 1
    [b] = storage.read_bookings("demo_clinic")
    assert (b["status"], b["name"], b["phone"]) == ("cancelled", "", "")


def test_delete_needs_a_full_number_and_can_be_scoped(data):
    with pytest.raises(ValueError):
        storage.delete_customer("3210")
    assert storage.delete_customer(PRIYA, client_id="lakshmi_beauty_salon", dry_run=True)["leads"] == 0


def test_the_worker_never_runs_in_tests(tmp_storage):
    import threading
    assert storage.start_retention_worker(threading.Event()) is None


def test_console_logs_mask_customer_details(tmp_storage, capsys):
    a = ReceptionistAgent("demo_clinic", llm=FakeLLM([]))
    day = open_day(); t = open_times(date=day)[0]
    a.run_tool({"name": "book_appointment", "args": {"customer_name": "Priya Sharma", "phone": PRIYA,
                                                     "service": "Cleaning", "date": day, "time": t}})
    a.run_tool({"name": "save_lead", "args": {"name": "Ravi Kumar", "phone": RAVI, "interest": "braces"}})
    out = capsys.readouterr().out
    assert "Priya Sharma" not in out and PRIYA not in out and "Ravi Kumar" not in out and RAVI not in out
    assert "…3210" in out and "P." in out


def test_cli_is_a_dry_run_unless_told(data, capsys, monkeypatch):
    monkeypatch.setattr(storage, "purge_expired", lambda dry_run=True: {"calls": int(dry_run)})
    storage.main(["purge"])
    assert "Would remove" in capsys.readouterr().out
