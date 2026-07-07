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
import sys
from pathlib import Path

import yaml

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


def _phone_ok(phone: str) -> bool:
    """A usable Indian phone number has at least 10 digits (12 with +91)."""
    return len(re.sub(r"\D", "", phone or "")) >= 10


class ReceptionistAgent:
    """One instance = one conversation with one business's receptionist."""

    def __init__(self, client_id: str, llm=None):
        self.client_id = client_id
        self.config = self._load_config(client_id)
        self._apply_existing_bookings()
        self.system_prompt = self._render_system_prompt()
        self.llm = llm or GeminiLLM()
        self.history: list[dict] = []

    # ---- setup ---------------------------------------------------------------

    def _load_config(self, client_id: str) -> dict:
        path = BASE_DIR / "clients" / f"{client_id}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"No client config found at {path}")
        with open(path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        # Defensive: if someone forgets to quote dates in YAML, keys arrive as
        # datetime.date objects. Normalize slot keys to plain "YYYY-MM-DD" strings.
        config["slots"] = {str(k): v for k, v in config.get("slots", {}).items()}
        return config

    def _apply_existing_bookings(self):
        """Remove already-booked slots so they are never offered twice.

        Reads past bookings from local storage (Sheet-only bookings aren't
        replayed yet — a real calendar backend replaces this mechanism later).
        """
        for row in storage.read_bookings(self.client_id):
            if row.get("status") != "confirmed":
                continue
            day = self.config["slots"].get(row.get("date", ""))
            if day and row.get("time") in day:
                day.remove(row["time"])

    def _render_system_prompt(self) -> str:
        template = (BASE_DIR / "prompts" / "receptionist.txt").read_text(encoding="utf-8")
        cfg = self.config
        services = "\n".join(f"- {s['name']}: {s['price']}" for s in cfg["services"])
        faq = "\n".join(f"Q: {f['q']}\nA: {f['a']}" for f in cfg["faq"]) or "(none provided)"
        policies = "\n".join(f"- {p}" for p in cfg["policies"]) or "(none provided)"
        today = dt.date.today()
        return template.format(
            business_name=cfg["business_name"],
            address=cfg["address"],
            timings=cfg["timings"],
            services_and_prices=services,
            faq=faq,
            policies=policies,
            fallback_instruction=cfg["fallback"],
            today=today.strftime("%A, %Y-%m-%d"),
        )

    # ---- the conversation loop -------------------------------------------------

    def chat(self, user_message: str) -> str:
        """One customer turn in, one receptionist reply out.

        The tool-use loop: the model may answer with tool calls instead of text.
        We execute them, append the results to history, and ask the model again.
        It repeats until the model produces a plain text reply (max 5 rounds so a
        confused model can never loop forever).
        """
        self.history.append({"role": "user", "text": user_message})
        messages = [{"role": "system", "text": self.system_prompt}]

        for _ in range(5):
            response = self.llm.send(messages + self.history, TOOL_SCHEMAS)

            if response["tool_calls"]:
                self.history.append(
                    {
                        "role": "assistant",
                        "text": response["text"],
                        "tool_calls": response["tool_calls"],
                    }
                )
                for call in response["tool_calls"]:
                    # A tool bug must never kill the conversation: report the
                    # failure to the model instead, so it can apologize and
                    # offer a front-desk callback.
                    try:
                        result = self._execute_tool(call["name"], call["args"])
                    except Exception as e:
                        result = {"error": f"{type(e).__name__}: {e}"}
                    self.history.append(
                        {"role": "tool", "name": call["name"], "result": result}
                    )
                continue  # feed tool results back, get the model's next move

            text = response["text"] or "Sorry, could you repeat that?"
            self.history.append({"role": "assistant", "text": text})
            return text

        # Safety net: 5 rounds of tools without a text reply.
        text = "Sorry, I'm having trouble right now — the front desk will call you back."
        self.history.append({"role": "assistant", "text": text})
        return text

    def reset(self):
        """Forget the conversation (the /reset command)."""
        self.history = []

    # ---- tools -----------------------------------------------------------------

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

    def _check_availability(self, date: str) -> dict:
        """Stage 1 mock: reads slots from the client YAML.

        Returns ALL free slots for the date, unfiltered. We used to filter by a
        'morning/afternoon/evening' window — until an eval caught the agent
        telling a customer 4 PM was unavailable because the model called it
        "evening" and our evening started at 5 PM. A tool that hides
        information can mislead the model; one that returns everything cannot.

        Later stages replace this body with a real calendar lookup — the tool's
        name and schema stay the same, so the agent doesn't change at all.
        """
        slots = self.config["slots"].get(date)
        if slots is None:
            return {
                "date": date,
                "available_slots": [],
                "note": (
                    "No slot information for this date. Offer to have the front "
                    "desk call the customer back."
                ),
            }
        return {"date": date, "available_slots": slots}

    def _book_appointment(self, customer_name, phone, service, date, time) -> dict:
        # Validate BEFORE writing anything. The error messages are written for
        # the model: it reads them and fixes its own mistake in the next turn.
        available = self.config["slots"].get(date) or []
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
        saved_to = storage.save_booking(row)
        # Consume the slot so the same time can't be double-booked.
        self.config["slots"][date].remove(time)
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
