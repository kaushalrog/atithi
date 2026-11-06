"""billing.py — a business is active only when its billing block says so.

Security audit H5: a missing block used to mean "always active", so a
hand-made or half-written config was free forever. It now fails closed.
"""

import datetime as dt

import billing


def _days(n: int) -> str:
    return (dt.date.today() + dt.timedelta(days=n)).isoformat()


def test_no_billing_block_is_inactive():
    assert billing._is_active(None) is False
    assert billing._is_active({}) is False


def test_an_explicit_free_plan_is_active():
    assert billing._is_active({"plan": "free"}) is True
    assert billing._is_active({"plan": "FREE "}) is True


def test_paid_and_trial_follow_paid_until():
    assert billing._is_active({"plan": "trial", "paid_until": _days(3)}) is True
    assert billing._is_active({"plan": "paid", "paid_until": _days(-1)}) is False


def test_a_config_without_billing_cannot_take_calls(tmp_storage, monkeypatch):
    import storage
    monkeypatch.setattr(storage, "read_client_config",
                        lambda client_id: {"client_id": client_id, "business_name": "X"})
    assert billing.client_active("anyone") is False


def test_the_demo_businesses_are_marked_free_on_purpose():
    import storage
    for client_id in ("demo_clinic", "lakshmi_beauty_salon"):
        assert storage.read_client_config(client_id)["billing"]["plan"] == "free"
