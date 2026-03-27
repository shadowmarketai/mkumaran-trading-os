"""Tests for Earnings Calendar: formatters, config, alert tracking."""

from mcp_server.earnings_calendar import (
    ALERT_DAYS_BEFORE,
    NSE_HEADERS,
    _sent_alerts,
    format_earnings_telegram,
    JPMORGAN_PROMPT,
)


# ── Config Constants ─────────────────────────────────────────

def test_alert_days_before():
    assert ALERT_DAYS_BEFORE == 2


def test_nse_headers_has_user_agent():
    assert "User-Agent" in NSE_HEADERS
    assert "Referer" in NSE_HEADERS
    assert "nseindia" in NSE_HEADERS["Referer"]


# ── _sent_alerts Tracking ────────────────────────────────────

def test_sent_alerts_is_dict():
    assert isinstance(_sent_alerts, dict)


def test_sent_alerts_dedup():
    """Adding same key twice should overwrite."""
    _sent_alerts["TEST:2025-01-01"] = "2025-01-01"
    _sent_alerts["TEST:2025-01-01"] = "2025-01-02"
    assert _sent_alerts["TEST:2025-01-01"] == "2025-01-02"
    del _sent_alerts["TEST:2025-01-01"]


# ── format_earnings_telegram ─────────────────────────────────

def test_format_earnings_telegram_today():
    event = {
        "ticker": "RELIANCE",
        "company_name": "Reliance Industries",
        "results_date": "2025-04-15",
        "quarter": "Q4",
        "urgency": "TODAY",
    }
    msg = format_earnings_telegram(event, "Hold position. Results likely positive.")
    assert "RELIANCE" in msg
    assert "Q4" in msg
    assert "TODAY" in msg
    assert "Hold position" in msg


def test_format_earnings_telegram_tomorrow():
    event = {
        "ticker": "TCS",
        "company_name": "TCS Limited",
        "results_date": "2025-04-16",
        "quarter": "Q4",
        "urgency": "TOMORROW",
    }
    msg = format_earnings_telegram(event, "Reduce to 50%.")
    assert "TCS" in msg
    assert "TOMORROW" in msg


def test_format_earnings_telegram_in_days():
    event = {
        "ticker": "SBIN",
        "company_name": "State Bank of India",
        "results_date": "2025-04-17",
        "quarter": "Q3",
        "urgency": "IN 2 DAYS",
    }
    msg = format_earnings_telegram(event, "Keep watching.")
    assert "SBIN" in msg
    assert "Q3" in msg


def test_format_earnings_telegram_has_header():
    event = {
        "ticker": "INFY",
        "company_name": "Infosys",
        "results_date": "2025-04-20",
        "quarter": "Q4",
        "urgency": "IN 2 DAYS",
    }
    msg = format_earnings_telegram(event, "Brief here.")
    assert "PRE-EARNINGS ALERT" in msg
    assert "=" in msg


# ── JPMORGAN_PROMPT ──────────────────────────────────────────

def test_jpmorgan_prompt_is_string():
    assert isinstance(JPMORGAN_PROMPT, str)
    assert len(JPMORGAN_PROMPT) > 200


def test_jpmorgan_prompt_placeholders():
    result = JPMORGAN_PROMPT.format(
        ticker="RELIANCE", company_name="Reliance Industries",
        days_away=2, results_date="2025-04-15", quarter="Q4",
        cmp=2500, position_type="LONG", entry_price=2400,
        target=2700, stop_loss=2350, current_pnl="Rs.1000",
        quarterly_table="Q4 | 50000 | 12000 | 25",
        price_reactions="Q3 | 2025-01-15 | +3.2%",
        sector="Energy", market_cap=1500000, pe=28,
    )
    assert "RELIANCE" in result
    assert "Q4" in result


def test_jpmorgan_prompt_decision_options():
    assert "HOLD FULL POSITION" in JPMORGAN_PROMPT
    assert "REDUCE" in JPMORGAN_PROMPT
    assert "EXIT COMPLETELY" in JPMORGAN_PROMPT


# ── EarningsCalendar Class Import ────────────────────────────

def test_earnings_calendar_class_import():
    from mcp_server.earnings_calendar import EarningsCalendar
    assert callable(EarningsCalendar)
