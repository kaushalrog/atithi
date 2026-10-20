"""Proof, not promises: the agent never tells a customer something is done
unless a tool result says so."""

import datetime as dt
import json

import pytest

import proof
import storage
from agent import ReceptionistAgent
from conftest import FakeLLM, open_day, open_times


def say(text):
    return {"text": text, "tool_calls": []}


def call(name, **args):
    return {"text": None, "tool_calls": [{"name": name, "args": args}]}


# ---- what counts as a claim ----------------------------------------------------

@pytest.mark.parametrize("text,kind", [
    ("Great, you're booked for Tuesday at 4 PM.", "booked"),
    ("Your appointment is confirmed for 10:30.", "booked"),
    ("I've booked you in for a haircut tomorrow.", "booked"),
    ("Your table has been reserved for 8 PM.", "booked"),
    ("Done. I've cancelled your booking.", "cancelled"),
    ("Your appointment has been moved to Friday.", "rescheduled"),
    ("Our team will call you back within the hour.", "callback"),
])
def test_claims_are_recognised(text, kind):
    assert kind in {c["kind"] for c in proof.claims(text)}


@pytest.mark.parametrize("text", [
    "Shall I book 4 PM for you?",
    "Would you like me to confirm that slot?",
    "Once you share your number, I'll book it.",
    "Sorry, Saturday is fully booked.",
    "Your booking is not confirmed yet.",
    "I couldn't cancel that one.",
    "We have slots at 10:30 and 11:00.",
    "If you'd like, I can move it to Friday.",
])
def test_questions_offers_and_negatives_are_not_claims(text):
    assert proof.claims(text) == []


def test_spoken_times_are_normalised():
    assert proof.spoken_times("booked for 4 PM") == {"16:00"}
    assert proof.spoken_times("at 10:30 a.m.") == {"10:30"}
    assert proof.spoken_times("at 4:30") == {"04:30", "16:30"}      # either half of the day
    assert proof.spoken_times("for 2 people") == set()


def test_a_claim_needs_a_matching_tool_result():
    booked = [{"role": "tool", "name": "book_appointment",
               "result": {"status": "confirmed", "time": "16:30"}}]
    failed = [{"role": "tool", "name": "book_appointment",
               "result": {"status": "failed", "error": "slot taken"}}]
    text = "You're booked for 4:30 PM."
    assert proof.unbacked(text, booked) == []
    assert proof.unbacked(text, failed)[0]["problem"] == "no_action"
    assert proof.unbacked("You're booked for 4 PM.", booked)[0]["problem"] == "wrong_time"
    assert proof.unbacked("Your booking is cancelled.", booked)[0]["kind"] == "cancelled"


def test_an_existing_booking_found_by_lookup_backs_a_confirmation():
    found = [{"role": "tool", "name": "find_booking",
              "result": {"status": "found", "bookings": [{"date": "2026-11-02", "time": "10:30"}]}}]
    assert proof.unbacked("Yes, your appointment is confirmed for 10:30.", found) == []


# ---- the live guard ----------------------------------------------------------

def test_a_false_booking_claim_never_reaches_the_customer(tmp_storage):
    """The model says "booked" without booking; after the nudge it books for real."""
    day = open_day(); t = open_times(date=day)[0]
    llm = FakeLLM([
        say(f"You're booked for {t}!"),                       # the lie
        call("book_appointment", customer_name="Ravi", phone="9876543210",
             service="Cleaning", date=day, time=t),
        say(f"Done, you're booked for {t}."),
    ])
    agent = ReceptionistAgent("demo_clinic", llm=llm)
    reply = agent.chat(f"Book me at {t} on {day}, I'm Ravi, 9876543210")
    assert reply == f"Done, you're booked for {t}."
    assert storage.read_bookings("demo_clinic")[0]["status"] == "confirmed"
    nudge = llm.requests[1]["messages"][-1]
    assert nudge["role"] == "user" and nudge["text"].startswith("[Record check")
    # The lie and the nudge are never stored in the conversation.
    texts = [m.get("text") or "" for m in agent.history]
    assert not any("Record check" in x for x in texts) and texts.count(f"You're booked for {t}!") == 0
    assert agent.caught == [{"kind": "booked", "said": f"You're booked for {t}!",
                             "problem": "no_action", "fixed": True}]


def test_if_the_model_insists_the_customer_gets_an_honest_reply(tmp_storage):
    llm = FakeLLM([say("You're booked for 4 PM."), say("Yes, you're all booked for 4 PM.")])
    agent = ReceptionistAgent("demo_clinic", llm=llm)
    assert agent.chat("book me at 4") == proof.SAFE_REPLY
    assert agent.caught[0]["fixed"] is False
    assert storage.read_bookings("demo_clinic") == []
    assert len(llm.requests) == 2                              # one nudge, not a loop


def test_honest_replies_cost_no_extra_model_call(tmp_storage):
    llm = FakeLLM([say("Shall I book 4 PM for you?")])
    agent = ReceptionistAgent("demo_clinic", llm=llm)
    agent.chat("4 pm please")
    assert len(llm.requests) == 1 and agent.caught == []


# ---- the call report ---------------------------------------------------------

def test_every_call_record_carries_a_proof_report(tmp_storage):
    day = open_day(); t = open_times(date=day)[0]
    llm = FakeLLM([
        say(f"You're booked for {t}!"),
        call("book_appointment", customer_name="Ravi", phone="9876543210",
             service="Cleaning", date=day, time=t),
        say(f"Done, you're booked for {t}."),
        say("The team will call you back about the offer."),
    ])
    agent = ReceptionistAgent("demo_clinic", llm=llm)
    agent.chat(f"Book {t} on {day}, Ravi 9876543210")
    agent.chat("any offers?")
    storage.log_call_from_agent(agent, "web-test", dt.datetime.now(), call_id="p1")
    record = json.loads((storage.CALLS_DIR / "demo_clinic" / "p1.json").read_text())
    p = record["proof"]
    assert (p["claims"], p["backed"], p["verdict"]) == (2, 2, "verified")   # booking carries a phone
    assert p["caught"][0]["problem"] == "no_action"


def test_a_phone_call_claim_without_a_booking_is_flagged_after_the_call():
    history = [
        {"role": "user", "text": "book me at 4"},
        {"role": "assistant", "text": "You're booked for 4 PM, see you then."},
        {"role": "user", "text": "thanks"},
        {"role": "assistant", "text": "Our team will call you back to confirm."},
    ]
    p = proof.report(history)
    assert p["verdict"] == "flagged" and p["backed"] == 0
    assert [u["problem"] for u in p["unbacked"]] == ["no_action", "no_action"]


def test_same_turn_tool_results_back_a_spoken_claim():
    """On a phone call the agent may speak before the tool result lands."""
    history = [
        {"role": "user", "text": "book me at 4"},
        {"role": "assistant", "text": "You're booked for 4 PM."},
        {"role": "assistant", "text": None, "tool_calls": [{"name": "book_appointment", "args": {}}]},
        {"role": "tool", "name": "book_appointment", "result": {"status": "confirmed", "time": "16:00"}},
    ]
    assert proof.report(history)["verdict"] == "verified"
    assert proof.report([])["verdict"] == "none"
