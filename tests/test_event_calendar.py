"""Tests for mcp_server.event_calendar — parsing, blackout gates, expiry map."""

from datetime import date, datetime, timedelta, timezone

from mcp_server.event_calendar import (
    DEFAULT_BUFFERS,
    KNOWN_TYPES,
    WEEKLY_EXPIRY_DAY,
    CalendarEvent,
    EventCalendar,
    _parse_events,
    expiry_instruments_today,
    get_calendar,
    is_expiry_day,
)

IST = timezone(timedelta(hours=5, minutes=30))


# ── Fixtures ────────────────────────────────────────────────


def _event(
    dt: datetime,
    event_type: str = "rbi_policy",
    buffer_hours: int | None = None,
) -> CalendarEvent:
    bh = buffer_hours if buffer_hours is not None else DEFAULT_BUFFERS.get(event_type, 4)
    return CalendarEvent(dt=dt, type=event_type, buffer_hours=bh)


def _future(hours: float = 2) -> datetime:
    return datetime.now(IST) + timedelta(hours=hours)


def _past(hours: float = 2) -> datetime:
    return datetime.now(IST) - timedelta(hours=hours)


# ── _parse_events ────────────────────────────────────────────


def test_parse_iso_datetime_string():
    raw = [{"datetime": "2026-04-09T10:00:00+05:30", "type": "rbi_policy"}]
    events = _parse_events(raw)
    assert len(events) == 1
    assert events[0].type == "rbi_policy"
    assert events[0].dt.tzinfo is not None


def test_parse_bare_date_string():
    raw = [{"datetime": "2026-02-01", "type": "budget"}]
    events = _parse_events(raw)
    assert len(events) == 1
    assert events[0].dt.hour == 9   # defaults to market open
    assert events[0].dt.minute == 15


def test_parse_applies_default_buffer():
    raw = [{"datetime": "2026-04-09T10:00:00+05:30", "type": "rbi_policy"}]
    events = _parse_events(raw)
    assert events[0].buffer_hours == DEFAULT_BUFFERS["rbi_policy"]


def test_parse_custom_buffer_overrides_default():
    raw = [{"datetime": "2026-04-09T10:00:00+05:30", "type": "rbi_policy",
            "buffer_hours": 99}]
    events = _parse_events(raw)
    assert events[0].buffer_hours == 99


def test_parse_malformed_event_skipped():
    raw = [
        {"datetime": "NOT_A_DATE", "type": "rbi_policy"},
        {"datetime": "2026-06-05T10:00:00+05:30", "type": "fed_fomc"},
    ]
    events = _parse_events(raw)
    assert len(events) == 1
    assert events[0].type == "fed_fomc"


def test_parse_sorted_chronologically():
    raw = [
        {"datetime": "2026-12-01T10:00:00+05:30", "type": "rbi_policy"},
        {"datetime": "2026-03-01T10:00:00+05:30", "type": "cpi_india"},
    ]
    events = _parse_events(raw)
    assert events[0].dt < events[1].dt


# ── CalendarEvent helpers ────────────────────────────────────


def test_blackout_start_end():
    dt = _future(10)
    e = _event(dt, buffer_hours=6)
    assert e.blackout_start() == dt - timedelta(hours=6)
    assert e.blackout_end() == dt + timedelta(hours=6)


def test_in_blackout_true_when_inside_window():
    now = datetime.now(IST)
    dt = now + timedelta(hours=3)          # event 3h from now
    e = _event(dt, buffer_hours=6)         # buffer=6h → window starts -3h from now
    assert e.in_blackout(now) is True


def test_in_blackout_false_when_far_away():
    now = datetime.now(IST)
    dt = now + timedelta(hours=48)
    e = _event(dt, buffer_hours=6)
    assert e.in_blackout(now) is False


def test_in_blackout_false_when_zero_buffer():
    now = datetime.now(IST)
    e = _event(now, buffer_hours=0)
    assert e.in_blackout(now) is False


def test_hours_until_positive_for_future():
    now = datetime.now(IST)
    dt = now + timedelta(hours=5)
    e = _event(dt)
    assert 4.9 < e.hours_until(now) < 5.1


def test_hours_until_negative_for_past():
    now = datetime.now(IST)
    dt = now - timedelta(hours=3)
    e = _event(dt)
    assert e.hours_until(now) < 0


# ── EventCalendar.high_impact_within ────────────────────────


def test_high_impact_within_detects_upcoming():
    now = datetime.now(IST)
    e = _event(_future(3), buffer_hours=6)
    cal = EventCalendar([e])
    assert cal.high_impact_within(hours=6, now=now) is True


def test_high_impact_within_ignores_far_future():
    now = datetime.now(IST)
    e = _event(_future(50), buffer_hours=6)
    cal = EventCalendar([e])
    assert cal.high_impact_within(hours=6, now=now) is False


def test_high_impact_within_ignores_zero_buffer():
    now = datetime.now(IST)
    e = _event(_future(1), buffer_hours=0)
    cal = EventCalendar([e])
    assert cal.high_impact_within(hours=6, now=now) is False


def test_high_impact_within_type_filter():
    now = datetime.now(IST)
    rbi = _event(_future(2), event_type="rbi_policy")
    nfp = _event(_future(3), event_type="us_nfp")
    cal = EventCalendar([rbi, nfp])
    # Only check for budget — neither event matches
    assert cal.high_impact_within(hours=6, event_types={"budget"}, now=now) is False
    # Check for rbi_policy — should find it
    assert cal.high_impact_within(hours=6, event_types={"rbi_policy"}, now=now) is True


def test_high_impact_within_already_in_blackout():
    now = datetime.now(IST)
    # Event was 2h ago, buffer=6h → still in blackout
    e = _event(_past(2), buffer_hours=6)
    cal = EventCalendar([e])
    # hours=-2 is within [-6, 6] window
    assert cal.high_impact_within(hours=0, now=now) is True


# ── EventCalendar.in_any_blackout ────────────────────────────


def test_in_any_blackout_true():
    now = datetime.now(IST)
    e = _event(now + timedelta(hours=1), buffer_hours=4)
    cal = EventCalendar([e])
    assert cal.in_any_blackout(now) is True


def test_in_any_blackout_false_when_clean():
    now = datetime.now(IST)
    e = _event(now + timedelta(hours=48), buffer_hours=4)
    cal = EventCalendar([e])
    assert cal.in_any_blackout(now) is False


# ── EventCalendar.upcoming ────────────────────────────────────


def test_upcoming_returns_events_in_window():
    now = datetime.now(IST)
    e1 = _event(now + timedelta(hours=3))
    e2 = _event(now + timedelta(hours=30))
    cal = EventCalendar([e1, e2])
    result = cal.upcoming(hours=6, now=now)
    assert len(result) == 1
    assert result[0] is e1


def test_upcoming_empty_when_no_events():
    cal = EventCalendar([])
    assert cal.upcoming(hours=24) == []


def test_next_event_returns_soonest():
    now = datetime.now(IST)
    e1 = _event(now + timedelta(hours=10))
    e2 = _event(now + timedelta(hours=2))
    cal = EventCalendar([e1, e2])
    nxt = cal.next_event(now)
    assert nxt is e2


# ── Weekly expiry ─────────────────────────────────────────────


def test_is_expiry_day_banknifty_wednesday():
    # Find the next Wednesday
    today = date.today()
    days_until_wed = (2 - today.weekday()) % 7
    next_wed = today + timedelta(days=days_until_wed if days_until_wed else 7)
    assert is_expiry_day("BANKNIFTY", next_wed) is True


def test_is_expiry_day_nifty_thursday():
    today = date.today()
    days_until_thu = (3 - today.weekday()) % 7
    next_thu = today + timedelta(days=days_until_thu if days_until_thu else 7)
    assert is_expiry_day("NIFTY", next_thu) is True


def test_is_expiry_day_case_insensitive():
    today = date.today()
    days_until_thu = (3 - today.weekday()) % 7
    next_thu = today + timedelta(days=days_until_thu if days_until_thu else 7)
    assert is_expiry_day("nifty", next_thu) is True


def test_is_expiry_day_false_on_wrong_day():
    today = date.today()
    days_until_mon = (0 - today.weekday()) % 7
    next_mon = today + timedelta(days=days_until_mon if days_until_mon else 7)
    # NIFTY expires Thursday, not Monday
    assert is_expiry_day("NIFTY", next_mon) is False


def test_is_expiry_day_unknown_instrument():
    assert is_expiry_day("UNKNOWNINSTRUMENT") is False


def test_expiry_instruments_today_is_list():
    result = expiry_instruments_today()
    assert isinstance(result, list)
    # Each returned item must be in WEEKLY_EXPIRY_DAY
    for inst in result:
        assert inst in WEEKLY_EXPIRY_DAY


def test_weekly_expiry_day_covers_all_6_instruments():
    assert len(WEEKLY_EXPIRY_DAY) == 6


# ── get_calendar (singleton + YAML loading) ──────────────────


def test_get_calendar_returns_event_calendar():
    cal = get_calendar()
    assert isinstance(cal, EventCalendar)


def test_get_calendar_loads_events_from_yaml():
    cal = get_calendar()
    # The YAML has many events; at least 10 should load
    assert len(cal._events) >= 10


def test_get_calendar_reload_refreshes():
    cal1 = get_calendar()
    cal2 = get_calendar(reload=True)
    # Should be a new instance but with same event count
    assert len(cal1._events) == len(cal2._events)


# ── DEFAULT_BUFFERS sanity ────────────────────────────────────


def test_budget_buffer_is_24h():
    assert DEFAULT_BUFFERS["budget"] == 24


def test_fed_fomc_buffer_is_12h():
    assert DEFAULT_BUFFERS["fed_fomc"] == 12


def test_monthly_expiry_buffer_is_2h():
    assert DEFAULT_BUFFERS["monthly_expiry"] == 2


def test_earnings_season_start_buffer_is_zero():
    assert DEFAULT_BUFFERS["earnings_season_start"] == 0


# ── KNOWN_TYPES completeness ─────────────────────────────────


def test_known_types_includes_key_events():
    for t in ("rbi_policy", "fed_fomc", "budget", "us_nfp", "monthly_expiry"):
        assert t in KNOWN_TYPES


# ── status() dict ─────────────────────────────────────────────


def test_status_has_expected_keys():
    cal = get_calendar()
    s = cal.status()
    for k in ("in_blackout", "upcoming_24h", "next_event", "expiry_today", "total_events_loaded"):
        assert k in s


def test_status_total_events_positive():
    s = get_calendar().status()
    assert s["total_events_loaded"] >= 10
