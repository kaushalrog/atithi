"""Unanswered questions: noted by the receptionist, answered once by the
owner, then part of the FAQ the receptionist uses."""

import shutil

import pytest
import yaml
from fastapi.testclient import TestClient

import server
import storage
from agent import ReceptionistAgent
from conftest import FakeLLM

DEMO_KEY = "VX-84KQ2N"


@pytest.fixture
def client(tmp_storage, monkeypatch):
    import auth
    clients = tmp_storage / "clients"
    shutil.copytree(storage.CLIENTS_DIR, clients)
    monkeypatch.setattr(storage, "CLIENTS_DIR", clients)
    monkeypatch.setattr(auth, "DB_FILE", tmp_storage / "voxagent.db")
    monkeypatch.setattr(auth, "LEGACY_USERS", tmp_storage / "no_users.json")
    monkeypatch.setattr(auth, "LEGACY_TOKENS", tmp_storage / "no_tokens.json")
    storage.clear_caches()
    return TestClient(server.app)


def ask(agent, question):
    return agent.run_tool({"name": "note_unanswered_question", "args": {"question": question}})["result"]


def test_repeats_are_counted_as_one_question(tmp_storage):
    agent = ReceptionistAgent("demo_clinic", llm=FakeLLM([]))
    assert ask(agent, "Do you have parking?")["times_asked"] == 1
    assert ask(agent, "do you have  parking")["times_asked"] == 2      # case, spaces, punctuation
    assert ask(agent, "Is Dr. Rao in on Sundays?")["times_asked"] == 1
    qs = storage.open_questions("demo_clinic")
    assert [(q["question"], q["asked"]) for q in qs] == [("Do you have parking?", 2),
                                                        ("Is Dr. Rao in on Sundays?", 1)]
    assert storage.open_questions("lakshmi_beauty_salon") == []        # per business


def test_answering_adds_an_faq_the_receptionist_then_uses(client):
    agent = ReceptionistAgent("demo_clinic", llm=FakeLLM([]))
    ask(agent, "Do you have parking?")
    h = {"X-Client-Key": DEMO_KEY}
    [q] = client.get("/api/questions?client_id=demo_clinic", headers=h).json()
    assert client.get("/api/dashboard?client_id=demo_clinic", headers=h).json()["open_questions"] == 1
    assert client.post("/api/questions/answer", json={"client_id": "demo_clinic", "question_id": q["id"],
                                                      "answer": ""}, headers=h).status_code == 422
    res = client.post("/api/questions/answer", json={"client_id": "demo_clinic", "question_id": q["id"],
                                                     "answer": "Yes, free parking behind the building."}, headers=h)
    assert res.status_code == 200
    cfg = yaml.safe_load((storage.CLIENTS_DIR / "demo_clinic.yaml").read_text(encoding="utf-8"))
    assert {"q": "Do you have parking?", "a": "Yes, free parking behind the building."} in cfg["faq"]
    assert "free parking behind the building" in ReceptionistAgent("demo_clinic", llm=FakeLLM([])).system_prompt
    assert client.get("/api/questions?client_id=demo_clinic", headers=h).json() == []
    again = client.post("/api/questions/answer", json={"client_id": "demo_clinic", "question_id": q["id"],
                                                       "answer": "x"}, headers=h)
    assert again.status_code == 404


def test_dismiss_and_other_businesses_cannot_touch_it(client):
    agent = ReceptionistAgent("demo_clinic", llm=FakeLLM([]))
    ask(agent, "What's the wifi password?")
    [q] = storage.open_questions("demo_clinic")
    other = {"X-Client-Key": "VX-7TPX3R"}
    assert client.get("/api/questions?client_id=demo_clinic", headers=other).status_code == 401
    assert client.post("/api/questions/dismiss", json={"client_id": "demo_clinic", "question_id": q["id"]},
                       headers=other).status_code == 401
    assert client.post("/api/questions/dismiss", json={"client_id": "demo_clinic", "question_id": q["id"]},
                       headers={"X-Client-Key": DEMO_KEY}).status_code == 200
    assert storage.open_questions("demo_clinic") == []
    ask(agent, "What's the wifi password?")                    # asked again after dismissal: back as new
    assert storage.open_questions("demo_clinic")[0]["asked"] == 1
