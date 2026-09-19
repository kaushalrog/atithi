"""Rolling availability — the module that ended the silent booking outage."""

import datetime as dt

import scheduling

MON_TO_SAT = {
    "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
    "ranges": [["09:30", "13:00"], ["16:00", "20:30"]],
    "gap_min": 30,
    "horizon_days": 7,
}


def test_window_always_starts_today_however_old_the_config():
    """The outage in one assertion: a rule cannot drift into the past."""
    slots = scheduling.generate(MON_TO_SAT)
    assert min(slots) == dt.date.today().isoformat()
    assert len(slots) == 7
    assert sum(len(v) for v in slots.values()) > 0


def test_closed_days_are_empty_open_days_are_not():
    slots = scheduling.generate(MON_TO_SAT)
    for date, times in slots.items():
        weekday = scheduling.WEEKDAYS[dt.date.fromisoformat(date).weekday()]
        assert (times != []) == (weekday != "Sun")


def test_times_follow_the_ranges_and_gap():
    day = scheduling.day_times(MON_TO_SAT, dt.date(2026, 9, 21))  # a Monday
    assert day[0] == "09:30"
    assert "13:00" not in day          # end of range is exclusive
    assert "15:30" not in day          # the gap between ranges is closed
    assert "16:00" in day and day[-1] == "20:00"


def test_yaml_sexagesimal_times_still_work():
    """YAML turns '16:00' into the integer 960; a range must not vanish.

    Losing a range silently would halve a business's bookable hours with no
    error anywhere — so every shape YAML can produce has to be understood.
    """
    assert scheduling.parse_time(960) == dt.time(16, 0)
    assert scheduling.parse_time("09:30") == dt.time(9, 30)
    assert scheduling.parse_time(dt.time(8, 15)) == dt.time(8, 15)
    assert scheduling.parse_time("nonsense") is None
    # shapes a human or an API client actually sends
    assert scheduling.parse_time("9:00") == dt.time(9, 0)
    assert scheduling.parse_time("10:00 AM") == dt.time(10, 0)
    assert scheduling.parse_time("7pm") == dt.time(19, 0)
    assert scheduling.parse_time("12:30 am") == dt.time(0, 30)
    assert scheduling.parse_time("19:00:00") == dt.time(19, 0)
    assert scheduling.parse_time("25:00") is None

    mangled = dict(MON_TO_SAT, ranges=[[570, 780]])      # 09:30 - 13:00 as ints
    assert scheduling.day_times(mangled, dt.date(2026, 9, 21))[0] == "09:30"


def test_past_times_today_are_not_offered():
    now = dt.datetime.combine(dt.date.today(), dt.time(18, 0))
    slots = scheduling.drop_past(
        {dt.date.today().isoformat(): ["09:30", "17:00", "19:00", "20:00"]}, now
    )
    assert slots[dt.date.today().isoformat()] == ["19:00", "20:00"]


def test_dates_before_today_are_dropped():
    old = (dt.date.today() - dt.timedelta(days=3)).isoformat()
    slots = scheduling.drop_past({old: ["10:00"], dt.date.today().isoformat(): []})
    assert old not in slots


def test_booked_slots_are_removed():
    slots = scheduling.generate(MON_TO_SAT)
    date = next(d for d, t in sorted(slots.items()) if t)
    taken = slots[date][0]
    result = scheduling.available_slots(
        {"schedule": MON_TO_SAT}, {(date, taken)}
    )
    assert taken not in result[date]


def test_legacy_clients_without_a_schedule_still_work():
    """Businesses onboarded before schedules existed keep their dated slots."""
    future = (dt.date.today() + dt.timedelta(days=2)).isoformat()
    config = {"slots": {future: ["11:00", "12:00"]}}
    assert scheduling.available_slots(config, set())[future] == ["11:00", "12:00"]


def test_schedule_from_form_normalises_and_rejects_junk():
    schedule = scheduling.schedule_from_form(
        ["Mon"], [["9:00", "12:00"], ["", ""], ["18:00", "17:00"]], 15
    )
    assert schedule["ranges"] == [["09:00", "12:00"]]   # blank + reversed dropped
    assert schedule["gap_min"] == 15


def test_generation_is_cached_but_callers_get_their_own_copy():
    a = scheduling.generate(MON_TO_SAT)
    b = scheduling.generate(MON_TO_SAT)
    assert a == b
    date = next(iter(a))
    a[date].append("99:99")
    assert "99:99" not in scheduling.generate(MON_TO_SAT)[date]
