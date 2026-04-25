"""
MKUMARAN Trading OS — High-Impact Event Calendar

Provides a single gate function `high_impact_within(hours)` that any
strategy or scanner can call to check whether a market-moving event
is close enough in time to warrant avoiding fresh positions.

Usage
─────
    from mcp_server.event_calendar import get_calendar

    cal = get_calendar()                        # cached singleton
    if cal.high_impact_within(hours=6):
        return None  # don't open new position near an event

    # Or with context
    events = cal.upcoming(hours=24)
    for e in events:
        logger.info("Upcoming: %s at %s", e.type, e.dt)

Event types and default blackout buffers (hours before + after)
───────────────────────────────────────────────────────────────
    rbi_policy           6h  — rate decision, INR moves sharply
    fed_fomc            12h  — global risk-off / risk-on pivot
    budget              24h  — full day before Finance Minister speaks
    election_result     48h  — two days around result day
    cpi_india            4h  — domestic inflation print
    us_nfp               4h  — monthly employment — high US equity vol
    gdp_india            4h  — India GDP advance estimate
    monthly_expiry       2h  — expiry-day gamma risk (long + short side)
    earnings_season_start 0h — informational only (no blackout)
    earnings_season_end   0h — informational only

Weekly options expiry (per-instrument by weekday)
─────────────────────────────────────────────────
    Monday     BANKEX   (BSE)
    Tuesday    MIDCPNIFTY, FINNIFTY   (NSE)
    Wednesday  BANKNIFTY   (NSE)
    Thursday   NIFTY   (NSE)
    Friday     SENSEX   (BSE)

`EventCalendar.is_expiry_day(instrument, date)` handles the per-day
lookup; no need to enumerate each expiry date in the YAML.

Data source
───────────
    events/calendar.yaml — checked-in, human-maintained, updated
    quarterly (Jan / Apr / Jul / Oct).

Design
──────
    Stateless except for the parsed event list. `get_calendar()` reads
    the YAML once per process; call `get_calendar(reload=True)` to
    force a re-read (e.g. after a hot-update of the YAML).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── IST timezone (UTC+5:30) ─────────────────────────────────
IST = timezone(timedelta(hours=5, minutes=30))

# ── Known event types ────────────────────────────────────────
KNOWN_TYPES = {
    "rbi_policy",
    "fed_fomc",
    "budget",
    "election_result",
    "cpi_india",
    "us_nfp",
    "gdp_india",
    "monthly_expiry",
    "earnings_season_start",
    "earnings_season_end",
}

# ── Default blackout buffers (hours) ─────────────────────────
# Applied symmetrically: block [event - buffer, event + buffer].
DEFAULT_BUFFERS: dict[str, int] = {
    "rbi_policy":            6,
    "fed_fomc":             12,
    "budget":               24,
    "election_result":      48,
    "cpi_india":             4,
    "us_nfp":                4,
    "gdp_india":             4,
    "monthly_expiry":        2,
    "earnings_season_start": 0,
    "earnings_season_end":   0,
}

# ── Weekly expiry map (instrument → weekday index, 0=Mon) ────
WEEKLY_EXPIRY_DAY: dict[str, int] = {
    "BANKEX":      0,   # Monday   (BSE)
    "MIDCPNIFTY":  1,   # Tuesday  (NSE)
    "FINNIFTY":    1,   # Tuesday  (NSE)
    "BANKNIFTY":   2,   # Wednesday(NSE)
    "NIFTY":       3,   # Thursday (NSE)
    "SENSEX":      4,   # Friday   (BSE)
}

# ── Path to the YAML data file ────────────────────────────────
# Use .resolve() so the path is absolute regardless of how Python was
# invoked (matters when __file__ is relative on some CI setups).
_CALENDAR_YAML = Path(__file__).resolve().parent.parent / "events" / "calendar.yaml"


@dataclass
class CalendarEvent:
    dt: datetime          # timezone-aware (IST or UTC-aware)
    type: str
    buffer_hours: int
    notes: str = ""

    def blackout_start(self) -> datetime:
        return self.dt - timedelta(hours=self.buffer_hours)

    def blackout_end(self) -> datetime:
        return self.dt + timedelta(hours=self.buffer_hours)

    def in_blackout(self, now: datetime | None = None) -> bool:
        """Return True if `now` falls within [dt - buffer, dt + buffer]."""
        now = now or _now_ist()
        if self.buffer_hours == 0:
            return False
        return self.blackout_start() <= now <= self.blackout_end()

    def hours_until(self, now: datetime | None = None) -> float:
        now = now or _now_ist()
        delta = self.dt - now
        return delta.total_seconds() / 3600


def _now_ist() -> datetime:
    return datetime.now(IST)


def _parse_events(raw: list[dict[str, Any]]) -> list[CalendarEvent]:
    """Parse the list from the YAML into CalendarEvent objects."""
    events: list[CalendarEvent] = []
    for item in raw:
        try:
            raw_dt = item["datetime"]
            # Accept both full ISO datetimes and bare dates
            if isinstance(raw_dt, str):
                if "T" in raw_dt:
                    dt = datetime.fromisoformat(raw_dt)
                else:
                    # Bare date — assume market-open time IST
                    dt = datetime.fromisoformat(f"{raw_dt}T09:15:00+05:30")
            elif isinstance(raw_dt, (datetime,)):
                dt = raw_dt
            else:
                # pyyaml may return a date object for bare dates
                from datetime import date as _date
                if isinstance(raw_dt, _date):
                    dt = datetime(raw_dt.year, raw_dt.month, raw_dt.day,
                                  9, 15, 0, tzinfo=IST)
                else:
                    logger.warning("Unknown datetime format: %s", raw_dt)
                    continue

            # Ensure timezone-aware; treat naive as IST
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=IST)

            event_type = item.get("type", "unknown")
            buffer_h = item.get("buffer_hours", DEFAULT_BUFFERS.get(event_type, 4))
            notes = item.get("notes", "")

            events.append(CalendarEvent(
                dt=dt,
                type=event_type,
                buffer_hours=int(buffer_h),
                notes=notes,
            ))
        except Exception as e:
            logger.warning("event_calendar: skipping malformed event %s — %s", item, e)

    # Sort chronologically
    events.sort(key=lambda e: e.dt)
    return events


class EventCalendar:
    """Loaded event calendar with query methods."""

    def __init__(self, events: list[CalendarEvent]) -> None:
        self._events = events

    # ── Core gate ─────────────────────────────────────────────

    def high_impact_within(
        self,
        hours: float,
        event_types: set[str] | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Return True if any high-impact event is within `hours` hours.

        `event_types` restricts the check to specific types. If None,
        all types with buffer_hours > 0 are checked.
        """
        now = now or _now_ist()
        for event in self._events:
            if event.buffer_hours == 0:
                continue
            if event_types and event.type not in event_types:
                continue
            h = event.hours_until(now)
            if -event.buffer_hours <= h <= hours:
                return True
        return False

    def in_any_blackout(self, now: datetime | None = None) -> bool:
        """Return True if right now is inside any event's blackout window."""
        now = now or _now_ist()
        return any(e.in_blackout(now) for e in self._events if e.buffer_hours > 0)

    # ── Lookups ───────────────────────────────────────────────

    def upcoming(
        self,
        hours: float = 24,
        now: datetime | None = None,
    ) -> list[CalendarEvent]:
        """Return events within the next `hours` hours, sorted by time."""
        now = now or _now_ist()
        cutoff = now + timedelta(hours=hours)
        return [e for e in self._events if now <= e.dt <= cutoff]

    def next_event(self, now: datetime | None = None) -> CalendarEvent | None:
        now = now or _now_ist()
        future = sorted(
            [e for e in self._events if e.dt >= now],
            key=lambda e: e.dt,
        )
        return future[0] if future else None

    def events_on_date(self, d: "date", now: datetime | None = None) -> list[CalendarEvent]:  # noqa: F821
        return [e for e in self._events
                if e.dt.astimezone(IST).date() == d]

    # ── Weekly options expiry ────────────────────────────────

    @staticmethod
    def is_expiry_day(
        instrument: str,
        d: "date | None" = None,  # noqa: F821
    ) -> bool:
        """Return True if `d` (default today) is the weekly expiry day
        for `instrument` based on the WEEKLY_EXPIRY_DAY map.

        Does NOT check for holiday-adjusted expiries — the exchange
        sometimes shifts expiry when the normal day is a market holiday.
        For production use, cross-reference with market_calendar.is_market_open().
        """
        from datetime import date as _date
        if d is None:
            d = _date.today()
        expected_weekday = WEEKLY_EXPIRY_DAY.get(instrument.upper())
        if expected_weekday is None:
            return False
        return d.weekday() == expected_weekday

    @staticmethod
    def expiry_instruments_today(d: "date | None" = None) -> list[str]:  # noqa: F821
        """Return all instruments with weekly expiry on day `d` (default today)."""
        from datetime import date as _date
        if d is None:
            d = _date.today()
        return [inst for inst, wday in WEEKLY_EXPIRY_DAY.items()
                if d.weekday() == wday]

    # ── Summary ───────────────────────────────────────────────

    def status(self, now: datetime | None = None) -> dict:
        """Return a status dict suitable for the /api/events/status endpoint."""
        now = now or _now_ist()
        upcoming_24h = self.upcoming(hours=24, now=now)
        in_blackout = self.in_any_blackout(now)
        nxt = self.next_event(now)
        return {
            "in_blackout": in_blackout,
            "upcoming_24h": [
                {"type": e.type, "dt": e.dt.isoformat(),
                 "hours_until": round(e.hours_until(now), 1),
                 "notes": e.notes}
                for e in upcoming_24h
            ],
            "next_event": (
                {"type": nxt.type, "dt": nxt.dt.isoformat(),
                 "hours_until": round(nxt.hours_until(now), 1)}
                if nxt else None
            ),
            "expiry_today": expiry_instruments_today() if False else
                            EventCalendar.expiry_instruments_today(),
            "total_events_loaded": len(self._events),
        }


# ── Singleton ────────────────────────────────────────────────

_instance: EventCalendar | None = None


def get_calendar(reload: bool = False) -> EventCalendar:
    """Return the process-level EventCalendar singleton.

    Reads `events/calendar.yaml` on first call (or when reload=True).
    """
    global _instance
    if _instance is None or reload:
        _instance = _load_calendar()
    return _instance


def _load_calendar() -> EventCalendar:
    try:
        import yaml  # pyyaml is already in requirements
        with _CALENDAR_YAML.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        raw = data.get("events", []) if isinstance(data, dict) else []
        events = _parse_events(raw)
        logger.info("event_calendar: loaded %d events from %s", len(events), _CALENDAR_YAML)
        return EventCalendar(events)
    except FileNotFoundError:
        logger.warning("event_calendar: %s not found — returning empty calendar", _CALENDAR_YAML)
        return EventCalendar([])
    except Exception as e:
        logger.error("event_calendar: failed to load — %s", e)
        return EventCalendar([])


# Re-export so callers can do:
#   from mcp_server.event_calendar import expiry_instruments_today
expiry_instruments_today = EventCalendar.expiry_instruments_today
is_expiry_day = EventCalendar.is_expiry_day
