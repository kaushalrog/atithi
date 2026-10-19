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
    # A clock that moves only when we "sleep": attempts take no time unless a
    # test says otherwise.
    monkeypatch.setattr(llm.time, "monotonic", lambda: float(sum(slept)))
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


def test_the_budget_counts_time_spent_in_attempts_too(monkeypatch):
    """Review D4: only the sleeps were counted, so slow failing attempts
    (each up to the 30 s request timeout) could hold a request for minutes."""
    clock = [0.0]
    err = llm.errors.APIError(503, {"error": {"code": 503, "message": "busy",
                                              "status": "UNAVAILABLE"}})
    model, slept = gemini_with([err, err, err], monkeypatch)
    real = model.client.models.generate_content

    def slow(**kw):
        clock[0] += 15                          # each attempt takes 15 s
        return real(**kw)
    model.client.models.generate_content = slow
    monkeypatch.setattr(llm.time, "monotonic", lambda: clock[0] + sum(slept))
    with pytest.raises(llm.errors.APIError):
        model._call_with_retry([], None)
    assert slept == [2]                         # 15 + 2 fits in 25 s; 32 + 4 does not
    assert model.client.models.calls == 2


def test_a_wait_longer_than_the_budget_is_not_retried(monkeypatch):
    """Google asks for 40 s (capped at 25 s); after an attempt that took 1 s
    that no longer fits the 25 s deadline, so the request fails fast and the
    portal answers with the front-desk line instead of a long silence."""
    model, slept = gemini_with([rate_limited(40)], monkeypatch)
    monkeypatch.setattr(llm.time, "monotonic", lambda: 1.0 + sum(slept) if model.client.models.calls else 0.0)
    with pytest.raises(llm.errors.APIError):
        model._call_with_retry([], None)
    assert slept == [] and model.client.models.calls == 1
