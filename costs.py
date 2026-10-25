"""costs.py — what one conversation actually costs us.

WHY this exists: we sell a flat monthly plan while every call costs money by
the minute (telephony + model + speech). That is the shape of deal that loses
money on exactly the customers we most want — the busy ones. Before any
pricing decision we have to know the cost of a minute, and before that we have
to measure it instead of guessing.

So every call record now carries a `cost` block, and `python costs.py` reports
what a business is costing us against what it pays.

**Read the `assumed` flag.** Rates come from `.env`; anything not set there
falls back to a placeholder below. A placeholder is a guess, not a measurement
— the report marks those numbers clearly, and `docs/STRATEGY.md` §5 has the
worksheet to replace them with real invoice figures.

Set the measured rates in `.env`:

    COST_CURRENCY=INR
    COST_TELEPHONY_IN_PER_MIN=0.60      # from the Twilio/Exotel/Plivo invoice
    COST_TELEPHONY_OUT_PER_MIN=1.20
    COST_MODEL_PER_MIN=2.00             # Gemini Live audio, in + out
    COST_TTS_PER_1K_CHARS=0.40          # cascaded path only
    COST_STT_PER_MIN=0.00               # included in Live; set if cascaded
    COST_MESSAGING_PER_CONVERSATION=0.35  # WhatsApp
"""

import datetime as dt
import os
import sys

# Placeholders only. Every one of these is a guess until it is measured and
# written into .env — the report says so rather than quietly looking precise.
DEFAULT_RATES = {
    "telephony_in_per_min": 0.60,
    "telephony_out_per_min": 1.20,
    "model_per_min": 2.00,
    "tts_per_1k_chars": 0.40,
    "stt_per_min": 0.00,
    "messaging_per_conversation": 0.35,
}

# Which cost lines each channel actually incurs.
#   phone / callback  — a real phone line: telephony + the model
#   whatsapp          — messaging fee + the model, no telephony
#   web-test          — the owner trying their own agent: model + speech only
#   terminal/voice/live — our own development channels
CHANNEL_LINES = {
    "phone": ("telephony_in", "model"),
    "inbound": ("telephony_in", "model"),
    "callback": ("telephony_out", "model"),
    "outbound": ("telephony_out", "model"),
    "whatsapp": ("messaging", "model"),
    "web-test": ("model", "tts"),
    "voice": ("model", "tts"),
    "live": ("model",),
    "terminal": ("model",),
}
BILLABLE_CHANNELS = ("phone", "inbound", "callback", "outbound", "whatsapp")


def _rate(name: str) -> tuple[float, bool]:
    """(value, assumed) — assumed is True when .env didn't set it."""
    raw = os.getenv("COST_" + name.upper(), "").strip()
    if raw:
        try:
            return float(raw), False
        except ValueError:
            pass
    return DEFAULT_RATES[name], True


def rate_card() -> dict:
    card = {name: _rate(name)[0] for name in DEFAULT_RATES}
    card["currency"] = os.getenv("COST_CURRENCY", "INR")
    card["assumed"] = [name for name in DEFAULT_RATES if _rate(name)[1]]
    return card


def agent_chars(record: dict) -> int:
    """Characters the agent spoke — what a cascaded TTS bills for.

    Approximated from the transcript's "Agent:" lines. Exact enough to size a
    cost line; replace it with the provider's reported characters if we ever
    need the invoice to reconcile to the rupee.
    """
    total = 0
    for line in (record.get("transcript") or "").splitlines():
        stripped = line.strip()
        for prefix in ("Agent:", "Atithi:"):
            if stripped.startswith(prefix):
                total += len(stripped[len(prefix):].strip())
                break
    return total


def cost_for(record: dict) -> dict:
    """The cost of one call record: total, per-line breakdown, and honesty flag."""
    card = rate_card()
    seconds = max(int(record.get("seconds") or 0), 0)
    minutes = seconds / 60
    lines = CHANNEL_LINES.get(record.get("channel", ""), ("model",))

    breakdown: dict[str, float] = {}
    if "telephony_in" in lines:
        breakdown["telephony"] = round(minutes * card["telephony_in_per_min"], 4)
    if "telephony_out" in lines:
        breakdown["telephony"] = round(minutes * card["telephony_out_per_min"], 4)
    if "messaging" in lines:
        breakdown["messaging"] = round(card["messaging_per_conversation"], 4)
    if "model" in lines:
        breakdown["model"] = round(minutes * card["model_per_min"], 4)
    if "stt" in lines or card["stt_per_min"]:
        breakdown["stt"] = round(minutes * card["stt_per_min"], 4)
    if "tts" in lines:
        breakdown["tts"] = round(agent_chars(record) / 1000 * card["tts_per_1k_chars"], 4)

    total = round(sum(breakdown.values()), 4)
    return {
        "total": total,
        "currency": card["currency"],
        "per_minute": round(total / minutes, 4) if minutes else 0.0,
        "breakdown": breakdown,
        # True while any rate is still a placeholder. Do not price off these.
        "assumed": bool(card["assumed"]),
        "billable": record.get("channel") in BILLABLE_CHANNELS,
    }


def summarise(records: list[dict]) -> dict:
    """Totals across many calls, split into billable and internal."""
    out = {
        "calls": 0, "minutes": 0.0, "cost": 0.0,
        "billable_calls": 0, "billable_minutes": 0.0, "billable_cost": 0.0,
        "assumed": False, "currency": rate_card()["currency"],
        "by_channel": {},
    }
    for record in records:
        cost = record.get("cost") or cost_for(record)
        minutes = (record.get("seconds") or 0) / 60
        out["calls"] += 1
        out["minutes"] += minutes
        out["cost"] += cost["total"]
        out["assumed"] = out["assumed"] or cost.get("assumed", False)
        channel = record.get("channel", "?")
        bucket = out["by_channel"].setdefault(channel, {"calls": 0, "minutes": 0.0, "cost": 0.0})
        bucket["calls"] += 1
        bucket["minutes"] += minutes
        bucket["cost"] += cost["total"]
        if cost.get("billable"):
            out["billable_calls"] += 1
            out["billable_minutes"] += minutes
            out["billable_cost"] += cost["total"]
    for key in ("minutes", "cost", "billable_minutes", "billable_cost"):
        out[key] = round(out[key], 3)
    out["cost_per_minute"] = (round(out["billable_cost"] / out["billable_minutes"], 3)
                              if out["billable_minutes"] else 0.0)
    return out


# ---- the report ------------------------------------------------------------------

def _report():
    import billing
    import storage

    card = rate_card()
    print(f"\n=== What Atithi costs to run  ({dt.date.today()}) ===\n")
    if card["assumed"]:
        print("  !! UNMEASURED RATES — these are placeholders, not invoice figures:")
        print(f"     {', '.join(card['assumed'])}")
        print("     Fill them in .env (see docs/STRATEGY.md §5) before pricing anything.\n")

    grand = {"cost": 0.0, "minutes": 0.0, "revenue": 0.0}
    for entry in storage.all_clients():
        client_id = entry["client_id"]
        records = storage.read_call_logs(client_id)
        if not records:
            continue
        summary = summarise(records)
        status = billing.status(client_id)
        # What this business pays us this month, as configured today.
        revenue = 0.0 if status.get("plan") in (None, "free", "trial") else \
            float(os.getenv("BILLING_PRICE_INR", "1999"))

        print(f"  {entry['config'].get('business_name', client_id)}  [{client_id}]")
        print(f"    plan            : {status.get('plan')}  "
              f"(revenue counted: {card['currency']} {revenue:,.0f})")
        print(f"    calls           : {summary['calls']} "
              f"({summary['billable_calls']} billable)")
        print(f"    minutes         : {summary['minutes']:.1f} "
              f"({summary['billable_minutes']:.1f} billable)")
        print(f"    cost to serve   : {card['currency']} {summary['cost']:.2f}")
        if summary["billable_minutes"]:
            print(f"    cost per minute : {card['currency']} {summary['cost_per_minute']:.2f}")
        for channel, bucket in sorted(summary["by_channel"].items()):
            print(f"        {channel:<10} {bucket['calls']:>4} calls  "
                  f"{bucket['minutes']:>7.1f} min  "
                  f"{card['currency']} {bucket['cost']:>8.2f}")
        if revenue:
            margin = revenue - summary["cost"]
            pct = (margin / revenue * 100) if revenue else 0
            flag = "  <-- LOSS" if margin < 0 else ""
            print(f"    margin          : {card['currency']} {margin:,.2f} "
                  f"({pct:.0f}%){flag}")
        print()
        grand["cost"] += summary["cost"]
        grand["minutes"] += summary["minutes"]
        grand["revenue"] += revenue

    print(f"  TOTAL  {grand['minutes']:.1f} min   "
          f"cost {card['currency']} {grand['cost']:.2f}   "
          f"revenue {card['currency']} {grand['revenue']:,.0f}")
    if grand["cost"]:
        breakeven = grand["cost"] * 3            # the 3x rule from STRATEGY §5
        print(f"  At the 3x rule, that volume should sell for at least "
              f"{card['currency']} {breakeven:,.0f}.")
    print()


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    sys.exit(_report())
