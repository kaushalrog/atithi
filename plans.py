"""plans.py — what a business is allowed to use, and what it owes.

WHY this replaces a flat monthly fee: every call costs us money by the minute
(telephony + model + speech), so one flat price loses money on exactly the
customers we most want — the busy ones. `costs.py` measures the cost side;
this file is the price side, and it is deliberately the same shape the market
already uses: a small platform fee that includes a bundle of minutes, then a
per-minute rate beyond it.

    Trial    free        60 min      1 channel
    Clinic   Rs 1,499    300 min     Rs 4.50/min after   1 channel
    Growth   Rs 3,999    1,000 min   Rs 4.00/min after   3 channels

A "channel" is one simultaneous call, which is also our real engineering
limit — concurrent model sessions. Selling the limit we actually have beats
pretending we have none.

Nothing here charges a card. It computes allowance, usage and what an invoice
would say, so the dashboard can show it and the admin can act on it. A payment
gateway later replaces `billing.set_paid_until` and nothing in this file.

Minutes counted are BILLABLE minutes only (real phone and WhatsApp
conversations). The owner trying their own agent in the portal is not billed —
charging someone to test the thing they are deciding whether to buy is a good
way to lose the sale.
"""

import datetime as dt
import os

import costs
import storage

# Prices in rupees. Every number here is a hypothesis until a customer pays it
# (docs/STRATEGY.md §5) — and none of it is safe until costs.py reports a
# measured cost per minute, because the margin rule below depends on it.
PLANS = {
    "trial": {
        "label": "Trial",
        "monthly": 0,
        "included_minutes": 60,
        "overage_per_min": 0.0,      # trial stops instead of billing
        "channels": 1,
        "stop_at_limit": True,
    },
    "clinic": {
        "label": "Clinic",
        "monthly": 1499,
        "included_minutes": 300,
        "overage_per_min": 4.5,
        "channels": 1,
        "stop_at_limit": False,
    },
    "growth": {
        "label": "Growth",
        "monthly": 3999,
        "included_minutes": 1000,
        "overage_per_min": 4.0,
        "channels": 3,
        "stop_at_limit": False,
    },
    # Hand-made demo businesses predate billing and are never charged or capped.
    "free": {
        "label": "Internal",
        "monthly": 0,
        "included_minutes": 10 ** 6,
        "overage_per_min": 0.0,
        "channels": 2,
        "stop_at_limit": False,
    },
}

DEFAULT_PLAN = "trial"

#: Sell at no less than this multiple of measured cost. Below it there is no
#: room for free trials, failed calls, support and GST.
MARGIN_MULTIPLE = 3.0


def plan_name(client_id: str) -> str:
    """Which plan a business is on, from its billing block."""
    config = storage.read_client_config(client_id) or {}
    billing = config.get("billing") or {}
    # `paid` is the old flat plan: treat it as Clinic until it is migrated.
    name = str(billing.get("plan") or "").strip().lower()
    if name == "paid":
        name = "clinic"
    return name if name in PLANS else ("free" if not billing else DEFAULT_PLAN)


def plan_for(client_id: str) -> dict:
    name = plan_name(client_id)
    return dict(PLANS[name], name=name)


def month_key(when: dt.date | None = None) -> str:
    when = when or dt.date.today()
    return when.strftime("%Y-%m")


def usage(client_id: str, month: str | None = None) -> dict:
    """Billable minutes used this month, and what they cost us to serve."""
    month = month or month_key()
    billable_minutes = 0.0
    billable_calls = 0
    cost = 0.0
    for record in storage.read_call_logs(client_id):
        if not str(record.get("started", "")).startswith(month):
            continue
        line = record.get("cost") or costs.cost_for(record)
        if not line.get("billable"):
            continue
        billable_calls += 1
        billable_minutes += (record.get("seconds") or 0) / 60
        cost += line.get("total", 0.0)
    return {
        "month": month,
        "calls": billable_calls,
        "minutes": round(billable_minutes, 2),
        "cost_to_serve": round(cost, 2),
    }


def invoice(client_id: str, month: str | None = None) -> dict:
    """What this business would be billed for the month, and our margin on it."""
    plan = plan_for(client_id)
    used = usage(client_id, month)
    over = max(0.0, used["minutes"] - plan["included_minutes"])
    overage = round(over * plan["overage_per_min"], 2)
    total = round(plan["monthly"] + overage, 2)
    margin = round(total - used["cost_to_serve"], 2)
    return {
        "client_id": client_id,
        "month": used["month"],
        "plan": plan["name"],
        "plan_label": plan["label"],
        "calls": used["calls"],
        "monthly": plan["monthly"],
        "included_minutes": plan["included_minutes"],
        "minutes_used": used["minutes"],
        "minutes_remaining": round(max(0.0, plan["included_minutes"] - used["minutes"]), 2),
        "overage_minutes": round(over, 2),
        "overage_per_min": plan["overage_per_min"],
        "overage_amount": overage,
        "total": total,
        "cost_to_serve": used["cost_to_serve"],
        "margin": margin,
        "margin_pct": round(margin / total * 100, 1) if total else 0.0,
        "currency": os.getenv("COST_CURRENCY", "INR"),
        # True while any cost rate is still a placeholder — the margin above is
        # then a guess, and must not be used to set a price.
        "cost_assumed": costs.rate_card()["assumed"] != [],
    }


def allowance(client_id: str, month: str | None = None) -> dict:
    """Can this business still take calls right now?

    Only a trial is stopped at its limit. A paying business keeps working and
    pays overage — cutting off a clinic's phone line mid-day over a billing
    threshold would do more damage to them, and to us, than the minutes cost.
    """
    plan = plan_for(client_id)
    used = usage(client_id, month)
    remaining = plan["included_minutes"] - used["minutes"]
    blocked = bool(plan["stop_at_limit"] and remaining <= 0)
    return {
        "allowed": not blocked,
        "reason": ("Trial minutes used up — choose a plan to keep taking calls."
                   if blocked else ""),
        "plan": plan["name"],
        "minutes_used": used["minutes"],
        "included_minutes": plan["included_minutes"],
        "minutes_remaining": round(max(0.0, remaining), 2),
        "channels": plan["channels"],
    }


def channels(client_id: str) -> int:
    """How many calls this business may take at once (its paid concurrency)."""
    return int(plan_for(client_id)["channels"])


def price_check(cost_per_minute: float) -> dict:
    """Is each plan's effective rate safely above our cost?

    Feeds the pricing rule in docs/STRATEGY.md §5: sell at >= 3x measured cost.
    """
    floor = round(cost_per_minute * MARGIN_MULTIPLE, 2)
    out = {"cost_per_minute": cost_per_minute, "min_sell_per_minute": floor, "plans": {}}
    for name, plan in PLANS.items():
        if not plan["included_minutes"] or plan["included_minutes"] > 10 ** 5:
            continue
        effective = plan["monthly"] / plan["included_minutes"] if plan["included_minutes"] else 0
        out["plans"][name] = {
            "effective_per_min_if_fully_used": round(effective, 2),
            "overage_per_min": plan["overage_per_min"],
            "safe": effective >= floor and (plan["overage_per_min"] == 0
                                            or plan["overage_per_min"] >= floor),
        }
    return out


def _report():
    from dotenv import load_dotenv
    load_dotenv()

    card = costs.rate_card()
    print(f"\n=== Plans and usage  ({month_key()}) ===\n")
    if card["assumed"]:
        print("  !! Cost rates are placeholders — margins below are guesses.")
        print("     Fill COST_* in .env (docs/STRATEGY.md §5) first.\n")

    for entry in storage.all_clients():
        client_id = entry["client_id"]
        bill = invoice(client_id)
        allow = allowance(client_id)
        name = entry["config"].get("business_name", client_id)
        print(f"  {name}  [{client_id}]")
        print(f"    plan      : {bill['plan_label']} "
              f"({bill['currency']} {bill['monthly']:,}/mo, "
              f"{bill['included_minutes']} min incl, {allow['channels']} channel(s))")
        print(f"    used      : {bill['minutes_used']} min "
              f"over {bill['calls']} billable calls")
        if bill["overage_minutes"]:
            print(f"    overage   : {bill['overage_minutes']} min "
                  f"= {bill['currency']} {bill['overage_amount']:,}")
        print(f"    invoice   : {bill['currency']} {bill['total']:,}   "
              f"cost {bill['currency']} {bill['cost_to_serve']:,}   "
              f"margin {bill['margin_pct']}%")
        if not allow["allowed"]:
            print(f"    BLOCKED   : {allow['reason']}")
        print()

    if not card["assumed"]:
        # Only meaningful once the rates are real.
        measured = costs.summarise(
            [r for e in storage.all_clients()
             for r in storage.read_call_logs(e["client_id"])])["cost_per_minute"]
        if measured:
            check = price_check(measured)
            print(f"  Measured cost/min {check['cost_per_minute']}, "
                  f"so sell at >= {check['min_sell_per_minute']}/min:")
            for name, row in check["plans"].items():
                flag = "ok" if row["safe"] else "TOO CHEAP"
                print(f"    {name:<8} {row['effective_per_min_if_fully_used']:>6}/min "
                      f"incl, {row['overage_per_min']:>5}/min over   {flag}")
            print()


if __name__ == "__main__":
    _report()
