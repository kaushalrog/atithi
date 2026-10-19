"""notify.py — tell the customer what happened to their booking (SMS).

After a booking is confirmed, moved or cancelled, the customer gets a short
text from the business, and the day before, a reminder:

    Sri Balaji Dental Care: your Teeth cleaning is booked for Wed 21 Oct
    at 10:30 AM. To change it, call +91 98430 12345.

SAFETY, the same way as live calls: nothing is sent unless ENABLE_SMS=true
and Twilio is configured (telephony.sms_enabled). Otherwise each message is
written to notifications.jsonl as a "dry-run", so the owner can see exactly
what customers would receive before switching it on. A business can also
turn texts off for itself (`sms_confirmations: false` in its YAML).

WHY a background queue: sending goes over the network to Twilio. Like the
Google Sheet copy, it must never make a caller wait, and a failed SMS must
never touch the booking (that's already safe in bookings.db).

Reminders run as a command you schedule (cron / Task Scheduler), once a day:

    python notify.py reminders        # texts tomorrow's appointments, once each

India: commercial SMS to Indian numbers needs DLT registration (sender ID
and message templates) with your telecom operator before it is delivered.
"""

import datetime as dt
import re
import sys

import storage

QUEUE_MAX = 1000
KINDS = ("confirmed", "rescheduled", "cancelled", "reminder")


def to_e164(phone: str) -> str | None:
    """+91XXXXXXXXXX for an Indian 10-digit mobile; keep an explicit +country number."""
    raw = str(phone or "").strip()
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+") and len(digits) >= 11:
        return "+" + digits
    if len(digits) >= 10:
        return "+91" + digits[-10:]
    return None


def _when(date: str, time: str) -> str:
    try:
        d = dt.datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
    except ValueError:
        return f"{date} {time}"
    return d.strftime("%a %d %b at %I:%M %p").replace(" 0", " ")


def message(config: dict, kind: str, booking: dict) -> str:
    """The text for one booking event. Short: one SMS segment where possible."""
    biz = config.get("business_name", "Your clinic")
    what = booking.get("service") or "appointment"
    when = _when(booking.get("date", ""), booking.get("time", ""))
    call = config.get("phone", "").strip()
    change = f" To change it, call {call}." if call else ""
    if kind == "confirmed":
        return f"{biz}: your {what} is booked for {when}.{change}"
    if kind == "rescheduled":
        return f"{biz}: your {what} has been moved to {when}.{change}"
    if kind == "cancelled":
        return f"{biz}: your {what} on {when} has been cancelled." + (
            f" To book again, call {call}." if call else "")
    if kind == "reminder":
        return f"{biz}: reminder, your {what} is tomorrow, {when}.{change}"
    raise ValueError(f"unknown notification kind {kind!r}")


def _send(item: tuple[str, str, dict]):
    """The worker: send one message (or record the dry run), then log it."""
    client_id, kind, booking = item
    config = storage.read_client_config(client_id) or {}
    entry = {"at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
             "client_id": client_id, "kind": kind,
             "booking": {k: booking.get(k) for k in ("date", "time", "service")}}
    to = to_e164(booking.get("phone", ""))
    if config.get("sms_confirmations", True) is False:
        storage.log_notification(entry | {"status": "skipped", "reason": "turned off for this business"})
        return
    if to is None:
        storage.log_notification(entry | {"status": "skipped", "reason": "no valid phone number"})
        return
    text = message(config, kind, booking)
    entry |= {"to": to, "text": text}
    import telephony   # imported here: telephony imports agent, which imports this module
    if not telephony.sms_enabled():
        storage.log_notification(entry | {"status": "dry-run"})
        return
    try:
        sid = telephony.send_sms(to, text)
        storage.log_notification(entry | {"status": "sent", "sid": sid})
    except Exception as e:
        storage.log_notification(entry | {"status": "failed", "error": type(e).__name__})
        print(f"  [notify] SMS to customer of {client_id} failed ({type(e).__name__}); "
              "the booking itself is unaffected.")


_queue = storage.BackgroundQueue("notify", _send, maxsize=QUEUE_MAX)


def booking_event(client_id: str, kind: str, booking: dict):
    """Queue the customer's text for a booking event. Never blocks, never raises."""
    if kind not in KINDS:
        raise ValueError(f"unknown notification kind {kind!r}")
    if storage.in_test_mode() and not getattr(storage, "_ALLOW_NOTIFY_IN_TESTS", False):
        return      # tests opt in explicitly; evals never text anyone
    if not _queue.put((client_id, kind, dict(booking))):
        print(f"  [notify] queue full ({QUEUE_MAX}); a {kind} text for {client_id} was dropped.")


def send_reminders(today: dt.date | None = None) -> int:
    """Queue a reminder for every confirmed booking tomorrow that hasn't had
    one yet (safe to run more than once a day). Returns how many were queued."""
    tomorrow = ((today or dt.date.today()) + dt.timedelta(days=1)).isoformat()
    already = {(n["client_id"], n["booking"]["date"], n["booking"]["time"], n.get("to"))
               for n in storage.read_notifications()
               if n.get("kind") == "reminder" and n.get("status") in ("sent", "dry-run")}
    queued = 0
    for entry in storage.all_clients():
        cid = entry["client_id"]
        for b in storage.read_bookings(cid):
            if b["status"] != "confirmed" or b["date"] != tomorrow:
                continue
            if (cid, b["date"], b["time"], to_e164(b["phone"])) in already:
                continue
            booking_event(cid, "reminder", b)
            queued += 1
    return queued


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] != ["reminders"]:
        print("usage: python notify.py reminders")
        return 2
    n = send_reminders()
    left = _queue.drain(60)
    print(f"queued {n} reminder(s); {left} still sending" if left else f"queued {n} reminder(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
