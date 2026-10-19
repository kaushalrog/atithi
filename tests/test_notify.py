"""Customer texts: off unless switched on, never on the call path, never
able to affect a booking, and each reminder sent once."""

import datetime as dt

import pytest

import notify
import storage
import telephony
from agent import ReceptionistAgent
from conftest import FakeLLM, open_day, open_times

PHONE = "9876543210"


@pytest.fixture
def texts(tmp_storage, monkeypatch):
    """Notifications on (tests opt in explicitly), Twilio fully faked."""
    monkeypatch.setattr(storage, "_ALLOW_NOTIFY_IN_TESTS", True, raising=False)
    sent = []
    monkeypatch.setattr(telephony, "send_sms", lambda to, body: sent.append((to, body)) or "SM123")
    return sent


def book(agent, date, time):
    r = agent.run_tool({"name": "book_appointment", "args": {
        "customer_name": "Ravi", "phone": PHONE, "service": "Teeth cleaning", "date": date, "time": time}})
    assert r["result"]["status"] == "confirmed"


def logged():
    assert notify._queue.drain(3) == 0
    return storage.read_notifications()


def test_off_by_default_it_records_a_dry_run_instead_of_texting(texts):
    agent = ReceptionistAgent("demo_clinic", llm=FakeLLM([]))
    day = open_day(); t = open_times(date=day)[0]
    book(agent, day, t)
    [n] = logged()
    assert n["status"] == "dry-run" and n["kind"] == "confirmed" and n["to"] == "+91" + PHONE
    assert n["text"].startswith(agent.config["business_name"]) and "Teeth cleaning" in n["text"]
    assert texts == []                                       # nothing went to Twilio


def test_when_switched_on_it_texts_the_customer(texts, monkeypatch):
    monkeypatch.setenv("ENABLE_SMS", "true")
    for k, v in (("TWILIO_ACCOUNT_SID", "ACx"), ("TWILIO_AUTH_TOKEN", "tok"), ("TWILIO_NUMBER", "+15550001111")):
        monkeypatch.setenv(k, v)
    agent = ReceptionistAgent("demo_clinic", llm=FakeLLM([]))
    day = open_day(); first, second = open_times(date=day)[:2]
    book(agent, day, first)
    agent.run_tool({"name": "reschedule_booking", "args": {
        "phone": PHONE, "date": day, "time": first, "new_date": day, "new_time": second}})
    agent.run_tool({"name": "cancel_booking", "args": {"phone": PHONE, "date": day, "time": second}})
    kinds = [(n["kind"], n["status"]) for n in logged()]
    assert kinds == [("confirmed", "sent"), ("rescheduled", "sent"), ("cancelled", "sent")]
    assert [to for to, _ in texts] == ["+91" + PHONE] * 3
    assert "moved to" in texts[1][1] and "cancelled" in texts[2][1]


def test_a_failed_text_never_affects_the_booking(texts, monkeypatch, capsys):
    monkeypatch.setenv("ENABLE_SMS", "true")
    for k, v in (("TWILIO_ACCOUNT_SID", "ACx"), ("TWILIO_AUTH_TOKEN", "tok"), ("TWILIO_NUMBER", "+15550001111")):
        monkeypatch.setenv(k, v)

    def down(to, body):
        raise ConnectionError("Twilio unreachable")
    monkeypatch.setattr(telephony, "send_sms", down)
    agent = ReceptionistAgent("demo_clinic", llm=FakeLLM([]))
    day = open_day(); t = open_times(date=day)[0]
    book(agent, day, t)
    [n] = logged()
    assert n["status"] == "failed" and n["error"] == "ConnectionError"
    assert storage.read_bookings("demo_clinic")[0]["status"] == "confirmed"
    assert "booking itself is unaffected" in capsys.readouterr().out


def test_a_business_can_turn_texts_off(texts, monkeypatch):
    real = storage.read_client_config
    monkeypatch.setattr(storage, "read_client_config",
                        lambda cid: {**(real(cid) or {}), "sms_confirmations": False})
    notify.booking_event("demo_clinic", "confirmed",
                         {"phone": PHONE, "service": "x", "date": "2026-10-21", "time": "10:30"})
    [n] = logged()
    assert n["status"] == "skipped" and "text" not in n


def test_tests_never_queue_texts_unless_they_opt_in(tmp_storage):
    notify.booking_event("demo_clinic", "confirmed",
                         {"phone": PHONE, "service": "x", "date": "2026-10-21", "time": "10:30"})
    assert notify._queue.drain(1) == 0 and storage.read_notifications() == []


def test_reminders_go_out_once_for_tomorrows_bookings(texts):
    tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    later = (dt.date.today() + dt.timedelta(days=3)).isoformat()
    for day in (tomorrow, later):
        storage.reserve_booking(["2026-10-20T10:00:00", "demo_clinic", "Ravi", PHONE,
                                 "Teeth cleaning", day, "10:30", "confirmed"])
    assert notify.send_reminders() == 1
    [n] = logged()
    assert n["kind"] == "reminder" and n["booking"]["date"] == tomorrow and "tomorrow" in n["text"]
    assert notify.send_reminders() == 0                      # never twice


def test_message_texts_and_numbers():
    cfg = {"business_name": "Sri Balaji Dental Care", "phone": "+91 98430 12345"}
    b = {"service": "Teeth cleaning", "date": "2026-10-21", "time": "10:30"}
    assert notify.message(cfg, "confirmed", b) == (
        "Sri Balaji Dental Care: your Teeth cleaning is booked for Wed 21 Oct at 10:30 AM. "
        "To change it, call +91 98430 12345.")
    assert notify.to_e164("098765 43210") == "+919876543210"
    assert notify.to_e164("+1 555 000 1111") == "+15550001111"
    assert notify.to_e164("123") is None
