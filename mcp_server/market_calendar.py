"""
MKUMARAN Trading OS — Market Calendar & Trading Hours Validation

Validates orders against exchange trading hours and market holidays.
Prevents Kite rejections from after-hours order placement.

Exchange hours (IST):
- NSE/BSE: 09:15 - 15:30 (pre-market 09:00-09:08)
- MCX: 09:00 - 23:30 (metals/energy), 10:00 - 23:30 (agri)
- NFO: 09:15 - 15:30
- CDS: 09:00 - 17:00
"""

import logging
from datetime import datetime, time, date, timezone, timedelta

logger = logging.getLogger(__name__)

# Indian Standard Time (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

# ── Exchange Trading Hours (IST) ────────────────────────────

EXCHANGE_HOURS: dict[str, tuple[time, time]] = {
    "NSE": (time(9, 15), time(15, 30)),
    "BSE": (time(9, 15), time(15, 30)),
    "NFO": (time(9, 15), time(15, 30)),
    "MCX": (time(9, 0), time(23, 30)),
    "CDS": (time(9, 0), time(17, 0)),
}

# Buffer minutes before/after market for order prep
ORDER_BUFFER_MINUTES = 5

# ── NSE/BSE Market Holidays 2026 (Gazetted) ─────────────────
# Source: NSE circular (CMTR71775), verified March 2026
# Only weekday holidays — weekends handled by is_weekend()
NSE_HOLIDAYS_2026 = {
    date(2026, 1, 15),   # Municipal Corporation Election (Maharashtra)
    date(2026, 1, 26),   # Republic Day
    date(2026, 3, 3),    # Holi
    date(2026, 3, 26),   # Shri Ram Navami
    date(2026, 3, 31),   # Shri Mahavir Jayanti
    date(2026, 4, 3),    # Good Friday
    date(2026, 4, 14),   # Dr. Baba Saheb Ambedkar Jayanti
    date(2026, 5, 1),    # Maharashtra Day
    date(2026, 5, 28),   # Bakri Id (Eid-Ul-Adha)
    date(2026, 6, 26),   # Muharram
    date(2026, 9, 14),   # Ganesh Chaturthi
    date(2026, 10, 2),   # Mahatma Gandhi Jayanti
    date(2026, 10, 20),  # Dussehra
    date(2026, 11, 10),  # Diwali (Balipratipada)
    date(2026, 11, 24),  # Prakash Gurpurb Sri Guru Nanak Dev
    date(2026, 12, 25),  # Christmas
}

# MCX follows NSE holidays mostly, with some differences
MCX_HOLIDAYS_2026 = NSE_HOLIDAYS_2026.copy()

# CDS follows NSE holidays
CDS_HOLIDAYS_2026 = NSE_HOLIDAYS_2026.copy()

# Map exchange to holiday set
EXCHANGE_HOLIDAYS: dict[str, set[date]] = {
    "NSE": NSE_HOLIDAYS_2026,
    "BSE": NSE_HOLIDAYS_2026,
    "NFO": NSE_HOLIDAYS_2026,
    "MCX": MCX_HOLIDAYS_2026,
    "CDS": CDS_HOLIDAYS_2026,
}


def _now_ist() -> datetime:
    """Current datetime in IST regardless of server timezone."""
    return datetime.now(IST)


def is_market_holiday(exchange: str, check_date: date | None = None) -> bool:
    """Check if given date is a market holiday for the exchange."""
    if check_date is None:
        check_date = _now_ist().date()

    holidays = EXCHANGE_HOLIDAYS.get(exchange.upper(), NSE_HOLIDAYS_2026)
    return check_date in holidays


def is_weekend(check_date: date | None = None) -> bool:
    """Check if given date is Saturday (5) or Sunday (6)."""
    if check_date is None:
        check_date = _now_ist().date()
    return check_date.weekday() >= 5


def is_market_open(exchange: str, check_time: datetime | None = None) -> bool:
    """
    Check if the market is currently open for the given exchange.

    Considers: trading hours, weekends, holidays.
    """
    if check_time is None:
        check_time = _now_ist()

    check_date = check_time.date()

    # Weekend check
    if is_weekend(check_date):
        return False

    # Holiday check
    if is_market_holiday(exchange, check_date):
        return False

    # Trading hours check
    hours = EXCHANGE_HOURS.get(exchange.upper())
    if hours is None:
        logger.warning("Unknown exchange %s — defaulting to NSE hours", exchange)
        hours = EXCHANGE_HOURS["NSE"]

    market_open, market_close = hours
    current_time = check_time.time()

    return market_open <= current_time <= market_close


def get_market_status(exchange: str, check_time: datetime | None = None) -> dict:
    """
    Get detailed market status for an exchange.

    Returns dict with: is_open, exchange, reason, hours, next_open_hint
    """
    if check_time is None:
        check_time = _now_ist()

    check_date = check_time.date()
    current_time = check_time.time()
    hours = EXCHANGE_HOURS.get(exchange.upper(), EXCHANGE_HOURS["NSE"])
    market_open, market_close = hours

    if is_weekend(check_date):
        return {
            "is_open": False,
            "exchange": exchange,
            "reason": "WEEKEND",
            "hours": f"{market_open.strftime('%H:%M')}-{market_close.strftime('%H:%M')} IST",
            "next_open_hint": "Monday",
        }

    if is_market_holiday(exchange, check_date):
        return {
            "is_open": False,
            "exchange": exchange,
            "reason": "HOLIDAY",
            "hours": f"{market_open.strftime('%H:%M')}-{market_close.strftime('%H:%M')} IST",
            "next_open_hint": "Next trading day",
        }

    if current_time < market_open:
        return {
            "is_open": False,
            "exchange": exchange,
            "reason": "PRE_MARKET",
            "hours": f"{market_open.strftime('%H:%M')}-{market_close.strftime('%H:%M')} IST",
            "next_open_hint": f"Opens at {market_open.strftime('%H:%M')} IST",
        }

    if current_time > market_close:
        return {
            "is_open": False,
            "exchange": exchange,
            "reason": "POST_MARKET",
            "hours": f"{market_open.strftime('%H:%M')}-{market_close.strftime('%H:%M')} IST",
            "next_open_hint": "Next trading day",
        }

    return {
        "is_open": True,
        "exchange": exchange,
        "reason": "OPEN",
        "hours": f"{market_open.strftime('%H:%M')}-{market_close.strftime('%H:%M')} IST",
    }


def validate_order_timing(exchange: str, check_time: datetime | None = None) -> str | None:
    """
    Validate if an order can be placed now for the given exchange.

    Returns None if OK, error message string if order should be rejected.
    Used as pre-trade check in OrderManager._validate_order().
    """
    status = get_market_status(exchange, check_time)

    if status["is_open"]:
        return None  # OK to trade

    reason = status["reason"]
    hint = status.get("next_open_hint", "")

    return (
        f"Market CLOSED for {exchange}: {reason}. "
        f"Hours: {status['hours']}. {hint}"
    )
