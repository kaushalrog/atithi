"""WhatsApp receptionist: off unless switched on, signed requests only,
replies only, one conversation per customer, and capped."""

import datetime as dt
import xml.etree.ElementTree as ET

import pytest
import yaml

import storage
import telephony
from agent import ReceptionistAgent
from conftest import FakeLLM, open_day, open_times
from test_telephony import phone, sign  # noqa: F401

URL = "https://testserver/twilio/whatsapp"
LINE = "+14155238886"          # Twilio's WhatsApp sandbox number
CUSTOMER = "+919876543210"


def say(text):
    return {"text": text, "tool_calls": []}


@pytest.fixture
def wa(phone, monkeypatch):
    monkeypatch.setenv("ENABLE_WHATSAPP", "true")
    path = storage.CLIENTS_DIR / "demo_clinic.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg["whatsapp_number"] = LINE
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    storage.clear_caches()
    monkeypatch.setattr(telephony, "_wa_sessions", {})
    monkeypatch.setattr(telephony, "_wa_recent", {})
    scripts = []           # replies for the next agents created, in order

    def make_agent(client_id):
        return ReceptionistAgent(client_id, llm=FakeLLM(scripts.pop(0) if scripts else []))
    monkeypatch.setattr(telephony, "ReceptionistAgent", make_agent)
    return {"client": phone["client"], "scripts": scripts}


def send(client, body, sender=CUSTOMER, to=LINE, signature=None, **extra):
    data = {"From": f"whatsapp:{sender}", "To": f"whatsapp:{to}", "Body": body, **extra}
    return client.post("/twilio/whatsapp", data=data, headers={
        "X-Twilio-Signature": signature if signature is not None else sign(URL, data)})


NOTICE = "AI receptionist"


def reply_of(res):
    """The receptionist's words, without the AI notice that opens each conversation."""
    node = ET.fromstring(res.text).find("Message")
    if node is None:
        return None
    text = node.text
    if text.startswith("(You're chatting with"):
        text = text.split("\n\n", 1)[1]
    return text


def test_the_first_reply_says_it_is_an_ai_and_the_chat_is_saved(wa):
    wa["scripts"].append([say("Hello!"), say("Sure.")])
    first = ET.fromstring(send(wa["client"], "hi").text).find("Message").text
    assert NOTICE in first and "saved" in first and first.endswith("Hello!")
    second = ET.fromstring(send(wa["client"], "ok").text).find("Message").text
    assert second == "Sure."                                   # once per conversation


def test_a_customer_books_over_whatsapp_and_the_chat_is_recorded(wa):
    day = open_day(); t = open_times(date=day)[0]
    wa["scripts"].append([
        say("Hello! How can I help?"),
        {"text": None, "tool_calls": [{"name": "book_appointment", "args": {
            "customer_name": "Ravi", "phone": CUSTOMER, "service": "Cleaning", "date": day, "time": t}}]},
        say(f"Done, you're booked for {t} on {day}."),
    ])
    assert reply_of(send(wa["client"], "hi")) == "Hello! How can I help?"
    res = send(wa["client"], f"book cleaning {day} {t}, Ravi")
    assert reply_of(res) == f"Done, you're booked for {t} on {day}."
    assert storage.read_bookings("demo_clinic")[0]["status"] == "confirmed"
    [call] = storage.read_call_logs("demo_clinic")
    assert call["channel"] == "whatsapp" and call["turns"] == 2 and call["caller"] == CUSTOMER
    assert call["proof"]["verdict"] == "verified"


def test_off_by_default_and_signed_requests_only(wa, monkeypatch):
    assert send(wa["client"], "hi", signature="forged").status_code == 403
    monkeypatch.setenv("ENABLE_WHATSAPP", "false")
    assert send(wa["client"], "hi").status_code == 503


def test_each_customer_gets_their_own_conversation(wa):
    wa["scripts"].extend([[say("Hi Ravi")], [say("Hi Asha")]])
    assert reply_of(send(wa["client"], "hi", sender=CUSTOMER)) == "Hi Ravi"
    assert reply_of(send(wa["client"], "hi", sender="+919123456789")) == "Hi Asha"
    assert len(storage.read_call_logs("demo_clinic")) == 2


def test_a_long_silence_starts_a_new_conversation(wa, monkeypatch):
    wa["scripts"].extend([[say("first")], [say("second")]])
    send(wa["client"], "hi")
    for s in telephony._wa_sessions.values():
        s["last"] -= telephony.WHATSAPP_IDLE
    assert reply_of(send(wa["client"], "hello again")) == "second"


def test_unknown_line_media_and_floods_get_short_answers(wa, monkeypatch):
    assert "isn't taking messages" in reply_of(send(wa["client"], "hi", to="+15550009999"))
    assert "only read text" in reply_of(send(wa["client"], "", NumMedia="1"))
    monkeypatch.setattr(telephony, "WHATSAPP_PER_SENDER", 2)
    wa["scripts"].append([say("one")])
    send(wa["client"], "a")                     # 1 (the media message above was 1 too)
    res = send(wa["client"], "b")               # 3rd in the window: silence, no model call
    assert res.status_code == 200 and reply_of(res) is None


def test_a_slow_reply_is_sent_through_the_api_instead(wa, monkeypatch):
    monkeypatch.setattr(telephony, "WHATSAPP_REPLY_WAIT_S", 0.05)
    sent = []
    monkeypatch.setattr(telephony, "send_whatsapp", lambda to, from_, body: sent.append((to, from_, body)))
    import threading
    gate = threading.Event()

    class Slow(FakeLLM):
        def send(self, messages, tools=None):
            gate.wait(5)
            return say("sorry for the wait")
    monkeypatch.setattr(telephony, "ReceptionistAgent",
                        lambda cid: ReceptionistAgent(cid, llm=Slow([])))
    res = send(wa["client"], "hi")
    assert reply_of(res) is None                # webhook answered empty, in time
    gate.set()
    for _ in range(100):
        if sent:
            break
        threading.Event().wait(0.02)
    assert [(to, frm) for to, frm, _ in sent] == [(CUSTOMER, LINE)]
    assert sent[0][2].endswith("sorry for the wait") and NOTICE in sent[0][2]


def test_the_twiml_reply_is_escaped(wa):
    wa["scripts"].append([say('<Redirect>http://evil</Redirect> & "x"')])
    res = send(wa["client"], "hi")
    root = ET.fromstring(res.text)
    assert root.find(".//Redirect") is None
    assert reply_of(res) == '<Redirect>http://evil</Redirect> & "x"'
