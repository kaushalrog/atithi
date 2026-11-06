"""billing.py — who's on trial, who's paid, who's paused.

The billing state of a business lives in a `billing:` block inside its client
YAML (single source of truth, visible to the admin in plain text):

    billing:
      plan: trial | paid
      paid_until: "2026-07-17"
      renewal_requested: "2026-07-15T18:30:00"   # owner says "I've paid"

A business with NO billing block is inactive: a missing block must never
mean "free forever" (security audit H5). Internal/demo businesses say so
explicitly with `billing: {plan: free}`. Money flow at this stage: the owner pays by UPI,
clicks "I've paid" (request_renewal), the admin sees the claim in the console
and extends the plan (set_paid_until). A payment gateway slots into exactly
these two functions later.
"""

import datetime as dt
import os

import storage

TRIAL_DAYS = 7


def new_trial() -> dict:
    """The billing block every freshly onboarded business starts with."""
    return {"plan": "trial",
            "paid_until": (dt.date.today() + dt.timedelta(days=TRIAL_DAYS)).isoformat()}


def _is_active(billing: dict | None) -> bool:
    if not billing:
        return False  # fail closed: no block is a mistake, not a free plan
    if str(billing.get("plan", "")).strip().lower() == "free":
        return True   # an internal/demo business, marked as such on purpose
    return str(billing.get("paid_until", "")) >= dt.date.today().isoformat()


def client_active(client_id: str) -> bool:
    """May this business use the agent (portal sessions + phone calls)?

    Two gates: the plan must not have lapsed, and a TRIAL must not have used
    up its free minutes. Wiring the minutes gate here rather than at each
    caller means every existing check — the portal session, the inbound
    webhook, the stream, the callback worker — picks it up at once.

    A paying business is never stopped by minutes; it bills overage instead
    (plans.allowance). Cutting off a clinic's phone line mid-day over a
    threshold would cost them, and us, far more than the minutes.
    """
    cfg = storage.read_client_config(client_id)
    if cfg is None:
        return False
    if not _is_active(cfg.get("billing")):
        return False
    try:
        import plans
        return plans.allowance(client_id)["allowed"]
    except Exception as e:
        # A metering bug must never take a paying clinic off the air.
        print(f"  [billing] allowance check failed for {client_id}: {e}")
        return True


def status(client_id: str) -> dict:
    """Everything the dashboard's billing banner needs (one config read)."""
    cfg = storage.read_client_config(client_id) or {}
    billing = cfg.get("billing") or {}
    paid_until = str(billing.get("paid_until", ""))
    days_left = None
    if paid_until:
        days_left = (dt.date.fromisoformat(paid_until) - dt.date.today()).days
    return {
        "plan": billing.get("plan", "free"),
        "paid_until": paid_until or None,
        "days_left": days_left,
        "active": _is_active(cfg.get("billing")),
        "renewal_requested": billing.get("renewal_requested"),
        "price_inr": int(os.getenv("BILLING_PRICE_INR", "1999")),
        "upi": os.getenv("BILLING_UPI", ""),
    }


def request_renewal(client_id: str) -> dict:
    """The owner says they've paid — flag it for the admin to confirm."""
    cfg = storage.read_client_config(client_id)
    if cfg is None:
        raise LookupError(f"No client '{client_id}'")
    # storage hands back the shared cached parse; copy before editing.
    cfg = dict(cfg)
    billing = dict(cfg.get("billing") or new_trial())
    billing["renewal_requested"] = dt.datetime.now().isoformat(timespec="seconds")
    cfg["billing"] = billing
    storage.write_client_config(client_id, cfg)
    return status(client_id)


def set_paid_until(client_id: str, months: int) -> str:
    """Admin confirms payment: extend the plan; returns the new end date.
    Extends from whichever is later — today or the current end — so paying
    early never costs days."""
    cfg = storage.read_client_config(client_id)
    if cfg is None:
        raise LookupError(f"No client '{client_id}'")
    cfg = dict(cfg)                              # never mutate the shared cache
    billing = dict(cfg.get("billing") or {})
    base = max(dt.date.today(),
               dt.date.fromisoformat(str(billing.get("paid_until", dt.date.today().isoformat()))))
    billing["plan"] = "paid"
    billing["paid_until"] = (base + dt.timedelta(days=30 * months)).isoformat()
    billing.pop("renewal_requested", None)  # claim confirmed
    cfg["billing"] = billing
    storage.write_client_config(client_id, cfg)
    return billing["paid_until"]
