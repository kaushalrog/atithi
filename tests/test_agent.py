"""Agent core: the tool-use loop, tool validation, and slot bookkeeping.

Dates here are derived from the client's live schedule, never hardcoded. The
old suite pinned a literal date, which drifted into the past and let a total
booking outage pass every test for two months.
"""

import datetime as dt

import pytest

import agent as agent_module
import storage
from agent import ReceptionistAgent
from conftest import open_day, open_times

# A time no business in this project is open — safe "unavailable" fixture.
CLOSED_TIME = "03:00"


def make_agent(fake_llm, responses):
    return ReceptionistAgent("demo_clinic", llm=fake_llm(responses))


def test_plain_reply(tmp_storage, fake_llm):
    agent = make_agent(fake_llm, [{"text": "Hello!", "tool_calls": []}])
    assert agent.chat("hi") == "Hello!"
    assert [m["role"] for m in agent.history] == ["user", "assistant"]


def test_tool_loop_executes_and_feeds_back(tmp_storage, fake_llm):
    date = open_day()
    first_slot = open_times(date=date)[0]
    agent = make_agent(fake_llm, [
        {"text": None, "tool_calls": [{"name": "check_availability", "args": {"date": date}}]},
        {"text": f"We have {first_slot} free.", "tool_calls": []},
    ])
    reply = agent.chat("anything tomorrow?")
    assert reply == f"We have {first_slot} free."
    roles = [m["role"] for m in agent.history]
    assert roles == ["user", "assistant", "tool", "assistant"]
    tool_result = agent.history[2]["result"]
    assert first_slot in tool_result["available_slots"]
    # the agent must offer all three tools to the model every turn
    assert {t["name"] for t in agent.llm.requests[0]["tools"]} == {
        "check_availability", "book_appointment", "save_lead",
    }


def test_runaway_tool_loop_is_stopped(tmp_storage, fake_llm):
    endless = {"text": None,
               "tool_calls": [{"name": "check_availability", "args": {"date": open_day()}}]}
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
    date = open_day()
    result = agent._check_availability(date)
    assert result["available_slots"] == open_times(date=date)
    assert len(result["available_slots"]) > 1


def test_availability_is_never_empty_for_the_whole_window(tmp_storage, fake_llm):
    """Regression guard for the outage: a rolling schedule always has slots."""
    agent = make_agent(fake_llm, [])
    assert sum(len(v) for v in agent.slots.values()) > 0
    # and the window starts today, not on some date frozen at onboarding
    import datetime as dt
    assert min(agent.slots) == dt.date.today().isoformat()


def test_unknown_date_explains_the_bookable_window(tmp_storage, fake_llm):
    agent = make_agent(fake_llm, [])
    result = agent._check_availability("2020-01-01")
    assert result["available_slots"] == []
    assert "front desk" in result["note"] or "Bookings are open" in result["note"]


def test_booking_rejects_unavailable_slot(tmp_storage, fake_llm):
    agent = make_agent(fake_llm, [])
    date = open_day()
    result = agent._book_appointment("A", "9876543210", "Cleaning", date, CLOSED_TIME)
    assert result["status"] == "failed"
    assert result["available_slots"] == open_times(date=date)  # gives the model the fix


def test_booking_rejects_short_phone(tmp_storage, fake_llm):
    agent = make_agent(fake_llm, [])
    date = open_day()
    result = agent._book_appointment("A", "12345", "Cleaning", date, open_times(date=date)[0])
    assert result["status"] == "failed"
    assert "phone" in result["error"].lower()


def test_booking_consumes_slot_and_persists(tmp_storage, fake_llm):
    agent = make_agent(fake_llm, [])
    date = open_day()
    slot = open_times(date=date)[0]
    result = agent._book_appointment("Ravi", "+91 98765 43210", "Cleaning", date, slot)
    assert result["status"] == "confirmed"
    assert slot not in agent._check_availability(date)["available_slots"]
    rows = storage.read_bookings("demo_clinic")
    assert len(rows) == 1 and rows[0]["time"] == slot
    # a fresh agent must replay the booking and not offer the slot again
    agent2 = make_agent(fake_llm, [])
    assert slot not in agent2._check_availability(date)["available_slots"]


def test_double_booking_same_slot_fails(tmp_storage, fake_llm):
    agent = make_agent(fake_llm, [])
    date = open_day()
    slot = open_times(date=date)[1]
    assert agent._book_appointment("A", "9876543210", "X", date, slot)["status"] == "confirmed"
    assert agent._book_appointment("B", "9876543211", "X", date, slot)["status"] == "failed"


def test_two_conversations_cannot_book_the_same_slot(tmp_storage, fake_llm):
    """Audit H2 (reproduced as R1): both agents are built BEFORE either books,
    so each started out believing the slot was free."""
    date = open_day()
    slot = open_times(date=date)[0]
    first, second = make_agent(fake_llm, []), make_agent(fake_llm, [])
    assert first._book_appointment("Asha", "9876543210", "X", date, slot)["status"] == "confirmed"
    result = second._book_appointment("Bala", "9876543211", "X", date, slot)
    assert result["status"] == "failed"
    assert slot not in result["available_slots"]       # the model gets real alternatives
    assert result["available_slots"]                   # ...and there are some
    assert len(storage.read_bookings("demo_clinic")) == 1


def test_availability_sees_other_conversations_bookings(tmp_storage, fake_llm):
    date = open_day()
    slot = open_times(date=date)[0]
    waiting = make_agent(fake_llm, [])
    assert slot in waiting._check_availability(date)["available_slots"]
    make_agent(fake_llm, [])._book_appointment("Asha", "9876543210", "X", date, slot)
    assert slot not in waiting._check_availability(date)["available_slots"]


def test_losing_the_database_race_is_reported_to_the_model(tmp_storage, fake_llm, monkeypatch):
    """The slot looked free when checked, but another writer committed first."""
    agent = make_agent(fake_llm, [])
    date = open_day()
    slot = open_times(date=date)[0]
    monkeypatch.setattr(storage, "reserve_booking", lambda row: None)
    result = agent._book_appointment("Asha", "9876543210", "X", date, slot)
    assert result["status"] == "failed" and "just booked" in result["error"]


def test_save_lead(tmp_storage, fake_llm):
    agent = make_agent(fake_llm, [])
    result = agent._save_lead("Kiran", "9998887776", "braces price", "call after 6pm")
    assert result["status"] == "saved"
    leads = storage.read_leads("demo_clinic")
    assert len(leads) == 1 and leads[0]["interest"] == "braces price"


def test_lead_rejects_short_phone(tmp_storage, fake_llm):
    agent = make_agent(fake_llm, [])
    assert agent._save_lead("K", "12", "x", "")["status"] == "failed"
    assert list(storage.read_leads("demo_clinic")) == []


# ---- the LLM provider seam ----------------------------------------------------------

def test_gemini_client_is_built_with_a_request_timeout(monkeypatch):
    """Audit M6: generate_content had no timeout, so a stalled request hung
    the caller's turn forever. No network: the client constructor is a spy."""
    import llm

    built = []
    monkeypatch.setattr(llm.genai, "Client", lambda **kw: built.append(kw) or object())
    monkeypatch.setattr(llm, "_clients", {})
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("GEMINI_TIMEOUT_S", "12")
    llm.shared_client()
    assert built[0]["http_options"].timeout == 12_000      # milliseconds


@pytest.mark.parametrize("raw,ms", [("abc", 30_000), ("0", 1_000), ("-5", 1_000), ("2.5", 2_500)])
def test_gemini_timeout_setting_is_guarded(monkeypatch, raw, ms):
    import llm

    monkeypatch.setenv("GEMINI_TIMEOUT_S", raw)
    assert llm._timeout_ms() == ms


# ---- channels -------------------------------------------------------------------

def test_tool_error_is_reported_not_fatal(tmp_storage, fake_llm, monkeypatch):
    """A tool failure (e.g. bookings paused) must come back to the model as an
    error, not end the call. Every channel runs tools through run_tool, and
    the model reads this exact text, so it must not change."""
    agent = make_agent(fake_llm, [])

    def broken(name, args):
        raise storage.BookingsUnavailable("paused")
    monkeypatch.setattr(agent, "_execute_tool", broken)
    entry = agent.run_tool({"name": "book_appointment", "args": {}})
    assert entry["result"] == {"error": "BookingsUnavailable: paused"}
    assert entry["role"] == "tool" and entry["name"] == "book_appointment"


def test_history_timestamps_carry_the_business_timezone(tmp_storage, fake_llm):
    """"Tomorrow at 4" can only be checked later if every entry says whose
    tomorrow. Default Asia/Kolkata (+05:30)."""
    date = open_day()
    agent = make_agent(fake_llm, [
        {"text": None, "tool_calls": [{"name": "check_availability", "args": {"date": date}}]},
        {"text": "We have slots.", "tool_calls": []},
    ])
    agent.chat("any slots?")
    assert [m["role"] for m in agent.history] == ["user", "assistant", "tool", "assistant"]
    for msg in agent.history:
        assert dt.datetime.fromisoformat(msg["at"]).utcoffset() == dt.timedelta(hours=5, minutes=30)


@pytest.mark.parametrize("name,offset", [("Asia/Dubai", 4), ("Not/AZone", 5.5)])
def test_client_yaml_can_set_the_timezone(tmp_storage, fake_llm, monkeypatch, name, offset):
    """A typo in one client's timezone must not stop its calls: fall back to IST."""
    agent = make_agent(fake_llm, [])
    agent.tz = agent_module._business_timezone({"timezone": name})
    assert dt.datetime.fromisoformat(agent.now()).utcoffset() == dt.timedelta(hours=offset)


def test_turn_recorder_writes_tools_between_the_request_and_the_reply(tmp_storage, fake_llm):
    """On a streaming call the tool runs mid-turn, before the caller's words
    are complete. History must still read: request, tool, reply."""
    date = open_day()
    agent = make_agent(fake_llm, [])
    turn = agent_module.TurnRecorder(agent)
    results = turn.tool_calls([{"id": "t1", "name": "check_availability", "args": {"date": date}}])
    turn.user_text("any slots ")
    turn.user_text("tomorrow?")
    turn.agent_text("Yes, 10 AM is free.")
    assert agent.history == []                       # nothing written mid-turn
    turn.flush()
    assert [m["role"] for m in agent.history] == ["user", "assistant", "tool", "assistant"]
    assert agent.history[0]["text"] == "any slots tomorrow?"
    assert results[0]["id"] == "t1" and results[0]["result"]["available_slots"]
    turn.flush()                                     # a second flush adds nothing
    assert len(agent.history) == 4
