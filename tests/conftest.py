"""Shared test fixtures.

The tests run with NO network and NO API key: storage is redirected to a temp
folder, and the agent gets a FakeLLM with scripted responses. That FakeLLM is
the proof of architecture principle 6 — because the agent only knows the
neutral message format, ANY provider fits behind the seam, including a fake.
"""

import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scheduling  # noqa: E402
import storage  # noqa: E402


@pytest.fixture
def tmp_storage(tmp_path, monkeypatch):
    """Point every persistence path at a fresh temp folder."""
    monkeypatch.setattr(storage, "BOOKINGS_CSV", tmp_path / "bookings.csv")
    monkeypatch.setattr(storage, "LEADS_CSV", tmp_path / "leads.csv")
    monkeypatch.setattr(storage, "CALLS_DIR", tmp_path / "calls")
    monkeypatch.setenv("SHEET_ID", "")  # force the CSV fallback
    # Caches are keyed by path, but a temp file can reuse a path from an
    # earlier test — start every test from a cold cache.
    storage.clear_caches()
    yield tmp_path
    storage.clear_caches()


def open_day(client_id: str = "demo_clinic", skip: int = 0) -> str:
    """The next date this business actually has slots on.

    Tests used to hardcode a date ("2026-07-09"). That date quietly slid into
    the past and the suite kept passing while the agent could no longer book
    anything at all — the exact outage scheduling.py now prevents. Asking the
    schedule for a real open day keeps these tests honest forever.
    """
    config = storage.read_client_config(client_id) or {}
    slots = scheduling.available_slots(config, set())
    days = [d for d in sorted(slots) if slots[d]]
    if not days:
        raise AssertionError(f"{client_id} has no open days in its schedule")
    return days[min(skip, len(days) - 1)]


def open_times(client_id: str = "demo_clinic", date: str | None = None) -> list[str]:
    config = storage.read_client_config(client_id) or {}
    slots = scheduling.available_slots(config, set())
    return slots[date or open_day(client_id)]


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
