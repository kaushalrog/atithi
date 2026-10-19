"""Server logic that doesn't need HTTP: slot generation from open hours."""

import datetime as dt

import server
from server import WEEKDAYS, generate_slots


def test_generate_slots_seven_days_from_today():
    slots = generate_slots(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                           [["10:00", "12:00"]], 30)
    today = dt.date.today()
    expected_keys = [(today + dt.timedelta(days=i)).isoformat() for i in range(7)]
    assert list(slots.keys()) == expected_keys
    assert all(day == ["10:00", "10:30", "11:00", "11:30"] for day in slots.values())


def test_generate_slots_respects_closed_days():
    slots = generate_slots(["Mon"], [["10:00", "11:00"]], 30)  # open Mondays only
    for date_str, times in slots.items():
        weekday = WEEKDAYS[dt.date.fromisoformat(date_str).weekday()]
        assert (times != []) == (weekday == "Mon")


def test_generate_slots_two_ranges_and_empty_second_range():
    slots = generate_slots(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                           [["09:00", "10:00"], ["", ""]], 60)
    assert all(day == ["09:00"] for day in slots.values())


def test_startup_prints_the_capacity_this_process_runs_with(monkeypatch):
    """One process, fixed pools: the operator must see the numbers (plan §2.7)."""
    import asyncio
    monkeypatch.setenv("MAX_CONCURRENT_CALLS", "5")

    async def line():
        return server._capacity_line()
    text = asyncio.run(line())
    assert "portal worker threads: 40" in text
    assert "phone call-I/O threads: 10" in text and "MAX_CONCURRENT_CALLS=5" in text
