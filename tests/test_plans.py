"""plans.py — allowance, usage and what an invoice would say."""

import datetime as dt

import pytest

import plans
import storage

MONTH = dt.date.today().strftime("%Y-%m")
TODAY = dt.date.today().isoformat()


@pytest.fixture
def measured(monkeypatch):
    """Real-looking cost rates so margins are not flagged as guesses."""
    monkeypatch.setenv("COST_TELEPHONY_IN_PER_MIN", "1.00")
    monkeypatch.setenv("COST_MODEL_PER_MIN", "1.00")
    monkeypatch.setenv("COST_TTS_PER_1K_CHARS", "0")
    monkeypatch.setenv("COST_STT_PER_MIN", "0")
    monkeypatch.setenv("COST_MESSAGING_PER_CONVERSATION", "0")
    monkeypatch.setenv("COST_TELEPHONY_OUT_PER_MIN", "1.00")
    monkeypatch.setenv("COST_CURRENCY", "INR")


def fake_client(monkeypatch, plan=None, minutes=0.0, channel="phone"):
    """A business on `plan` that has used `minutes` of billable time."""
    config = {"business_name": "Test Clinic"}
    if plan is not None:
        config["billing"] = {"plan": plan, "paid_until": "2099-01-01"}
    monkeypatch.setattr(storage, "read_client_config", lambda cid: config)

    records = []
    if minutes:
        records.append({"channel": channel, "seconds": int(minutes * 60),
                        "started": f"{TODAY}T10:00:00", "transcript": ""})
    monkeypatch.setattr(storage, "read_call_logs", lambda cid: records)


# ---- plan resolution ---------------------------------------------------------------

def test_a_business_with_no_billing_block_is_internal(monkeypatch):
    """The hand-made demo clients predate billing and must never be capped."""
    fake_client(monkeypatch, plan=None)
    assert plans.plan_name("demo") == "free"
    assert plans.allowance("demo")["allowed"] is True


def test_the_old_flat_paid_plan_maps_to_clinic(monkeypatch):
    fake_client(monkeypatch, plan="paid")
    assert plans.plan_name("x") == "clinic"


def test_an_unknown_plan_falls_back_to_trial(monkeypatch):
    fake_client(monkeypatch, plan="enterprise-platinum")
    assert plans.plan_name("x") == "trial"


# ---- usage --------------------------------------------------------------------------

def test_only_billable_channels_count(monkeypatch, measured):
    """The owner testing their own agent in the portal is not charged."""
    fake_client(monkeypatch, plan="clinic", minutes=10, channel="web-test")
    assert plans.usage("x")["minutes"] == 0.0

    fake_client(monkeypatch, plan="clinic", minutes=10, channel="phone")
    assert plans.usage("x")["minutes"] == 10.0


def test_usage_ignores_other_months(monkeypatch, measured):
    config = {"billing": {"plan": "clinic"}}
    monkeypatch.setattr(storage, "read_client_config", lambda cid: config)
    monkeypatch.setattr(storage, "read_call_logs", lambda cid: [
        {"channel": "phone", "seconds": 600, "started": "2020-01-01T10:00:00",
         "transcript": ""},
    ])
    assert plans.usage("x")["minutes"] == 0.0


# ---- the invoice ----------------------------------------------------------------------

def test_inside_the_bundle_there_is_no_overage(monkeypatch, measured):
    fake_client(monkeypatch, plan="clinic", minutes=100)
    bill = plans.invoice("x")
    assert bill["overage_minutes"] == 0 and bill["overage_amount"] == 0
    assert bill["total"] == 1499
    assert bill["minutes_remaining"] == 200


def test_beyond_the_bundle_overage_is_charged(monkeypatch, measured):
    fake_client(monkeypatch, plan="clinic", minutes=400)      # 100 over 300
    bill = plans.invoice("x")
    assert bill["overage_minutes"] == 100
    assert bill["overage_amount"] == 450.0                     # 100 * 4.50
    assert bill["total"] == 1949.0


def test_the_invoice_shows_margin_against_what_it_cost_us(monkeypatch, measured):
    fake_client(monkeypatch, plan="clinic", minutes=100)
    bill = plans.invoice("x")
    # 100 min at (1.00 line + 1.00 model) = 200 to serve, against 1499
    assert bill["cost_to_serve"] == 200.0
    assert bill["margin"] == 1299.0
    assert bill["cost_assumed"] is False


def test_margin_is_flagged_as_a_guess_when_rates_are_placeholders(monkeypatch):
    for key in ("COST_TELEPHONY_IN_PER_MIN", "COST_MODEL_PER_MIN",
                "COST_TTS_PER_1K_CHARS", "COST_STT_PER_MIN",
                "COST_MESSAGING_PER_CONVERSATION", "COST_TELEPHONY_OUT_PER_MIN"):
        monkeypatch.delenv(key, raising=False)
    fake_client(monkeypatch, plan="clinic", minutes=10)
    assert plans.invoice("x")["cost_assumed"] is True


def test_usage_pricing_stays_profitable_where_the_flat_plan_did_not(monkeypatch, measured):
    """The busy clinic that broke flat pricing (STRATEGY §5) now pays for itself."""
    fake_client(monkeypatch, plan="clinic", minutes=600)
    bill = plans.invoice("x")
    assert bill["minutes_used"] == 600
    assert bill["total"] > bill["cost_to_serve"]      # the whole point
    assert bill["margin"] > 0


# ---- allowance -------------------------------------------------------------------------

def test_a_trial_stops_when_its_minutes_run_out(monkeypatch, measured):
    fake_client(monkeypatch, plan="trial", minutes=61)
    allow = plans.allowance("x")
    assert allow["allowed"] is False
    assert "Trial" in allow["reason"]


def test_a_trial_inside_its_minutes_still_works(monkeypatch, measured):
    fake_client(monkeypatch, plan="trial", minutes=10)
    assert plans.allowance("x")["allowed"] is True
    assert plans.allowance("x")["minutes_remaining"] == 50


def test_a_paying_clinic_is_never_cut_off_mid_day(monkeypatch, measured):
    """Overage bills; it does not silence a clinic's phone line."""
    fake_client(monkeypatch, plan="clinic", minutes=5000)
    allow = plans.allowance("x")
    assert allow["allowed"] is True
    assert plans.invoice("x")["overage_amount"] > 0


def test_channels_follow_the_plan(monkeypatch):
    fake_client(monkeypatch, plan="clinic")
    assert plans.channels("x") == 1
    fake_client(monkeypatch, plan="growth")
    assert plans.channels("x") == 3


# ---- the margin rule ---------------------------------------------------------------------

def test_price_check_flags_a_plan_that_is_too_cheap_to_serve():
    """At Rs 2/min cost the floor is Rs 6/min, which both plans fail."""
    check = plans.price_check(2.0)
    assert check["min_sell_per_minute"] == 6.0
    assert check["plans"]["clinic"]["safe"] is False      # 1499/300 = ~5/min

    cheap = plans.price_check(1.0)                        # floor 3/min
    assert cheap["plans"]["clinic"]["safe"] is True
