"""agent.py — the channel-independent agent core.

WHY (architecture principle 3): this class knows nothing about terminals,
microphones, browsers, or phone lines. It takes a text message in and returns a
text reply. Four channels already wrap it (terminal, push-to-talk, live call,
web portal) and none of them required changing this file.

WHY tools instead of prompt text (principle 4): slot availability changes in
real time. If we pasted slots into the system prompt, the model would happily
quote stale data. A tool call is executed at the moment of asking, so the
answer is always current. Static facts (prices, address, FAQ) don't change
mid-conversation, so they live in the prompt.

Tool design rule learned the hard way: tools VALIDATE their inputs and return
errors instead of trusting the model. book_appointment refuses times that
aren't actually free and phone numbers that are too short — the model reads
the error and corrects itself. Self-healing beats hoping.
"""

import datetime as dt
import re
import secrets
import sys
import threading
import time
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import perf
import scheduling
import storage
from llm import GeminiLLM

# Windows consoles often use the cp1252 codepage, which can't print emoji or ₹.
# Without this, the booking-confirmation print() would CRASH the whole tool-use
# loop mid-booking (found the hard way). "replace" swaps unprintable characters
# for '?' instead of raising.
if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

BASE_DIR = Path(__file__).resolve().parent

# Tool schemas in plain JSON schema — provider-neutral (llm.py converts them).
TOOL_SCHEMAS = [
    {
        "name": "check_availability",
        "description": (
            "Get ALL free appointment slots for a given date. Always call this "
            "before telling the customer a slot is available or unavailable. "
            "Pick the slots nearest the customer's preferred time yourself."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "The date to check, format YYYY-MM-DD.",
                },
            },
            "required": ["date"],
        },
    },
    {
        "name": "book_appointment",
        "description": (
            "Book a confirmed appointment. Call this ONLY after the customer has "
            "confirmed their name, phone, service, date and time. The time must "
            "be one returned by check_availability."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "customer_name": {"type": "string", "description": "Customer's full name."},
                "phone": {"type": "string", "description": "Customer's phone number (10+ digits)."},
                "service": {"type": "string", "description": "The service being booked."},
                "date": {"type": "string", "description": "Appointment date, YYYY-MM-DD."},
                "time": {"type": "string", "description": "Appointment time, 24-hour HH:MM."},
            },
            "required": ["customer_name", "phone", "service", "date", "time"],
        },
    },
    {
        "name": "save_lead",
        "description": (
            "Save the caller's contact details as a follow-up lead when they show "
            "interest but do NOT complete a booking — they want to think about it, "
            "ask for a callback, or the conversation is ending without a booking. "
            "Only use details the customer actually gave; never invent them."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Customer's name, if given."},
                "phone": {"type": "string", "description": "Customer's phone number (10+ digits)."},
                "interest": {"type": "string", "description": "What they asked about or wanted."},
                "note": {"type": "string", "description": "Anything useful for the follow-up call."},
            },
            "required": ["phone", "interest"],
        },
    },
]
_TOOL_NAMES = frozenset(t["name"] for t in TOOL_SCHEMAS)


# Every timestamp in a conversation record carries a UTC offset, so "tomorrow
# at 4" can later be checked against the right calendar day. Indian businesses
# by default; a client YAML may set `timezone:` (an IANA name).
DEFAULT_TIMEZONE = "Asia/Kolkata"
# India has no daylight saving, so a fixed offset is exact. Used when the
# operating system has no timezone database (Windows without `tzdata`).
_IST = dt.timezone(dt.timedelta(hours=5, minutes=30), "IST")


def _business_timezone(config: dict) -> tuple[dt.tzinfo, str]:
    """(timezone, its IANA name). The name is what records store, so it stays
    "Asia/Kolkata" even when the fixed-offset fallback is used."""
    name = config.get("timezone") or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(name), name
    except (ZoneInfoNotFoundError, ValueError):
        if name != DEFAULT_TIMEZONE:
            # A typo in one client's YAML must not stop its calls.
            print(f"  (unknown timezone {name!r} in client config; using {DEFAULT_TIMEZONE})")
    try:
        return ZoneInfo(DEFAULT_TIMEZONE), DEFAULT_TIMEZONE
    except (ZoneInfoNotFoundError, ValueError):
        return _IST, DEFAULT_TIMEZONE


def _phone_ok(phone: str) -> bool:
    """A usable Indian phone number has at least 10 digits (12 with +91)."""
    return len(re.sub(r"\D", "", phone or "")) >= 10


# The prompt template and each client's rendered prompt are the same on every
# call of the day — read and render them once, not once per conversation.
_template_cache: list = []
_prompt_cache: dict = {}
_prompt_lock = threading.Lock()
_shared_llm = None
_llm_lock = threading.Lock()


def _prompt_template() -> str:
    path = BASE_DIR / "prompts" / "receptionist.txt"
    stamp = path.stat().st_mtime_ns
    if not _template_cache or _template_cache[0] != stamp:
        _template_cache[:] = [stamp, path.read_text(encoding="utf-8")]
    return _template_cache[1]


def default_llm() -> GeminiLLM:
    """One LLM wrapper for the whole process.

    Building one costs ~780 ms (the Gemini client underneath). Creating it per
    conversation meant every phone call opened with nearly a second of silence.
    GeminiLLM holds no conversation state, so a single instance is safe to
    share across calls and threads.
    """
    global _shared_llm
    if _shared_llm is None:
        with _llm_lock:
            if _shared_llm is None:
                _shared_llm = GeminiLLM()
    return _shared_llm


class ReceptionistAgent:
    """One instance = one conversation with one business's receptionist."""

    def __init__(self, client_id: str, llm=None):
        self.client_id = client_id
        self.config = self._load_config(client_id)
        self.tz, self.tz_name = _business_timezone(self.config)
        # What's free right now. Refreshed from the bookings database on every
        # availability check and booking (see _refresh_slots), so a slot that
        # another conversation booked a minute ago is never offered here.
        self.slots = self._refresh_slots()
        self.system_prompt = self._render_system_prompt()
        self.llm = llm or default_llm()
        self.history: list[dict] = []
        # A random id that ties this conversation's perf measurements
        # together. Deliberately NOT the phone number or the Twilio SID.
        self.perf_id = secrets.token_hex(6)

    # ---- setup ---------------------------------------------------------------

    def _load_config(self, client_id: str) -> dict:
        """The shared, cached parse of the client YAML — treat as read-only."""
        config = storage.read_client_config(client_id)
        if config is None:
            raise FileNotFoundError(
                f"No client config found at {BASE_DIR / 'clients' / (client_id + '.yaml')}"
            )
        return config

    def _render_system_prompt(self) -> str:
        cfg = self.config
        today = dt.date.today()
        # id(cfg) changes whenever the YAML is re-parsed, so it doubles as a
        # version marker: edit the file and the prompt re-renders.
        key = (self.client_id, id(cfg), today)
        with _prompt_lock:
            hit = _prompt_cache.get(key)
        if hit is not None:
            return hit

        services = "\n".join(f"- {s['name']}: {s['price']}" for s in cfg.get("services", []))
        faq = "\n".join(f"Q: {f['q']}\nA: {f['a']}" for f in cfg.get("faq", [])) or "(none provided)"
        policies = "\n".join(f"- {p}" for p in cfg.get("policies", [])) or "(none provided)"
        prompt = _prompt_template().format(
            business_name=cfg["business_name"],
            address=cfg.get("address", ""),
            timings=cfg.get("timings", ""),
            services_and_prices=services,
            faq=faq,
            policies=policies,
            fallback_instruction=cfg.get("fallback", ""),
            today=today.strftime("%A, %Y-%m-%d"),
        )
        with _prompt_lock:
            if len(_prompt_cache) > 512:
                _prompt_cache.clear()
            _prompt_cache[key] = prompt
        return prompt

    def now(self) -> str:
        """The current time in the business's timezone, with its UTC offset."""
        return dt.datetime.now(self.tz).isoformat(timespec="seconds")

    # ---- the conversation loop -------------------------------------------------

    def chat(self, user_message: str) -> str:
        """One customer turn in, one receptionist reply out.

        The tool-use loop: the model may answer with tool calls instead of text.
        We execute them, append the results to history, and ask the model again.
        It repeats until the model produces a plain text reply (max 5 rounds so a
        confused model can never loop forever).
        """
        self.history.append({"role": "user", "text": user_message, "at": self.now()})
        messages = [{"role": "system", "text": self.system_prompt}]
        t0, rounds, outcome = time.perf_counter(), 0, "error"
        try:
            for _ in range(5):
                rounds += 1
                # Each model round trip is timed: a turn that needs three
                # trips is three waits the customer sits through.
                with perf.span("model.request", call=self.perf_id, round=rounds):
                    response = self.llm.send(messages + self.history, TOOL_SCHEMAS)

                if response["tool_calls"]:
                    self.history.append(self.tool_call_entry(response["tool_calls"], response["text"]))
                    for call in response["tool_calls"]:
                        self.history.append(self.run_tool(call))
                    continue  # feed tool results back, get the model's next move

                text = response["text"] or "Sorry, could you repeat that?"
                self.history.append({"role": "assistant", "text": text, "at": self.now()})
                outcome = "reply"
                return text

            # Safety net: 5 rounds of tools without a text reply.
            text = "Sorry, I'm having trouble right now — the front desk will call you back."
            self.history.append({"role": "assistant", "text": text, "at": self.now()})
            outcome = "round_limit"
            return text
        finally:
            perf.record("turn", (time.perf_counter() - t0) * 1000, outcome != "error",
                        self.perf_id, rounds=rounds, outcome=outcome)

    def reset(self):
        """Forget the conversation (the /reset command)."""
        self.history = []

    # ---- tools -----------------------------------------------------------------

    def tool_call_entry(self, calls: list[dict], text: str | None = None) -> dict:
        """The history entry for "the agent asked for these tools"."""
        return {"role": "assistant", "text": text, "tool_calls": calls, "at": self.now()}

    def run_tool(self, call: dict) -> dict:
        """Run one tool call and return its history entry.

        Every channel (text chat, phone, live mic) runs tools through here, so
        error handling and timestamps are identical everywhere. A tool bug
        must never kill the conversation: the failure is reported to the
        model, which apologises and offers a front-desk callback.
        """
        t0 = time.perf_counter()
        try:
            result = self._execute_tool(call["name"], call["args"])
        except Exception as e:
            result = {"error": f"{type(e).__name__}: {e}"}
        # The tool name comes from the model, so only known names become a
        # label; the outcome is the tool's own status, never its arguments.
        raised = storage.tool_raised(result)
        status = result.get("status") or ("error" if raised else "ok")
        perf.record("tool", (time.perf_counter() - t0) * 1000, not raised, self.perf_id,
                    tool=call["name"] if call["name"] in _TOOL_NAMES else "unknown",
                    status=status)
        return {"role": "tool", "name": call["name"], "result": result, "at": self.now()}

    def _execute_tool(self, name: str, args: dict) -> dict:
        if name == "check_availability":
            return self._check_availability(args.get("date", ""))
        if name == "book_appointment":
            return self._book_appointment(
                args.get("customer_name", ""),
                args.get("phone", ""),
                args.get("service", ""),
                args.get("date", ""),
                args.get("time", ""),
            )
        if name == "save_lead":
            return self._save_lead(
                args.get("name", ""),
                args.get("phone", ""),
                args.get("interest", ""),
                args.get("note", ""),
            )
        return {"error": f"Unknown tool: {name}"}

    def _refresh_slots(self) -> dict:
        """Opening hours minus every confirmed booking in the database.

        WHY not a snapshot taken when the conversation started (as before):
        two calls running at once each held their own snapshot, so both could
        offer — and book — the same slot (audit H2). One indexed query per
        tool call is cheap; a double-booked patient in the waiting room is not.
        """
        self.slots = scheduling.available_slots(
            self.config, storage.booked_pairs(self.client_id)
        )
        return self.slots

    def _check_availability(self, date: str) -> dict:
        """What's actually free on a date, computed from the business's hours.

        Returns ALL free slots for the date, unfiltered. We used to filter by a
        'morning/afternoon/evening' window — until an eval caught the agent
        telling a customer 4 PM was unavailable because the model called it
        "evening" and our evening started at 5 PM. A tool that hides
        information can mislead the model; one that returns everything cannot.

        Later stages replace this body with a real calendar lookup — the tool's
        name and schema stay the same, so the agent doesn't change at all.
        """
        slots = self._refresh_slots().get(date)
        if slots is None:
            horizon = sorted(self.slots)
            return {
                "date": date,
                "available_slots": [],
                "note": (
                    f"No slot information for {date}. Bookings are open from "
                    f"{horizon[0]} to {horizon[-1]}. Offer a date in that range, "
                    "or have the front desk call the customer back."
                    if horizon else
                    "No slot information for this date. Offer to have the front "
                    "desk call the customer back."
                ),
            }
        return {"date": date, "available_slots": slots}

    def _book_appointment(self, customer_name, phone, service, date, time) -> dict:
        # Validate BEFORE writing anything. The error messages are written for
        # the model: it reads them and fixes its own mistake in the next turn.
        available = self._refresh_slots().get(date) or []
        if time not in available:
            return {
                "status": "failed",
                "error": (
                    f"{time} on {date} is not an available slot. Offer the "
                    "customer one of the available slots instead."
                ),
                "available_slots": available,
            }
        if not _phone_ok(phone):
            return {
                "status": "failed",
                "error": "The phone number looks incomplete. Ask the customer "
                         "to confirm a 10-digit mobile number before booking.",
            }

        row = [
            dt.datetime.now().isoformat(timespec="seconds"),
            self.client_id, customer_name, phone, service, date, time, "confirmed",
        ]
        saved_to = storage.reserve_booking(row)
        if saved_to is None:
            # Another conversation booked this exact slot between our check
            # and our write. The database refused the second booking; tell
            # the model so it offers the customer what is still free.
            return {
                "status": "failed",
                "error": (
                    f"{time} on {date} was just booked by someone else. "
                    "Apologise and offer the customer one of the available slots."
                ),
                "available_slots": self._refresh_slots().get(date) or [],
            }
        self.slots[date].remove(time)   # keep this view current without a re-query
        print(
            f"\n  ✅ BOOKING CONFIRMED — {customer_name} | {phone} | {service} "
            f"| {date} {time}\n     saved to: {saved_to}\n"
        )
        return {
            "status": "confirmed",
            "customer_name": customer_name,
            "phone": phone,
            "service": service,
            "date": date,
            "time": time,
            "saved_to": saved_to,
        }

    def _save_lead(self, name, phone, interest, note) -> dict:
        if not _phone_ok(phone):
            return {
                "status": "failed",
                "error": "The phone number looks incomplete. Ask the customer "
                         "for a 10-digit mobile number so the front desk can call back.",
            }
        storage.save_lead(self.client_id, name, phone, interest, note)
        print(f"\n  📇 LEAD SAVED — {name or '(no name)'} | {phone} | {interest}\n")
        return {"status": "saved", "name": name, "phone": phone, "interest": interest}

    # ---- transcript ---------------------------------------------------------------

    def transcript_text(self) -> str:
        """Human-readable transcript, including tool activity (the dashboard's
        call history renders this)."""
        lines = []
        for msg in self.history:
            if msg["role"] == "user":
                lines.append(f"Customer: {msg['text']}")
            elif msg["role"] == "assistant":
                if msg.get("tool_calls"):
                    for call in msg["tool_calls"]:
                        lines.append(f"  [tool call] {call['name']}({call['args']})")
                if msg.get("text"):
                    lines.append(f"Agent: {msg['text']}")
            elif msg["role"] == "tool":
                lines.append(f"  [tool result] {msg['result']}")
            lines.append("")
        return "\n".join(lines)


class TurnRecorder:
    """Writes a streaming call (phone, live mic) into agent.history in the
    order things actually happened.

    WHY: on a streaming call the speech arrives as text fragments that are
    only complete when the turn ends, but tools run in the MIDDLE of the turn.
    Appending tool entries the moment they run would put "booked 10:30"
    before the caller's "can I come at 10:30?". So the turn is buffered and
    written at once, keeping what the agent said BEFORE a tool separate from
    what it said after (a "you're booked!" spoken before the booking ran is
    exactly the premature claim the checker must be able to see):

        user_text ...   agent_text ...   tool_calls(+results)   agent_text ...
             |               |                    |                    |
             v               v                    v                    v
        [ user ] -> [ assistant: before ] -> [ tool_calls, results ] -> [ assistant: after ]

    flush() runs at turn_complete, when the caller barges in (interrupted),
    and at hang-up. History ORDER is authoritative; an entry's "at" is when
    its text started arriving, and speech transcription can lag behind a
    tool call, so "at" values are not guaranteed to increase.
    """

    def __init__(self, agent: ReceptionistAgent):
        self.agent = agent
        # Tools run on a worker thread (telephony, live_main). If the caller
        # hangs up while one is still running, flush() can run on another
        # thread at the same moment; the lock keeps every tool entry whole
        # and in order, so a late result lands in the NEXT flush, not nowhere.
        self._lock = threading.Lock()
        self._reset()

    def _reset(self):
        self._user, self._user_at = "", None
        self._user_last = None                     # perf_counter of the caller's last fragment
        self._before, self._before_at = "", None   # agent speech before the first tool
        self._after, self._after_at = "", None     # agent speech after it
        self._tools: list[dict] = []

    def user_text(self, text: str):
        if not self._user:
            self._user_at = self.agent.now()
        self._user += text
        self._user_last = time.perf_counter()

    def agent_text(self, text: str):
        if self._tools:
            if not self._after:
                self._after_at = self.agent.now()
            self._after += text
        else:
            if not self._before:
                self._before_at = self.agent.now()
            self._before += text

    def tool_calls(self, calls: list[dict]) -> list[dict]:
        """Run the tools now (the model is waiting); record them at flush()."""
        with self._lock:
            self._tools.append(self.agent.tool_call_entry(calls))
        results = []
        for call in calls:
            entry = self.agent.run_tool(call)
            with self._lock:
                self._tools.append(entry)
            results.append({"id": call.get("id"), "name": call["name"], "result": entry["result"]})
        return results

    def flush(self) -> tuple[str, str]:
        """Write the buffered turn to history; returns (caller said, agent said)."""
        with self._lock:
            return self._flush()

    def _flush(self) -> tuple[str, str]:
        history = self.agent.history
        user, before, after = self._user.strip(), self._before.strip(), self._after.strip()
        if user:
            history.append({"role": "user", "text": user, "at": self._user_at})
        if before:
            history.append({"role": "assistant", "text": before, "at": self._before_at})
        history.extend(self._tools)
        if after:
            history.append({"role": "assistant", "text": after, "at": self._after_at})
        if self._user_last is not None:
            # From the caller's last transcribed words to the turn being
            # written down. A turn is written when the agent's reply ends,
            # so this spans the whole response: think time + reply length.
            perf.record("turn.finalize", (time.perf_counter() - self._user_last) * 1000,
                        call=self.agent.perf_id)
        self._reset()
        return user, " ".join(t for t in (before, after) if t)
