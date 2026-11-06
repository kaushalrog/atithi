"""live_main.py — the live mic channel's event wiring, driven by a fake Live
session (no microphone, no speaker, no network)."""

import asyncio

from agent import ReceptionistAgent, TurnRecorder
from conftest import open_day
import live_main


class ScriptedLive:
    """Plays back a fixed list of Live events and records what was sent."""

    def __init__(self, events):
        self._events = events
        self.tool_results = []

    async def events(self):
        for event in self._events:
            yield event

    async def send_tool_results(self, results):
        self.tool_results.append(results)


def run_events(fake_llm, events):
    agent = ReceptionistAgent("demo_clinic", llm=fake_llm([]))
    live, turn, playback, said = ScriptedLive(events), TurnRecorder(agent), bytearray(), []
    asyncio.run(live_main.pump_events(live, turn, playback, say=said.append))
    return agent, live, turn, playback, said


def test_a_turn_is_written_in_order_and_tools_answer_the_model(tmp_storage, fake_llm):
    date = open_day()
    agent, live, _turn, playback, said = run_events(fake_llm, [
        {"type": "user_text", "text": "any slots tomorrow?"},
        {"type": "tool_calls", "calls": [{"id": "t1", "name": "check_availability",
                                          "args": {"date": date}}]},
        {"type": "audio", "data": b"\x01\x02"},
        {"type": "agent_text", "text": "Yes, 10 AM is free."},
        {"type": "turn_complete"},
    ])
    assert [m["role"] for m in agent.history] == ["user", "assistant", "tool", "assistant"]
    assert live.tool_results[0][0]["id"] == "t1"           # the model got its answer
    assert playback == bytearray(b"\x01\x02")               # the voice was queued to play
    assert "You said: any slots tomorrow?" in said


def test_barge_in_silences_the_agent_and_closes_its_turn(tmp_storage, fake_llm):
    agent, _live, _turn, playback, _said = run_events(fake_llm, [
        {"type": "user_text", "text": "hello"},
        {"type": "audio", "data": b"\x01" * 100},
        {"type": "agent_text", "text": "Our timings are"},
        {"type": "interrupted"},                            # the caller talks over it
    ])
    assert playback == bytearray()                          # silent at once
    assert [m["text"] for m in agent.history] == ["hello", "Our timings are"]


def test_a_turn_cut_off_mid_way_is_still_recorded(tmp_storage, fake_llm):
    """Ctrl+C ends the stream with no turn_complete; run() flushes in finally."""
    agent, _live, turn, _playback, _said = run_events(fake_llm, [
        {"type": "user_text", "text": "book me for"},
    ])
    assert agent.history == []                              # nothing written yet...
    turn.flush()                                            # ...run()'s finally block
    assert agent.history[0]["text"] == "book me for"
