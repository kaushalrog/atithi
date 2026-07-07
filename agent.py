"""agent.py — the channel-independent agent core.

WHY (architecture principle 3): this class knows nothing about terminals,
microphones, or phone lines. It takes a text message in and returns a text
reply. Stage 1 wraps it in a terminal loop (main.py); Stage 2/3 will wrap the
SAME class in a websocket audio pipeline. If the core stays channel-free, the
voice upgrade never touches this file's logic.

WHY tools instead of prompt text (principle 4): slot availability changes in
real time. If we pasted slots into the system prompt, the model would happily
quote stale data. A tool call is executed at the moment of asking, so the
answer is always current. Static facts (prices, address, FAQ) don't change
mid-conversation, so they live in the prompt.
"""

import csv
import datetime as dt
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

from llm import GeminiLLM

load_dotenv()

# Windows consoles often use the cp1252 codepage, which can't print emoji or ₹.
# Without this, the booking-confirmation print() would CRASH the whole tool-use
# loop mid-booking (found the hard way). "replace" swaps unprintable characters
# for '?' instead of raising.
if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

BASE_DIR = Path(__file__).resolve().parent

BOOKING_HEADER = [
    "timestamp", "client_id", "name", "phone", "service", "date", "time", "status",
]

# Tool schemas in plain JSON schema — provider-neutral (llm.py converts them).
TOOL_SCHEMAS = [
    {
        "name": "check_availability",
        "description": (
            "Check which appointment slots are free on a given date. Always call "
            "this before telling the customer a slot is available or unavailable."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "The date to check, format YYYY-MM-DD.",
                },
                "time_window": {
                    "type": "string",
                    "description": "Optional filter: 'morning', 'afternoon', 'evening', or 'any'.",
                },
            },
            "required": ["date"],
        },
    },
    {
        "name": "book_appointment",
        "description": (
            "Book a confirmed appointment. Call this ONLY after the customer has "
            "confirmed their name, phone, service, date and time."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "customer_name": {"type": "string", "description": "Customer's full name."},
                "phone": {"type": "string", "description": "Customer's phone number."},
                "service": {"type": "string", "description": "The service being booked."},
                "date": {"type": "string", "description": "Appointment date, YYYY-MM-DD."},
                "time": {"type": "string", "description": "Appointment time, 24-hour HH:MM."},
            },
            "required": ["customer_name", "phone", "service", "date", "time"],
        },
    },
]


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

        Stage 1 reads past bookings from bookings.csv only (bookings that went
        straight to Google Sheets aren't replayed yet — a real calendar backend
        replaces this whole mechanism in a later stage).
        """
        path = BASE_DIR / "bookings.csv"
        if not path.exists():
            return
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("client_id") == self.client_id and row.get("status") == "confirmed":
                    day = self.config["slots"].get(row.get("date", ""))
                    if day and row.get("time") in day:
                        day.remove(row["time"])

    def _render_system_prompt(self) -> str:
        template = (BASE_DIR / "prompts" / "receptionist.txt").read_text(encoding="utf-8")
        cfg = self.config
        services = "\n".join(f"- {s['name']}: {s['price']}" for s in cfg["services"])
        faq = "\n".join(f"Q: {f['q']}\nA: {f['a']}" for f in cfg["faq"])
        policies = "\n".join(f"- {p}" for p in cfg["policies"])
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
            return self._check_availability(
                args.get("date", ""), args.get("time_window", "any")
            )
        if name == "book_appointment":
            return self._book_appointment(
                args.get("customer_name", ""),
                args.get("phone", ""),
                args.get("service", ""),
                args.get("date", ""),
                args.get("time", ""),
            )
        return {"error": f"Unknown tool: {name}"}

    def _check_availability(self, date: str, time_window: str = "any") -> dict:
        """Stage 1 mock: reads slots from the client YAML.

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
        windows = {"morning": (0, 13), "afternoon": (13, 17), "evening": (17, 24)}
        if time_window in windows:
            low, high = windows[time_window]
            slots = [s for s in slots if low <= int(s.split(":")[0]) < high]
        return {"date": date, "time_window": time_window, "available_slots": slots}

    def _book_appointment(self, customer_name, phone, service, date, time) -> dict:
        row = [
            dt.datetime.now().isoformat(timespec="seconds"),
            self.client_id, customer_name, phone, service, date, time, "confirmed",
        ]
        saved_to = self._save_to_google_sheet(row)
        if saved_to is None:
            self._save_to_csv(row)
            saved_to = "bookings.csv (local fallback)"
        # Consume the slot so the same time can't be double-booked.
        day = self.config["slots"].get(date)
        if day and time in day:
            day.remove(time)
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

    def _save_to_google_sheet(self, row) -> str | None:
        """Returns 'Google Sheet' on success, None if we should fall back to CSV.

        WHY the fallback: a live demo must never die because of a missing
        credentials file or a flaky network. The booking is the product — losing
        it is the only unacceptable failure.
        """
        creds_path = os.getenv("GOOGLE_SHEETS_CREDENTIALS_PATH", "")
        sheet_id = os.getenv("SHEET_ID", "")
        if not creds_path or not sheet_id:
            print("  [warning] Google Sheets not configured (.env) — using bookings.csv.")
            return None
        if not Path(creds_path).is_absolute():
            creds_path = str(BASE_DIR / creds_path)
        if not os.path.exists(creds_path):
            print(f"  [warning] {creds_path} not found — using bookings.csv.")
            return None
        try:
            import gspread  # imported here so the demo runs even without gspread installed

            gc = gspread.service_account(filename=creds_path)
            worksheet = gc.open_by_key(sheet_id).sheet1
            if not worksheet.get_values("A1:H1"):
                worksheet.append_row(BOOKING_HEADER)
            worksheet.append_row(row)
            return "Google Sheet"
        except Exception as e:
            print(f"  [warning] Google Sheets failed ({e}) — using bookings.csv.")
            return None

    def _save_to_csv(self, row):
        path = BASE_DIR / "bookings.csv"
        is_new = not path.exists()
        with open(path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if is_new:
                writer.writerow(BOOKING_HEADER)
            writer.writerow(row)

    # ---- transcript ---------------------------------------------------------------

    def transcript_text(self) -> str:
        """Human-readable transcript, including tool activity (useful for debugging
        and, in Stage 5, for the dashboard)."""
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
