"""Proof, not promises: does every "you're booked" have a booking behind it?

A receptionist that SAYS "you're booked for 4 PM" when nothing was saved is
the worst failure Atithi can have: the customer turns up, the business has
no record, and the business looks careless. This file catches it.

It reads only agent.history (what was said and what the tools returned), so
it is pure: no disk, no clock, no provider. Two users:

1. agent.chat() asks `unbacked(text, history)` before a text reply goes out.
   If the reply claims something no tool did, the model gets one nudge to
   fix it (do the action, or stop claiming it); if it still can't back the
   claim, the customer gets an honest fallback instead.
2. storage writes `report(history, caught)` into every call record, so the
   owner sees "3 promises, 3 backed by a record" on each call. Phone calls
   are spoken as they are generated, so for them the report is all we can do.

WHY phrase rules and not a second model: a model checking a model costs a
round trip the customer waits through, and can be wrong in the same way.
These rules are boring, free and testable. They are English-only (a known
limit, like the planned voxcheck checks this mirrors: docs/designs/
claim-vs-records-checker.md, check 4 "claim without action" and check 5
"spoken time differs"). A sentence in another language is simply not checked.
"""

import re

# ---- claims ------------------------------------------------------------------

_THING = r"(?:booking|appointment|reservation|table|session|slot|class|visit|seat)"
_CLAIMS = {
    "booked": [
        rf"\b(?:you'?re|you are|you have been|you've been)\s+(?:all\s+)?(?:booked|confirmed|scheduled|set for)\b",
        r"\b(?:i'?ve|i have|we'?ve|we have)\s+(?:now\s+)?(?:booked|confirmed|scheduled|reserved)\b",
        rf"\b{_THING}\s+(?:is|has been)\s+(?:now\s+)?(?:confirmed|booked|reserved|scheduled|done)\b",
        r"\b(?:booked|confirmed|reserved) (?:you|it|that) (?:in|for)\b",
    ],
    "cancelled": [
        r"\b(?:i'?ve|i have|we'?ve|we have)\s+(?:now\s+)?cancell?ed\b",
        rf"\b{_THING}\s+(?:is|has been)\s+(?:now\s+)?cancell?ed\b",
        r"\b(?:it'?s|that'?s|it has|that has)\s+(?:been\s+)?cancell?ed\b",
    ],
    "rescheduled": [
        r"\b(?:i'?ve|i have|we'?ve|we have)\s+(?:now\s+)?(?:moved|rescheduled|changed)\b",
        rf"\b{_THING}\s+(?:is|has been)\s+(?:now\s+)?(?:moved|rescheduled|changed)\b",
        r"\b(?:it'?s|that'?s|it has|that has)\s+(?:been\s+)?(?:moved|rescheduled)\b",
    ],
    # A callback promise with no phone number saved is a call nobody makes.
    "callback": [
        r"\b(?:will|'ll)\s+(?:call|ring|phone|get back to|contact)\s+you\b",
    ],
}
_CLAIMS = {k: [re.compile(p, re.I) for p in v] for k, v in _CLAIMS.items()}

# A sentence that hedges, asks or talks about the future is not a claim.
_NOT_A_CLAIM = re.compile(
    r"\b(?:not|never|unable|cannot|can'?t|couldn'?t|won'?t|wasn'?t|isn'?t|haven'?t|hasn'?t|"
    r"didn'?t|if|once|would|shall|going to|about to|let me|want me|should i|fully booked)\b|n't\b",
    re.I)
_FUTURE_OK = {"callback"}       # "will call you" IS the claim; don't drop it for "will"


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]


def claims(text: str) -> list[dict]:
    """[{"kind", "said"}] for each sentence that states something was done."""
    found = []
    for s in _sentences(text):
        if s.endswith("?"):
            continue
        for kind, patterns in _CLAIMS.items():
            if not any(p.search(s) for p in patterns):
                continue
            if _NOT_A_CLAIM.search(s) and not (kind in _FUTURE_OK and not re.search(
                    r"\b(?:not|never|won'?t|can'?t|cannot|if)\b|n't\b", s, re.I)):
                continue
            found.append({"kind": kind, "said": s})
    return found


# ---- times ("4 PM", "10:30", "16:30") -------------------------------------------

_TIME = re.compile(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?(?![\d])", re.I)


def spoken_times(sentence: str) -> set[str]:
    """Times in a sentence as HH:MM. "10:30" with no AM/PM could be either
    half of the day, so both readings are returned. A bare "10" is not a
    time (it is usually a count)."""
    out = set()
    for h, m, ampm in _TIME.findall(sentence):
        if not m and not ampm:
            continue
        h, m = int(h), int(m or 0)
        if h > 23 or m > 59:
            continue
        if ampm:
            if h > 12:
                continue
            pm = ampm.lower().startswith("p")
            h = (h % 12) + (12 if pm else 0)
            out.add(f"{h:02d}:{m:02d}")
        else:
            out.add(f"{h:02d}:{m:02d}")
            if h < 12:
                out.add(f"{h + 12:02d}:{m:02d}")
    return out


# ---- evidence ------------------------------------------------------------------

def evidence(tool_entries: list[dict]) -> dict[str, set[str]]:
    """What the tools actually did: {kind: {times}}. A booking found by
    find_booking is evidence too ("yes, your appointment is confirmed")."""
    ev: dict[str, set[str]] = {}

    def add(kind, *times):
        ev.setdefault(kind, set()).update(t for t in times if t)

    for m in tool_entries:
        if m.get("role") != "tool":
            continue
        r, name = m.get("result") or {}, m.get("name")
        status = r.get("status")
        if name == "book_appointment" and status == "confirmed":
            add("booked", r.get("time"))
        elif name == "find_booking" and status == "found":
            add("booked", *(b.get("time") for b in r.get("bookings") or []))
        elif name == "cancel_booking" and status == "cancelled":
            add("cancelled", r.get("time"))
        elif name == "reschedule_booking" and status == "rescheduled":
            to, frm = (r.get("to") or {}).get("time"), (r.get("from") or {}).get("time")
            add("rescheduled", to, frm)
            add("booked", to)                   # "you're now booked for 4 PM"
        elif name in ("save_lead",) and status == "saved":
            add("callback")
    if "booked" in ev or "rescheduled" in ev:
        add("callback")                         # a booking carries a phone number
    return ev


def _problem(claim: dict, ev: dict[str, set[str]]) -> str | None:
    kind = claim["kind"]
    if kind not in ev:
        return "no_action"
    said = spoken_times(claim["said"])
    if said and ev[kind] and not (said & ev[kind]):
        return "wrong_time"
    return None


def unbacked(text: str, history: list[dict]) -> list[dict]:
    """Claims in a reply that no tool result in the conversation backs.

    Used live, before the reply is sent; callback promises are left to the
    end-of-call report because the number is often asked for right after
    ("the team will call you back. What's your number?")."""
    ev = evidence(history)
    out = []
    for c in claims(text):
        if c["kind"] == "callback":
            continue
        problem = _problem(c, ev)
        if problem:
            out.append({**c, "problem": problem})
    return out


def nudge(problems: list[dict]) -> str:
    """The one correction the model gets. Written for the model, not the customer."""
    lines = []
    for p in problems:
        if p["problem"] == "wrong_time":
            lines.append(f'You said "{p["said"]}", but the time does not match what the tool returned.')
        else:
            lines.append(f'You said "{p["said"]}", but no tool has done that in this conversation.')
    return ("[Record check, not from the customer] " + " ".join(lines) +
            " Never tell the customer something is done unless a tool result says so. "
            "Call the right tool now, or reply again without claiming it.")


SAFE_REPLY = ("Sorry, I haven't been able to complete that yet. Could you tell me the date, "
              "the time and your phone number once more so I can try again?")


def report(history: list[dict], caught: list[dict] | None = None) -> dict:
    """The call's honesty report, written into the call record.

    A claim is backed by any tool result before the NEXT caller turn: on a
    phone call the agent can say "booking that now" and the tool result
    lands a moment later in the same turn. Callback promises are backed by
    a lead or booking anywhere in the call.
    """
    caught = caught or []
    whole = evidence(history)
    checked, problems = 0, []
    for i, m in enumerate(history):
        if m.get("role") != "assistant" or not m.get("text"):
            continue
        end = next((j for j in range(i + 1, len(history)) if history[j].get("role") == "user"),
                   len(history))
        ev = evidence(history[:end])
        for c in claims(m["text"]):
            checked += 1
            problem = _problem(c, whole if c["kind"] == "callback" else ev)
            if problem:
                problems.append({"kind": c["kind"], "said": c["said"][:200], "problem": problem})
    return {
        "claims": checked,
        "backed": checked - len(problems),
        "unbacked": problems,
        "caught": [{k: e[k] for k in ("kind", "said", "problem", "fixed") if k in e} for e in caught],
        "verdict": "flagged" if problems else ("verified" if checked or caught else "none"),
    }
