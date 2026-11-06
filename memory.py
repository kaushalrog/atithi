"""memory.py — recognise a caller we have spoken to before.

WHY: a receptionist who has to ask "and your name?" to a patient who called
last week does not feel like a receptionist, it feels like a form. Competitors
sell this as "caller memory". On a phone call we already know the number from
caller ID, so the agent can open with the customer's name and already know
about their upcoming appointment.

What it does NOT do, deliberately:
  * It never replays the old conversation into the prompt. Only a short,
    factual summary goes in — a name, an upcoming appointment, roughly when
    they last called. Old transcripts in the prompt would cost tokens on every
    turn and let a stale remark leak into a new call.
  * It never invents a relationship. If the number does not match, the agent
    behaves exactly as it does today for a new caller.
  * It only ever looks inside ONE business. A customer known to the dental
    clinic is a stranger to the salon, which is what a customer expects.

Privacy: this reads the business's own bookings and call records for a number
that is already calling them. It adds no new storage. Whatever retention
policy covers call records covers this (TODOS.md, personal-data retention).
"""

import datetime as dt

import storage

#: Ignore anything older than this — "you called us last year" is not useful
#: and risks greeting someone about a visit they have forgotten.
LOOKBACK_DAYS = 120

#: How many past calls to count. We only need "new / returning / regular".
MAX_CALLS_COUNTED = 20


def _recent_calls(client_id: str, phone10: str) -> list[dict]:
    cutoff = (dt.datetime.now() - dt.timedelta(days=LOOKBACK_DAYS)).isoformat()
    found = []
    for record in storage.read_call_logs(client_id):
        caller = record.get("caller")
        if not caller or storage._phone10(caller) != phone10:
            continue
        if str(record.get("started", "")) < cutoff:
            continue
        found.append(record)
        if len(found) >= MAX_CALLS_COUNTED:
            break
    return found


def _known_name(client_id: str, phone: str) -> str:
    """The name this number booked under last, if any."""
    try:
        bookings = storage.find_bookings(client_id, phone)
    except Exception:
        return ""
    for booking in bookings:
        if booking.get("name"):
            return str(booking["name"]).strip()
    return ""


def recall(client_id: str, phone: str | None) -> dict:
    """What we already know about this caller. Empty dict if nothing useful.

    Never raises: a memory lookup must not be able to stop a call connecting.
    """
    if not phone:
        return {}
    try:
        phone10 = storage._phone10(phone)
        if not phone10:
            return {}
        calls = _recent_calls(client_id, phone10)
        name = _known_name(client_id, phone)
        upcoming = []
        try:
            today = dt.date.today().isoformat()
            upcoming = [b for b in storage.find_bookings(client_id, phone)
                        if str(b.get("date", "")) >= today]
        except Exception:
            upcoming = []

        if not calls and not name and not upcoming:
            return {}
        last_seen = max((str(c.get("started", "")) for c in calls), default="")
        return {
            "known": True,
            "name": name,
            "calls": len(calls),
            "last_seen": last_seen,
            "upcoming": [
                {k: b.get(k) for k in ("service", "date", "time")} for b in upcoming[:3]
            ],
        }
    except Exception as e:                       # memory is a nicety, never a blocker
        print(f"  [memory] recall failed for {client_id}: {e}")
        return {}


def _days_ago(stamp: str) -> int | None:
    try:
        return (dt.datetime.now() - dt.datetime.fromisoformat(stamp)).days
    except (ValueError, TypeError):
        return None


def briefing(known: dict) -> str:
    """One short paragraph for the system prompt. Empty when we know nothing.

    Written as facts plus an instruction, because a bare fact list invites the
    model to recite it ("I see you called 3 times") which sounds like
    surveillance rather than service.
    """
    if not known or not known.get("known"):
        return ""

    facts = []
    if known.get("name"):
        facts.append(f"their name is {known['name']}")
    days = _days_ago(known.get("last_seen", ""))
    if days is not None:
        when = "earlier today" if days == 0 else (
            "yesterday" if days == 1 else f"about {days} days ago")
        facts.append(f"they last called {when}")
    if known.get("calls", 0) >= 3:
        facts.append("they call regularly")
    for appointment in known.get("upcoming", []):
        service = appointment.get("service") or "an appointment"
        facts.append(f"they already have {service} booked on "
                     f"{appointment.get('date')} at {appointment.get('time')}")

    if not facts:
        return ""
    return (
        "\n\nRETURNING CALLER. From this business's own records: "
        + "; ".join(facts) + ". "
        "Greet them by name if you have it, warmly and briefly. Do NOT list "
        "what you know or mention how many times they have called — that "
        "sounds like surveillance. Do NOT assume why they are calling; ask. "
        "If they mention the appointment above, you already have its details. "
        "If anything they say contradicts these records, believe the caller "
        "and check with the tools."
    )


def brief_for(client_id: str, phone: str | None) -> str:
    """Convenience: recall + briefing in one call."""
    return briefing(recall(client_id, phone))
