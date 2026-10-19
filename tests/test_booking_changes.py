"""Cancel and reschedule: a booking is changed, never lost or doubled."""

import threading

import pytest
from fastapi.testclient import TestClient

import server
import storage
from agent import ReceptionistAgent
from conftest import FakeLLM, open_day, open_times

PHONE = "9876543210"


def book(agent, date, time, phone=PHONE, name="Ravi"):
    r = agent.run_tool({"name": "book_appointment", "args": {
        "customer_name": name, "phone": phone, "service": "Cleaning", "date": date, "time": time}})
    assert r["result"]["status"] == "confirmed", r
    return r


def tool(agent, name, **args):
    return agent.run_tool({"name": name, "args": args})["result"]


@pytest.fixture
def agent(tmp_storage):
    return ReceptionistAgent("demo_clinic", llm=FakeLLM([]))


def test_a_caller_finds_and_cancels_their_booking_and_the_slot_frees_up(agent):
    day = open_day(); t = open_times(date=day)[0]
    book(agent, day, t)
    found = tool(agent, "find_booking", phone="+91 " + PHONE)       # any way of writing it
    assert found["status"] == "found" and found["bookings"][0]["time"] == t
    res = tool(agent, "cancel_booking", phone=PHONE, date=day, time=t)
    assert res["status"] == "cancelled"
    assert [b["status"] for b in storage.read_bookings("demo_clinic")] == ["cancelled"]
    assert t in tool(agent, "check_availability", date=day)["available_slots"]
    book(agent, day, t, phone="9123456789", name="Asha")           # someone else can take it


def test_a_different_number_cannot_cancel_someone_elses_booking(agent):
    day = open_day(); t = open_times(date=day)[0]
    book(agent, day, t)
    res = tool(agent, "cancel_booking", phone="9000000000", date=day, time=t)
    assert res["status"] == "failed" and "find_booking" in res["error"]
    assert storage.read_bookings("demo_clinic")[0]["status"] == "confirmed"
    assert tool(agent, "cancel_booking", phone="123", date=day, time=t)["status"] == "failed"


def test_reschedule_moves_the_booking_and_frees_the_old_slot(agent):
    day = open_day(); first, second = open_times(date=day)[:2]
    book(agent, day, first)
    res = tool(agent, "reschedule_booking", phone=PHONE, date=day, time=first,
               new_date=day, new_time=second)
    assert res["status"] == "rescheduled"
    rows = {(b["time"], b["status"]) for b in storage.read_bookings("demo_clinic")}
    assert rows == {(first, "rescheduled"), (second, "confirmed")}
    free = tool(agent, "check_availability", date=day)["available_slots"]
    assert first in free and second not in free


def test_rescheduling_into_a_taken_slot_changes_nothing(agent):
    day = open_day(); mine, theirs = open_times(date=day)[:2]
    book(agent, day, mine)
    book(agent, day, theirs, phone="9123456789", name="Asha")
    res = tool(agent, "reschedule_booking", phone=PHONE, date=day, time=mine,
               new_date=day, new_time=theirs)
    assert res["status"] == "failed" and "available_slots" in res
    rows = sorted((b["time"], b["status"]) for b in storage.read_bookings("demo_clinic"))
    assert rows == sorted([(mine, "confirmed"), (theirs, "confirmed")])


def test_the_database_refuses_a_race_into_the_same_new_slot(tmp_storage):
    """Two callers move their bookings into the same free slot at once: one
    wins, the other keeps their original booking."""
    day = open_day(); a, b, target = open_times(date=day)[:3]
    seed = ReceptionistAgent("demo_clinic", llm=FakeLLM([]))
    book(seed, day, a, phone="9111111111"); book(seed, day, b, phone="9222222222")
    results, barrier = [], threading.Barrier(2)

    def move(phone, old):
        barrier.wait()
        results.append(storage.reschedule_booking("demo_clinic", day, target,
                                                  date=day, time_=old, phone=phone)[0])
    ts = [threading.Thread(target=move, args=args) for args in (("9111111111", a), ("9222222222", b))]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert sorted(results) == ["rescheduled", "taken"]
    confirmed = [r for r in storage.read_bookings("demo_clinic") if r["status"] == "confirmed"]
    assert len(confirmed) == 2 and [r["time"] for r in confirmed].count(target) == 1


def test_the_owner_cancels_from_the_dashboard_and_counts_stay_honest(tmp_storage, monkeypatch, agent):
    import auth
    monkeypatch.setattr(auth, "DB_FILE", tmp_storage / "voxagent.db")
    monkeypatch.setattr(auth, "LEGACY_USERS", tmp_storage / "no_users.json")
    monkeypatch.setattr(auth, "LEGACY_TOKENS", tmp_storage / "no_tokens.json")
    client = TestClient(server.app)
    key = {"X-Client-Key": "VX-84KQ2N"}
    day = open_day(); t = open_times(date=day)[0]
    book(agent, day, t)
    [row] = storage.read_bookings("demo_clinic")
    assert client.post("/api/bookings/cancel", json={"client_id": "demo_clinic", "booking_id": row["id"]},
                       headers={"X-Client-Key": "VX-7TPX3R"}).status_code == 401   # another business
    res = client.post("/api/bookings/cancel", json={"client_id": "demo_clinic", "booking_id": row["id"]},
                      headers=key)
    assert res.status_code == 200
    again = client.post("/api/bookings/cancel", json={"client_id": "demo_clinic", "booking_id": row["id"]},
                        headers=key)
    assert again.status_code == 404
    stats = client.get("/api/dashboard?client_id=demo_clinic", headers=key).json()["stats"]
    assert stats["bookings"] == 0                      # a cancelled booking isn't a booking


def test_changes_are_recorded_as_actions_in_the_trace(agent):
    import json
    import datetime as dt
    day = open_day(); first, second = open_times(date=day)[:2]
    agent.history = [{"role": "user", "text": "move my booking", "at": agent.now()}]
    book(agent, day, first)
    for name, args in (("reschedule_booking", dict(phone=PHONE, date=day, time=first,
                                                    new_date=day, new_time=second)),
                       ("cancel_booking", dict(phone=PHONE, date=day, time=second))):
        agent.history.append(agent.tool_call_entry([{"name": name, "args": args}]))
        agent.history.append(agent.run_tool({"name": name, "args": args}))
    storage.log_call_from_agent(agent, "web-test", dt.datetime.now(), call_id="t1")
    trace = json.loads((storage.CALLS_DIR / "demo_clinic" / "traces" / "t1.json").read_text())
    assert [(a["type"], a["ok"]) for a in trace["actions"]] == [("reschedule", True), ("cancel", True)]
