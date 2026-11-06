"""costs.py — what a conversation costs, and whether we know or are guessing."""

import pytest

import costs

RATES = {
    "COST_TELEPHONY_IN_PER_MIN": "1.00",
    "COST_TELEPHONY_OUT_PER_MIN": "2.00",
    "COST_MODEL_PER_MIN": "3.00",
    "COST_TTS_PER_1K_CHARS": "10.00",
    "COST_STT_PER_MIN": "0",
    "COST_MESSAGING_PER_CONVERSATION": "0.50",
}


@pytest.fixture
def measured(monkeypatch):
    """A fully measured rate card, so nothing is a placeholder."""
    for key, value in RATES.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("COST_CURRENCY", "INR")
    return costs.rate_card()


def call(channel="phone", seconds=120, transcript=""):
    return {"channel": channel, "seconds": seconds, "transcript": transcript}


def test_unmeasured_rates_are_flagged_as_assumed(monkeypatch):
    """The most important field here: do not price off a guess."""
    for key in RATES:
        monkeypatch.delenv(key, raising=False)
    cost = costs.cost_for(call())
    assert cost["assumed"] is True
    assert costs.rate_card()["assumed"]


def test_measured_rates_are_not_assumed(measured):
    assert costs.cost_for(call())["assumed"] is False
    assert costs.rate_card()["assumed"] == []


def test_a_phone_call_pays_for_the_line_and_the_model(measured):
    cost = costs.cost_for(call("phone", seconds=120))     # 2 minutes
    assert cost["breakdown"] == {"telephony": 2.0, "model": 6.0}
    assert cost["total"] == 8.0
    assert cost["per_minute"] == 4.0
    assert cost["billable"] is True


def test_an_outbound_callback_uses_the_outbound_rate(measured):
    cost = costs.cost_for(call("callback", seconds=60))
    assert cost["breakdown"]["telephony"] == 2.0          # not the inbound 1.00


def test_the_owners_own_test_call_is_not_billable(measured):
    """The portal widget costs us money but earns none — keep it out of
    cost-per-billable-minute or the unit economics look worse than they are."""
    cost = costs.cost_for(call("web-test", seconds=60))
    assert cost["billable"] is False
    assert "telephony" not in cost["breakdown"]


def test_whatsapp_pays_per_conversation_not_per_minute(measured):
    cost = costs.cost_for(call("whatsapp", seconds=600))
    assert cost["breakdown"]["messaging"] == 0.5


def test_tts_is_charged_on_what_the_agent_actually_said(measured):
    transcript = "Customer: hi\n\nAgent: " + "x" * 1000 + "\n"
    cost = costs.cost_for(call("web-test", seconds=60, transcript=transcript))
    assert cost["breakdown"]["tts"] == pytest.approx(10.0, rel=0.01)
    assert costs.agent_chars({"transcript": transcript}) == 1000


def test_a_zero_length_call_costs_nothing_and_does_not_divide_by_zero(measured):
    cost = costs.cost_for(call("phone", seconds=0))
    assert cost["total"] == 0.0 and cost["per_minute"] == 0.0


def test_summary_separates_billable_from_internal(measured):
    records = [call("phone", 60), call("phone", 60), call("web-test", 600)]
    summary = costs.summarise(records)
    assert summary["calls"] == 3
    assert summary["billable_calls"] == 2
    assert summary["billable_minutes"] == 2.0
    # 2 billable minutes at 1.00 line + 3.00 model = 8.00 over 2 minutes
    assert summary["cost_per_minute"] == 4.0
    assert set(summary["by_channel"]) == {"phone", "web-test"}


def test_summary_reports_assumed_if_any_call_used_a_guess(monkeypatch):
    for key in RATES:
        monkeypatch.delenv(key, raising=False)
    assert costs.summarise([call()])["assumed"] is True


def test_the_flat_plan_loses_money_on_a_busy_client(measured):
    """The trap in docs/STRATEGY.md §5, as an executable fact.

    600 billable minutes a month at a 4.00/min cost is 2,400 against a
    1,999 flat plan. If this test ever starts failing because the rates
    improved, the pricing page can change — but not before.
    """
    busy_month = [call("phone", seconds=120) for _ in range(300)]   # 600 minutes
    summary = costs.summarise(busy_month)
    assert summary["billable_minutes"] == 600.0
    flat_plan_revenue = 1999.0
    assert summary["cost"] > flat_plan_revenue
