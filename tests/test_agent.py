"""Agent core: the tool-use loop, tool validation, and slot bookkeeping."""

import storage
from agent import ReceptionistAgent

# demo_clinic.yaml has slots on this date: 09:30, 10:00, 16:00, 18:00, 19:30
DATE = "2026-07-09"


def make_agent(fake_llm, responses):
    return ReceptionistAgent("demo_clinic", llm=fake_llm(responses))


def test_plain_reply(tmp_storage, fake_llm):
    agent = make_agent(fake_llm, [{"text": "Hello!", "tool_calls": []}])
    assert agent.chat("hi") == "Hello!"
    assert [m["role"] for m in agent.history] == ["user", "assistant"]


def test_tool_loop_executes_and_feeds_back(tmp_storage, fake_llm):
    agent = make_agent(fake_llm, [
        {"text": None, "tool_calls": [{"name": "check_availability", "args": {"date": DATE}}]},
        {"text": "We have 09:30 free.", "tool_calls": []},
    ])
    reply = agent.chat("anything tomorrow?")
    assert reply == "We have 09:30 free."
    roles = [m["role"] for m in agent.history]
    assert roles == ["user", "assistant", "tool", "assistant"]
    tool_result = agent.history[2]["result"]
    assert "09:30" in tool_result["available_slots"]
    # the agent must offer all three tools to the model every turn
    assert {t["name"] for t in agent.llm.requests[0]["tools"]} == {
        "check_availability", "book_appointment", "save_lead",
    }


def test_runaway_tool_loop_is_stopped(tmp_storage, fake_llm):
    endless = {"text": None, "tool_calls": [{"name": "check_availability", "args": {"date": DATE}}]}
    agent = make_agent(fake_llm, [endless] * 6)
    reply = agent.chat("hi")
    assert "front desk" in reply  # the safety net answer, not a crash


def test_tool_exception_is_reported_not_raised(tmp_storage, fake_llm):
    agent = make_agent(fake_llm, [
        {"text": None, "tool_calls": [{"name": "no_such_tool", "args": {}}]},
        {"text": "Sorry about that.", "tool_calls": []},
    ])
    assert agent.chat("hi") == "Sorry about that."
    assert "error" in agent.history[2]["result"]


def test_check_availability_returns_all_slots_unfiltered(tmp_storage, fake_llm):
    # No server-side time filtering: an eval showed a window mismatch ("evening"
    # meaning 4 PM to the model but 5 PM to us) hides real slots from customers.
    agent = make_agent(fake_llm, [])
    result = agent._check_availability(DATE)
    assert result["available_slots"] == ["09:30", "10:00", "16:00", "18:00", "19:30"]
    unknown = agent._check_availability("2030-01-01")
    assert unknown["available_slots"] == [] and "note" in unknown


def test_booking_rejects_unavailable_slot(tmp_storage, fake_llm):
    agent = make_agent(fake_llm, [])
    result = agent._book_appointment("A", "9876543210", "Cleaning", DATE, "14:00")
    assert result["status"] == "failed"
    assert "09:30" in result["available_slots"]  # gives the model the fix


def test_booking_rejects_short_phone(tmp_storage, fake_llm):
    agent = make_agent(fake_llm, [])
    result = agent._book_appointment("A", "12345", "Cleaning", DATE, "09:30")
    assert result["status"] == "failed"
    assert "phone" in result["error"].lower()


def test_booking_consumes_slot_and_persists(tmp_storage, fake_llm):
    agent = make_agent(fake_llm, [])
    result = agent._book_appointment("Ravi", "+91 98765 43210", "Cleaning", DATE, "09:30")
    assert result["status"] == "confirmed"
    assert "09:30" not in agent._check_availability(DATE)["available_slots"]
    rows = storage.read_bookings("demo_clinic")
    assert len(rows) == 1 and rows[0]["time"] == "09:30"
    # a fresh agent must replay the booking and not offer the slot again
    agent2 = make_agent(fake_llm, [])
    assert "09:30" not in agent2._check_availability(DATE)["available_slots"]


def test_double_booking_same_slot_fails(tmp_storage, fake_llm):
    agent = make_agent(fake_llm, [])
    assert agent._book_appointment("A", "9876543210", "X", DATE, "10:00")["status"] == "confirmed"
    assert agent._book_appointment("B", "9876543211", "X", DATE, "10:00")["status"] == "failed"


def test_save_lead(tmp_storage, fake_llm):
    agent = make_agent(fake_llm, [])
    result = agent._save_lead("Kiran", "9998887776", "braces price", "call after 6pm")
    assert result["status"] == "saved"
    leads = storage.read_leads("demo_clinic")
    assert len(leads) == 1 and leads[0]["interest"] == "braces price"


def test_lead_rejects_short_phone(tmp_storage, fake_llm):
    agent = make_agent(fake_llm, [])
    assert agent._save_lead("K", "12", "x", "")["status"] == "failed"
    assert storage.read_leads("demo_clinic") == []
