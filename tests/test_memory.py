"""memory.py — recognising a caller we have spoken to before."""

import datetime as dt

import pytest

import memory
import storage

TODAY = dt.date.today()


def hours_ago(h):
    return (dt.datetime.now() - dt.timedelta(hours=h)).isoformat(timespec="seconds")


def days_ago(d):
    return (dt.datetime.now() - dt.timedelta(days=d)).isoformat(timespec="seconds")


@pytest.fixture
def records(monkeypatch):
    """Control what the business's call log and bookings contain."""
    state = {"calls": [], "bookings": []}
    monkeypatch.setattr(storage, "read_call_logs", lambda cid: state["calls"])
    monkeypatch.setattr(storage, "find_bookings", lambda cid, phone: state["bookings"])
    return state


def test_an_unknown_number_is_remembered_as_nothing(records):
    assert memory.recall("clinic", "+919876543210") == {}
    assert memory.brief_for("clinic", "+919876543210") == ""


def test_no_caller_id_means_no_memory(records):
    assert memory.recall("clinic", None) == {}
    assert memory.recall("clinic", "") == {}


def test_a_returning_caller_is_recognised_across_number_formats(records):
    """Caller ID arrives in several shapes; the same person must match."""
    records["calls"] = [{"caller": "+91 98765 43210", "started": hours_ago(20)}]
    known = memory.recall("clinic", "9876543210")
    assert known["known"] is True and known["calls"] == 1


def test_the_name_comes_from_what_they_booked_under(records):
    records["calls"] = [{"caller": "+919876543210", "started": hours_ago(5)}]
    records["bookings"] = [{"name": "Priya Sharma", "service": "Cleaning",
                            "date": TODAY.isoformat(), "time": "10:30"}]
    brief = memory.brief_for("clinic", "+919876543210")
    assert "Priya Sharma" in brief
    assert "Greet them by name" in brief


def test_an_upcoming_appointment_is_in_the_briefing(records):
    future = (TODAY + dt.timedelta(days=2)).isoformat()
    records["bookings"] = [{"name": "Ravi", "service": "Root canal",
                            "date": future, "time": "16:00"}]
    brief = memory.brief_for("clinic", "+919876543210")
    assert "Root canal" in brief and future in brief


def test_a_past_appointment_is_not_called_upcoming(records):
    past = (TODAY - dt.timedelta(days=5)).isoformat()
    records["bookings"] = [{"name": "Ravi", "service": "Cleaning",
                            "date": past, "time": "16:00"}]
    known = memory.recall("clinic", "+919876543210")
    assert known["upcoming"] == []


def test_very_old_calls_are_forgotten(records):
    """Greeting someone about a visit they have forgotten is worse than silence."""
    records["calls"] = [{"caller": "+919876543210",
                         "started": days_ago(memory.LOOKBACK_DAYS + 10)}]
    assert memory.recall("clinic", "+919876543210") == {}


def test_a_regular_is_noted_but_the_count_is_never_recited(records):
    records["calls"] = [{"caller": "+919876543210", "started": hours_ago(h)}
                        for h in (2, 30, 60, 90)]
    brief = memory.brief_for("clinic", "+919876543210")
    assert "call regularly" in brief
    # The agent must not say "you have called 4 times" — that sounds like
    # surveillance, not service.
    assert "4" not in brief
    assert "Do NOT list" in brief


def test_the_briefing_tells_the_agent_to_believe_the_caller(records):
    """Records can be stale; the person on the phone is the source of truth."""
    records["calls"] = [{"caller": "+919876543210", "started": hours_ago(3)}]
    records["bookings"] = [{"name": "Ravi", "service": "Cleaning",
                            "date": TODAY.isoformat(), "time": "10:30"}]
    brief = memory.brief_for("clinic", "+919876543210")
    assert "believe the caller" in brief


def test_memory_never_blocks_a_call_when_storage_fails(monkeypatch):
    """A memory lookup is a nicety. It must not be able to stop a call."""
    def boom(*a, **k):
        raise RuntimeError("bookings db is down")
    monkeypatch.setattr(storage, "read_call_logs", boom)
    monkeypatch.setattr(storage, "find_bookings", boom)
    assert memory.recall("clinic", "+919876543210") == {}
    assert memory.brief_for("clinic", "+919876543210") == ""


def test_memory_never_crosses_businesses(records, monkeypatch):
    """A customer known to the clinic is a stranger to the salon."""
    seen = []
    monkeypatch.setattr(storage, "read_call_logs",
                        lambda cid: seen.append(cid) or [])
    monkeypatch.setattr(storage, "find_bookings",
                        lambda cid, phone: seen.append(cid) or [])
    memory.recall("salon", "+919876543210")
    assert set(seen) == {"salon"}
