"""perf.py: measurements are bounded, private, and never break a call."""

import asyncio
import datetime as dt
import json
import time

import pytest
from fastapi.testclient import TestClient

import perf
import server
import storage
from agent import ReceptionistAgent
from conftest import FakeLLM, open_day


@pytest.fixture(autouse=True)
def fresh_perf():
    perf.reset()
    yield
    perf.reset()
    storage.enable_perf_log(None)


def test_span_records_duration_count_and_percentiles():
    for _ in range(3):
        with perf.span("unit.block", tool="book_appointment"):
            time.sleep(0.002)
    snap = perf.snapshot()["spans"]["unit.block"]
    assert snap["count"] == 3 and snap["errors"] == 0
    assert 1.5 <= snap["p50"] <= snap["p99"] <= snap["max"]


def test_an_exception_counts_as_an_error_and_still_raises():
    with pytest.raises(KeyError):
        with perf.span("unit.fails"):
            raise KeyError("x")
    assert perf.snapshot()["spans"]["unit.fails"]["errors"] == 1


def test_a_label_outside_the_allowlist_raises_in_test_mode():
    # Message text, names and phone numbers must never become labels.
    with pytest.raises(ValueError, match="not allowed"):
        perf.record("unit.leak", 1.0, phone="9876543210")


def test_a_label_outside_the_allowlist_is_dropped_in_production(monkeypatch):
    monkeypatch.setenv("VOXAGENT_ENV", "production")
    seen = []
    perf.set_sink(seen.append)
    perf.record("unit.leak", 1.0, phone="9876543210", tool="save_lead")
    perf.set_sink(None)
    assert seen[0]["labels"] == {"tool": "save_lead"}
    assert perf.snapshot()["dropped"]["labels"] == 1


def test_memory_stays_bounded():
    for i in range(10_000):
        perf.record("unit.many", float(i))
    for i in range(perf.MAX_NAMES + 10):
        perf.record(f"unit.name{i}", 1.0)
    snap = perf.snapshot()
    assert snap["spans"]["unit.many"]["count"] == 10_000
    assert snap["spans"]["unit.many"]["samples"] == perf.SAMPLES_PER_SPAN
    assert len(snap["spans"]) == perf.MAX_NAMES
    assert snap["dropped"]["names"] == 11


def test_perf_log_lines_are_timezone_aware_json(tmp_path):
    log = tmp_path / "perf.jsonl"
    storage.enable_perf_log(log)
    with perf.span("unit.logged", call="abc123", outcome="reply"):
        pass
    assert storage._perf_log.drain(2) == 0
    line = json.loads(log.read_text().splitlines()[-1])
    assert line["name"] == "unit.logged" and line["call"] == "abc123"
    assert line["labels"] == {"outcome": "reply"}
    assert dt.datetime.fromisoformat(line["ts"]).utcoffset() is not None


def test_perf_log_rolls_over_at_the_size_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "PERF_LOG_MAX_BYTES", 300)
    log = tmp_path / "perf.jsonl"
    storage.enable_perf_log(log)
    for _ in range(20):
        perf.record("unit.roll", 1.0)
    assert storage._perf_log.drain(2) == 0
    assert log.with_name("perf.jsonl.1").exists()
    assert log.stat().st_size < 600


def test_perf_log_refuses_real_data_paths_in_test_mode():
    with pytest.raises(RuntimeError, match="refuses"):
        storage.enable_perf_log(storage.CALLS_DIR / "perf.jsonl")


def test_a_text_turn_records_rounds_tools_and_model_requests(tmp_storage):
    day = open_day()
    llm = FakeLLM([
        {"text": None, "tool_calls": [{"name": "check_availability", "args": {"date": day}}]},
        {"text": "We have slots.", "tool_calls": []},
    ])
    agent = ReceptionistAgent("demo_clinic", llm=llm)
    seen = []
    perf.set_sink(seen.append)
    agent.chat("any slots?")
    perf.set_sink(None)
    names = [r["name"] for r in seen]
    assert names == ["model.request", "tool", "model.request", "turn"]
    assert seen[1]["labels"] == {"tool": "check_availability", "status": "ok"}
    assert seen[-1]["labels"] == {"rounds": "2", "outcome": "reply"}
    assert {r["call"] for r in seen} == {agent.perf_id}
    # Nothing the customer said reaches a measurement.
    assert "any slots" not in json.dumps(seen)


def test_a_made_up_tool_name_is_not_a_label(tmp_storage):
    agent = ReceptionistAgent("demo_clinic", llm=FakeLLM([]))
    seen = []
    perf.set_sink(seen.append)
    agent.run_tool({"name": "rm -rf / please", "args": {}})
    perf.set_sink(None)
    assert seen[0]["labels"]["tool"] == "unknown"


def test_loop_monitor_is_one_task_per_loop():
    async def main():
        perf.ensure_loop_monitor(period=0.01)
        perf.ensure_loop_monitor(period=0.01)
        await asyncio.sleep(0.05)
        time.sleep(0.05)               # block the loop on purpose
        await asyncio.sleep(0.03)
        return [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

    others = asyncio.run(main())
    assert len(others) == 1
    lag = perf.snapshot()["spans"]["loop.lag"]
    assert lag["max"] >= 30


def test_perf_endpoint_is_admin_only(tmp_storage, monkeypatch):
    import auth
    monkeypatch.setattr(auth, "DB_FILE", tmp_storage / "voxagent.db")
    monkeypatch.setattr(auth, "LEGACY_USERS", tmp_storage / "no_users.json")
    monkeypatch.setattr(auth, "LEGACY_TOKENS", tmp_storage / "no_tokens.json")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-pw")
    client = TestClient(server.app)
    assert client.get("/api/admin/perf").status_code in (401, 503)
    assert client.get("/api/admin/perf",
                      headers={"X-Client-Key": "VX-84KQ2N"}).status_code in (401, 503)
    res = client.get("/api/admin/perf", headers={"X-Admin-Key": "test-admin-pw"})
    assert res.status_code == 200
    assert {"spans", "events", "gauges"} <= set(res.json())


def test_a_model_error_is_a_failed_turn_and_still_raises(tmp_storage):
    class Down:
        def send(self, *a, **k):
            raise RuntimeError("model down")
    agent = ReceptionistAgent("demo_clinic", llm=Down())
    seen = []
    perf.set_sink(seen.append)
    with pytest.raises(RuntimeError, match="model down"):
        agent.chat("hi")
    perf.set_sink(None)
    [turn] = [r for r in seen if r["name"] == "turn"]
    assert turn["ok"] is False and turn["labels"]["outcome"] == "error"
    assert [r["ok"] for r in seen if r["name"] == "model.request"] == [False]


def test_five_tool_rounds_without_a_reply_is_a_round_limit_turn(tmp_storage):
    day = open_day()
    call = {"text": None, "tool_calls": [{"name": "check_availability", "args": {"date": day}}]}
    agent = ReceptionistAgent("demo_clinic", llm=FakeLLM([call] * 5))
    seen = []
    perf.set_sink(seen.append)
    agent.chat("slots?")
    perf.set_sink(None)
    [turn] = [r for r in seen if r["name"] == "turn"]
    assert turn["labels"] == {"rounds": "5", "outcome": "round_limit"} and turn["ok"] is True


def test_loop_lag_samples_stay_out_of_the_jsonl_log():
    """Four samples a second would roll real call spans out of the 20 MB log."""
    seen = []
    perf.set_sink(seen.append)
    perf.record("loop.lag", 1.0, log=False)
    perf.record("tool", 1.0)
    perf.set_sink(None)
    assert [r["name"] for r in seen] == ["tool"]
    assert perf.snapshot()["spans"]["loop.lag"]["count"] == 1
