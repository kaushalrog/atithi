"""Shared test fixtures.

The tests run with NO network and NO API key: storage is redirected to a temp
folder, and the agent gets a FakeLLM with scripted responses. That FakeLLM is
the proof of architecture principle 6 — because the agent only knows the
neutral message format, ANY provider fits behind the seam, including a fake.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import storage  # noqa: E402


@pytest.fixture
def tmp_storage(tmp_path, monkeypatch):
    """Point every persistence path at a fresh temp folder."""
    monkeypatch.setattr(storage, "BOOKINGS_CSV", tmp_path / "bookings.csv")
    monkeypatch.setattr(storage, "LEADS_CSV", tmp_path / "leads.csv")
    monkeypatch.setattr(storage, "CALLS_DIR", tmp_path / "calls")
    monkeypatch.setenv("SHEET_ID", "")  # force the CSV fallback
    return tmp_path


class FakeLLM:
    """A scripted stand-in for GeminiLLM: returns canned responses in order."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []  # everything the agent sent, for assertions

    def send(self, messages, tools=None):
        self.requests.append({"messages": list(messages), "tools": tools})
        if self.responses:
            return self.responses.pop(0)
        return {"text": "(out of script)", "tool_calls": []}


@pytest.fixture
def fake_llm():
    return FakeLLM
