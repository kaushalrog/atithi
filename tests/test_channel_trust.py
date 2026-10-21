"""Who is on the other end decides what the booking tools may do (audit
RT-1/RT-2, 2026-10-21): a phone number is not a secret, so on a public channel
it can't reveal or change someone else's booking, and one visitor can't fill
a day."""

import pytest

import agent as agent_mod
import proof
import storage
from agent import ReceptionistAgent
from conftest import FakeLLM, open_day, open_times
from test_whatsapp import CUSTOMER, say, send, wa  # noqa: F401
from test_telephony import phone  # noqa: F401  (wa builds on it)

VICTIM = "9876543210"


def tool(a, tool_name, **args):
    return a.run_tool({"name": tool_name, "args": args})["result"]


def book(a, day, time, phone_no, name="Priya"):
    return tool(a, "book_appointment", customer_name=name, phone=phone_no,
                service="Cleaning", date=day, time=time)


@pytest.fixture
def victim_booking(tmp_storage):
    day = open_day(); t = open_times(date=day)[0]
    owner = ReceptionistAgent("demo_clinic", llm=FakeLLM([]))
    assert book(owner, day, t, VICTIM)["status"] == "confirmed"
    return day, t


def public_agent():
    a = ReceptionistAgent("demo_clinic", llm=FakeLLM([]))
    a.set_channel("public")
    return a


# ---- the red team's attacks, now refused ----------------------------------------

def test_a_stranger_on_website_chat_learns_nothing_from_a_phone_number(victim_booking):
    res = tool(public_agent(), "find_booking", phone="98765 43210")
    assert res["status"] == "not_available"
    assert "Priya" not in str(res) and "bookings" not in res


def test_a_stranger_cannot_cancel_it_only_ask_the_team(victim_booking):
    day, t = victim_booking
    res = tool(public_agent(), "cancel_booking", phone=VICTIM, date=day, time=t)
    assert res["status"] == "request_saved" and "Do NOT say it is cancelled" in res["note"]
    assert storage.read_bookings("demo_clinic")[0]["status"] == "confirmed"   # untouched
    [lead] = storage.read_leads("demo_clinic")
    assert lead["interest"] == "Booking change request" and t in lead["note"]


def test_a_stranger_cannot_move_it_either(victim_booking):
    day, t = victim_booking
    later = open_times(date=day)[3]
    res = tool(public_agent(), "reschedule_booking", phone=VICTIM, date=day, time=t,
               new_date=day, new_time=later)
    assert res["status"] == "request_saved"
    assert {(b["time"], b["status"]) for b in storage.read_bookings("demo_clinic")} == {(t, "confirmed")}


def test_one_visitor_cannot_fill_a_day(tmp_storage):
    day = open_day(); times = open_times(date=day)
    a = public_agent()
    results = [book(a, day, t, f"90000000{i:02d}")["status"] for i, t in enumerate(times[:5])]
    assert results == ["confirmed", "confirmed", "failed", "failed", "failed"]
    assert len([b for b in storage.read_bookings("demo_clinic") if b["status"] == "confirmed"]) == 2


def test_one_number_cannot_hold_more_than_two_upcoming_bookings(tmp_storage):
    day = open_day(); times = open_times(date=day)
    for i in range(2):          # two separate conversations, same number
        assert book(public_agent(), day, times[i], "9123456789")["status"] == "confirmed"
    res = book(public_agent(), day, times[2], "9123456789")
    assert res["status"] == "failed" and "save_lead" in res["error"]


# ---- verified channels act only for their own number ------------------------------

def test_a_verified_sender_manages_only_their_own_bookings(victim_booking):
    day, t = victim_booking
    me = ReceptionistAgent("demo_clinic", llm=FakeLLM([]))
    me.set_channel("verified", "+91 98765 43210")             # the victim, via WhatsApp
    assert tool(me, "find_booking", phone=VICTIM)["status"] == "found"
    stranger = ReceptionistAgent("demo_clinic", llm=FakeLLM([]))
    stranger.set_channel("verified", "+919111111111")
    assert tool(stranger, "find_booking", phone=VICTIM)["status"] == "not_available"
    assert tool(stranger, "cancel_booking", phone=VICTIM, date=day, time=t)["status"] == "request_saved"
    assert tool(me, "cancel_booking", phone=VICTIM, date=day, time=t)["status"] == "cancelled"


def test_verified_without_a_usable_number_falls_back_to_public(tmp_storage):
    a = ReceptionistAgent("demo_clinic", llm=FakeLLM([]))
    a.set_channel("verified", "anonymous")
    assert (a.trust, a.verified_phone) == ("public", None)
    with pytest.raises(ValueError):
        a.set_channel("admin")


def test_the_owner_keeps_full_access(victim_booking):
    owner = ReceptionistAgent("demo_clinic", llm=FakeLLM([]))
    assert owner.trust == "owner"
    assert tool(owner, "find_booking", phone=VICTIM)["status"] == "found"


# ---- channels set the right level --------------------------------------------------

def test_website_chat_sessions_are_public(tmp_storage, monkeypatch):
    import shutil
    import yaml
    from fastapi.testclient import TestClient
    import server
    clients = tmp_storage / "clients"
    shutil.copytree(storage.CLIENTS_DIR, clients)
    path = clients / "demo_clinic.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg.update(website_chat=True, widget_key="wk_trusttest")
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(storage, "CLIENTS_DIR", clients)
    storage.clear_caches()
    res = TestClient(server.app).post("/api/public/session", json={"key": "wk_trusttest"})
    assert res.status_code == 200
    assert server.sessions[res.json()["session_id"]]["agent"].trust == "public"


def test_whatsapp_conversations_are_verified_to_the_sender(wa):
    wa["scripts"].append([say("Hello!")])
    send(wa["client"], "hi")
    [session] = list(__import__("telephony")._wa_sessions.values())
    assert (session["agent"].trust, session["agent"].verified_phone) == ("verified", CUSTOMER)


def test_a_change_request_backs_a_callback_promise():
    history = [{"role": "tool", "name": "cancel_booking", "result": {"status": "request_saved"}}]
    assert proof.unbacked("The team will call you to confirm the cancellation.", history) == []
    assert agent_mod.MAX_BOOKINGS_PER_CONVERSATION == 2


# ---- phone calls: caller ID is not proof (review follow-up, 2026-10-21) ------------

from test_telephony import SpyLive, post_voice, stream, ticket_from_twiml  # noqa: E402,F401
import telephony  # noqa: E402


@pytest.fixture
def made_agents(phone, monkeypatch, fake_llm):
    made = []

    def make(client_id):
        a = ReceptionistAgent(client_id, llm=fake_llm([]))
        made.append(a)
        return a
    monkeypatch.setattr(telephony, "ReceptionistAgent", make)
    return made


def test_an_inbound_caller_is_public_because_caller_id_can_be_faked(phone, made_agents):
    res = post_voice(phone["client"], {"To": "+15550001111", "From": "+919876543210", "CallSid": "CA1"})
    params = ticket_from_twiml(res.text)
    assert "purpose" not in params
    assert stream(phone["client"], params) == 1000
    [a] = made_agents
    assert (a.trust, a.verified_phone) == ("public", None)


@pytest.mark.parametrize("query,purpose", [("?client_id=demo_clinic", "outbound"),
                                           ("?client_id=demo_clinic&purpose=callback", "callback")])
def test_a_call_atithi_placed_proves_the_number(phone, made_agents, query, purpose):
    data = {"To": "+919876543210", "From": "+15550001111", "CallSid": "CA9", "Direction": "outbound-api"}
    params = ticket_from_twiml(post_voice(phone["client"], data, query=query).text)
    assert params["purpose"] == purpose
    assert stream(phone["client"], params, call_sid="CA9") == 1000
    [a] = made_agents
    assert (a.trust, a.verified_phone) == ("verified", "+919876543210")


def test_an_inbound_ticket_cannot_be_upgraded_to_outbound(phone, made_agents):
    params = ticket_from_twiml(post_voice(phone["client"], {"To": "+1", "From": "+919876543210",
                                                            "CallSid": "CA2"}).text)
    forged = {**params, "purpose": "outbound"}
    assert stream(phone["client"], forged, call_sid="CA2") == 1008     # signature no longer matches
    assert made_agents == []
