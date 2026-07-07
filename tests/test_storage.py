"""Storage layer: CSV round-trips and call logs."""

import datetime as dt

import storage


def test_booking_roundtrip_and_client_filter(tmp_storage):
    row = ["2026-07-07T10:00:00", "clinic_a", "Ravi", "9876543210",
           "Cleaning", "2026-07-09", "09:30", "confirmed"]
    where = storage.save_booking(row)
    assert "bookings.csv" in where  # Sheets not configured -> CSV fallback
    assert len(storage.read_bookings("clinic_a")) == 1
    assert storage.read_bookings("other_client") == []


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
