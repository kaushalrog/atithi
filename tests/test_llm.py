"""llm.py's retry policy, with a fake Gemini client (no network, no key)."""

import pytest

import llm
import perf


def rate_limited(delay_s: int):
    return llm.errors.APIError(429, {"error": {
        "code": 429, "message": "per-minute quota", "status": "RESOURCE_EXHAUSTED",
        "details": [{"retryDelay": f"{delay_s}s"}]}})


class FakeModels:
    def __init__(self, failures):
        self.failures, self.calls = list(failures), 0

    def generate_content(self, **kwargs):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return "ok"


def gemini_with(failures, monkeypatch):
    model = llm.GeminiLLM.__new__(llm.GeminiLLM)        # skip building a real client
    model.model = "fake"
    model.client = type("C", (), {"models": FakeModels(failures)})()
    slept = []
    monkeypatch.setattr(llm.time, "sleep", slept.append)
    return model, slept


def test_retries_stop_at_the_wait_budget(monkeypatch):
    """Perf audit F5: three 429s asking for 20 s each used to hold the request
    for ~60-75 s; now it gives up once waiting would pass RETRY_BUDGET_S."""
    perf.reset()
    model, slept = gemini_with([rate_limited(19)] * 3, monkeypatch)
    with pytest.raises(llm.errors.APIError):
        model._call_with_retry([], None)
    assert sum(slept) <= llm.RETRY_BUDGET_S
    assert slept == [20]
    assert perf.snapshot()["events"]["timeout.model_retry_budget"] == 1


def test_a_short_rate_limit_still_retries_and_succeeds(monkeypatch):
    model, slept = gemini_with([rate_limited(4), rate_limited(4)], monkeypatch)
    assert model._call_with_retry([], None) == "ok"
    assert slept == [5, 5]


def test_server_errors_back_off_within_the_budget(monkeypatch):
    err = llm.errors.APIError(503, {"error": {"code": 503, "message": "busy",
                                              "status": "UNAVAILABLE"}})
    model, slept = gemini_with([err, err, err], monkeypatch)
    assert model._call_with_retry([], None) == "ok"
    assert slept == [2, 4, 6] and sum(slept) <= llm.RETRY_BUDGET_S
