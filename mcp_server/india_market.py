"""India market utilities — IST timezone, NSE/MCX hours, holidays, INR formatting."""

import logging
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

# ── Indian Exchange Market Hours (IST) ────────────────────────
EXCHANGE_HOURS = {
    "NSE": {"open": time(9, 15), "close": time(15, 30)},
    "BSE": {"open": time(9, 15), "close": time(15, 30)},
    "NFO": {"open": time(9, 15), "close": time(15, 30)},
    "MCX": {"open": time(9, 0), "close": time(23, 30)},
    "CDS": {"open": time(9, 0), "close": time(17, 0)},
}

# Indian exchanges only — reject anything else
VALID_EXCHANGES = {"NSE", "BSE", "NFO", "MCX", "CDS"}

VALID_ASSET_CLASSES = {"EQUITY", "COMMODITY", "CURRENCY", "FNO"}

# ── 2026 NSE Holidays (seed — update yearly) ─────────────────
NSE_HOLIDAYS_2026 = [
    date(2026, 1, 26),   # Republic Day
    date(2026, 3, 10),   # Maha Shivaratri
    date(2026, 3, 17),   # Holi
    date(2026, 3, 30),   # Id-Ul-Fitr (Eid)
    date(2026, 4, 2),    # Ram Navami
    date(2026, 4, 3),    # Good Friday
    date(2026, 4, 14),   # Dr. Ambedkar Jayanti
    date(2026, 5, 1),    # Maharashtra Day
    date(2026, 6, 5),    # Bakri Eid
    date(2026, 7, 6),    # Muharram
    date(2026, 8, 15),   # Independence Day
    date(2026, 8, 18),   # Janmashtami
    date(2026, 10, 2),   # Mahatma Gandhi Jayanti
    date(2026, 10, 20),  # Dussehra
    date(2026, 11, 9),   # Diwali (Laxmi Pujan)
    date(2026, 11, 10),  # Diwali (Balipratipada)
    date(2026, 11, 27),  # Guru Nanak Jayanti
    date(2026, 12, 25),  # Christmas
]


def now_ist() -> datetime:
    """Current datetime in IST."""
    return datetime.now(IST)


def today_ist() -> date:
    """Current date in IST."""
    return now_ist().date()


def is_holiday(d: date | None = None, exchange: str = "NSE") -> bool:
    """Check if a date is a market holiday."""
    d = d or today_ist()
    return d in NSE_HOLIDAYS_2026


def is_weekend(d: date | None = None) -> bool:
    d = d or today_ist()
    return d.weekday() >= 5  # Saturday=5, Sunday=6


def is_market_open(exchange: str = "NSE") -> bool:
    """Check if Indian market is currently open (IST)."""
    now = now_ist()
    d = now.date()

    if is_weekend(d) or is_holiday(d, exchange):
        return False

    hours = EXCHANGE_HOURS.get(exchange, EXCHANGE_HOURS["NSE"])
    current_time = now.time()
    return hours["open"] <= current_time <= hours["close"]


def get_market_status(exchange: str = "NSE") -> str:
    """Return PRE, LIVE, POST, or CLOSED."""
    now = now_ist()
    d = now.date()

    if is_weekend(d) or is_holiday(d, exchange):
        return "CLOSED"

    hours = EXCHANGE_HOURS.get(exchange, EXCHANGE_HOURS["NSE"])
    current_time = now.time()

    if current_time < hours["open"]:
        return "PRE"
    elif current_time > hours["close"]:
        return "POST"
    else:
        return "LIVE"


def validate_exchange(exchange: str) -> bool:
    """Validate exchange is Indian only."""
    return exchange.upper() in VALID_EXCHANGES


def format_inr(amount: float, show_symbol: bool = True) -> str:
    """Format amount in Indian Rupee format (₹1,23,456.78)."""
    negative = amount < 0
    amount = abs(amount)

    # Split into integer and decimal
    integer_part = int(amount)
    decimal_part = f"{amount - integer_part:.2f}"[1:]  # ".78"

    # Indian grouping: last 3 digits, then groups of 2
    s = str(integer_part)
    if len(s) <= 3:
        formatted = s
    else:
        last3 = s[-3:]
        remaining = s[:-3]
        groups = []
        while remaining:
            groups.insert(0, remaining[-2:])
            remaining = remaining[:-2]
        formatted = ",".join(groups) + "," + last3

    result = formatted + decimal_part
    if show_symbol:
        result = "₹" + result
    if negative:
        result = "-" + result
    return result


def format_inr_compact(amount: float) -> str:
    """Format in compact Indian notation (₹1.2L, ₹3.4Cr)."""
    negative = amount < 0
    amount = abs(amount)

    if amount >= 1_00_00_000:  # 1 Crore
        val = f"₹{amount / 1_00_00_000:.1f}Cr"
    elif amount >= 1_00_000:  # 1 Lakh
        val = f"₹{amount / 1_00_000:.1f}L"
    elif amount >= 1000:
        val = f"₹{amount / 1000:.1f}K"
    else:
        val = f"₹{amount:.0f}"

    return f"-{val}" if negative else val


def validate_trading_hours(exchange: str = "NSE") -> tuple[bool, str]:
    """Validate if trading is allowed right now. Returns (ok, reason)."""
    if not validate_exchange(exchange):
        return False, f"Invalid exchange: {exchange}. Indian exchanges only: {', '.join(sorted(VALID_EXCHANGES))}"

    now = now_ist()
    d = now.date()

    if is_weekend(d):
        return False, f"Market closed — weekend ({now.strftime('%A')})"

    if is_holiday(d, exchange):
        return False, f"Market closed — holiday ({d.isoformat()})"

    hours = EXCHANGE_HOURS.get(exchange, EXCHANGE_HOURS["NSE"])
    current_time = now.time()

    if current_time < hours["open"]:
        return False, f"{exchange} pre-market — opens at {hours['open'].strftime('%H:%M')} IST"

    if current_time > hours["close"]:
        return False, f"{exchange} closed — closed at {hours['close'].strftime('%H:%M')} IST"

    return True, "Market open"


# ── SEBI Disclaimer ──────────────────────────────────────────
SEBI_DISCLAIMER = (
    "DISCLAIMER: This is not SEBI-registered investment advice. "
    "Signals are AI-generated for educational and analytical purposes only. "
    "Trading in securities market involves risk. Past performance is not indicative "
    "of future results. Please consult a SEBI-registered financial advisor before "
    "making investment decisions."
)
