"""scheduling.py — turn a business's opening hours into bookable slots.

WHY this module exists (it replaced a real outage): slots used to be written
into the client YAML as concrete dates for the next 7 days at onboarding.
Two months later every one of those dates was in the past, so
check_availability answered "no slot information" for every date a customer
asked about — the agent silently stopped being able to book anything.

Now the YAML stores the RULE instead of the dates:

    schedule:
      days: [Mon, Tue, Wed, Thu, Fri, Sat]
      ranges: [["09:30", "13:00"], ["16:00", "20:30"]]
      gap_min: 30
      horizon_days: 7

and the concrete slots are generated on demand for today..today+horizon.
A rule cannot expire, so this can never go stale again. Generation is pure
computation (no disk, no network) and cached per (schedule, day) so the hot
path costs a dict lookup.

Slots already in the past are never offered — at 6 PM the agent must not
suggest 09:30 "today".
"""

import datetime as dt
import re
import threading

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

DEFAULT_HORIZON_DAYS = 7
MIN_GAP_MIN = 5
# Don't offer a slot that starts in the next few minutes — nobody can get there.
LEAD_TIME_MIN = 30

_lock = threading.Lock()
_cache: dict = {}  # (schedule_key, today) -> {date: [times]}


def _schedule_key(schedule: dict) -> tuple:
    """Hashable identity of a schedule, so the cache can key on it."""
    return (
        tuple(schedule.get("days") or ()),
        tuple(tuple(r) for r in (schedule.get("ranges") or ())),
        int(schedule.get("gap_min") or 30),
        int(schedule.get("horizon_days") or DEFAULT_HORIZON_DAYS),
    )


# "9:00", "09:00", "9.30", "10:00 AM", "7pm", "19:00:00"
_TIME_RE = re.compile(
    r"^\s*(\d{1,2})(?:\s*[:.]\s*(\d{2}))?(?:\s*:\s*\d{2})?\s*([ap])\.?\s*m\.?\s*$|"
    r"^\s*(\d{1,2})\s*[:.]\s*(\d{2})(?:\s*:\s*\d{2})?\s*$",
    re.IGNORECASE,
)


def parse_time(value) -> dt.time | None:
    """Read an opening time from whatever shape it arrives in.

    Three traps this closes, each of which silently deleted a whole range of
    a business's opening hours before:
      * YAML 1.1 turns "16:00" into the integer 960 (sexagesimal) while
        "09:30" stays a string — a hand-edited schedule could lose an evening.
      * time.fromisoformat demands a two-digit hour, so a typed "9:00" failed.
      * Owners naturally write "10:00 AM".
    """
    if isinstance(value, dt.time):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, int):                      # 960 -> 16:00
        return dt.time(value // 60, value % 60) if 0 <= value < 24 * 60 else None

    found = _TIME_RE.match(str(value))
    if not found:
        return None
    if found.group(1) is not None:                  # the am/pm branch
        hour, minute = int(found.group(1)), int(found.group(2) or 0)
        if found.group(3).lower() == "p" and hour < 12:
            hour += 12
        elif found.group(3).lower() == "a" and hour == 12:
            hour = 0
    else:
        hour, minute = int(found.group(4)), int(found.group(5))
    return dt.time(hour, minute) if hour < 24 and minute < 60 else None


def day_times(schedule: dict, day: dt.date) -> list[str]:
    """Every opening time on one date, ignoring bookings and the clock."""
    if WEEKDAYS[day.weekday()] not in (schedule.get("days") or []):
        return []
    gap = max(int(schedule.get("gap_min") or 30), MIN_GAP_MIN)
    times = []
    for rng in schedule.get("ranges") or []:
        if not rng or len(rng) < 2:
            continue
        start, end = parse_time(rng[0]), parse_time(rng[1])
        if start is None or end is None:
            print(f"  [scheduling] ignoring unreadable time range {rng!r}")
            continue
        t = dt.datetime.combine(day, start)
        stop = dt.datetime.combine(day, end)
        while t < stop:
            times.append(t.strftime("%H:%M"))
            t += dt.timedelta(minutes=gap)
    return sorted(set(times))


def generate(schedule: dict, today: dt.date | None = None) -> dict[str, list[str]]:
    """{date: [times]} for the rolling window. Cached per schedule per day."""
    today = today or dt.date.today()
    key = (_schedule_key(schedule), today)
    with _lock:
        hit = _cache.get(key)
    if hit is not None:
        # Copy: callers (agents) consume slots from their own view.
        return {d: list(t) for d, t in hit.items()}

    horizon = max(1, int(schedule.get("horizon_days") or DEFAULT_HORIZON_DAYS))
    slots = {}
    for i in range(horizon):
        day = today + dt.timedelta(days=i)
        slots[day.isoformat()] = day_times(schedule, day)
    with _lock:
        if len(_cache) > 256:       # tiny bound; schedules rarely differ
            _cache.clear()
        _cache[key] = slots
    return {d: list(t) for d, t in slots.items()}


def drop_past(slots: dict[str, list[str]], now: dt.datetime | None = None) -> dict[str, list[str]]:
    """Remove times that have already passed (or are too soon) today."""
    now = now or dt.datetime.now()
    today_iso = now.date().isoformat()
    cutoff = (now + dt.timedelta(minutes=LEAD_TIME_MIN)).strftime("%H:%M")
    day = slots.get(today_iso)
    if day:
        slots[today_iso] = [t for t in day if t >= cutoff]
    # Any date before today is meaningless in a rolling window.
    for date in [d for d in slots if d < today_iso]:
        del slots[date]
    return slots


def schedule_from_form(days, ranges, gap_min, horizon_days=DEFAULT_HORIZON_DAYS) -> dict:
    """Build the stored rule from the onboarding form's fields.

    Times are normalised to "HH:MM" strings so the stored YAML round-trips
    cleanly whatever the browser sent.
    """
    clean_ranges = []
    for r in ranges or []:
        if not r or len(r) < 2:
            continue
        start, end = parse_time(r[0]), parse_time(r[1])
        if start is None or end is None or start >= end:
            continue
        clean_ranges.append([start.strftime("%H:%M"), end.strftime("%H:%M")])
    return {
        "days": list(days or []),
        "ranges": clean_ranges,
        "gap_min": max(int(gap_min or 30), MIN_GAP_MIN),
        "horizon_days": int(horizon_days),
    }


def available_slots(config: dict, booked: set[tuple[str, str]],
                    now: dt.datetime | None = None) -> dict[str, list[str]]:
    """The agent's view of what's free.

    `config` is a client YAML; `booked` is {(date, time)} already taken.
    Businesses onboarded before schedules existed fall back to their literal
    `slots:` block, so nothing breaks for them.
    """
    schedule = config.get("schedule")
    if schedule:
        slots = generate(schedule, (now or dt.datetime.now()).date())
    else:
        slots = {str(d): list(t or []) for d, t in (config.get("slots") or {}).items()}
    slots = drop_past(slots, now)
    if booked:
        for date, times in slots.items():
            if any((date, t) in booked for t in times):
                slots[date] = [t for t in times if (date, t) not in booked]
    return slots
