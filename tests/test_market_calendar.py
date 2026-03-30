"""Tests for market calendar — trading hours, holidays, order timing validation."""

import pytest
from datetime import datetime, date, time

from mcp_server.market_calendar import (
    is_market_holiday,
    is_weekend,
    is_market_open,
    get_market_status,
    validate_order_timing,
    EXCHANGE_HOURS,
    NSE_HOLIDAYS_2026,
)


# ── Holiday Tests ────────────────────────────────────────────

class TestHolidays:
    def test_republic_day_is_holiday(self):
        assert is_market_holiday("NSE", date(2026, 1, 26))

    def test_diwali_is_holiday(self):
        assert is_market_holiday("NSE", date(2026, 11, 10))  # Balipratipada

    def test_regular_day_not_holiday(self):
        assert not is_market_holiday("NSE", date(2026, 3, 12))

    def test_mcx_shares_nse_holidays(self):
        assert is_market_holiday("MCX", date(2026, 1, 26))

    def test_unknown_exchange_defaults_nse(self):
        assert is_market_holiday("UNKNOWN", date(2026, 1, 26))

    def test_holiday_count_reasonable(self):
        # Indian markets typically have 14-18 holidays per year
        assert 14 <= len(NSE_HOLIDAYS_2026) <= 22


# ── Weekend Tests ────────────────────────────────────────────

class TestWeekend:
    def test_saturday_is_weekend(self):
        # 2026-01-03 is Saturday
        assert is_weekend(date(2026, 1, 3))

    def test_sunday_is_weekend(self):
        assert is_weekend(date(2026, 1, 4))

    def test_monday_not_weekend(self):
        assert not is_weekend(date(2026, 1, 5))

    def test_friday_not_weekend(self):
        assert not is_weekend(date(2026, 1, 2))


# ── Market Open Tests ───────────────────────────────────────

class TestMarketOpen:
    def test_nse_open_during_hours(self):
        # Thursday 10:00 AM — regular trading day
        dt = datetime(2026, 3, 12, 10, 0)
        assert is_market_open("NSE", dt)

    def test_nse_closed_before_open(self):
        dt = datetime(2026, 3, 12, 9, 0)  # 9:00 AM, before 9:15
        assert not is_market_open("NSE", dt)

    def test_nse_closed_after_close(self):
        dt = datetime(2026, 3, 12, 16, 0)  # 4:00 PM
        assert not is_market_open("NSE", dt)

    def test_mcx_open_evening(self):
        dt = datetime(2026, 3, 12, 20, 0)  # 8 PM — MCX open till 23:30
        assert is_market_open("MCX", dt)

    def test_mcx_closed_late_night(self):
        dt = datetime(2026, 3, 13, 0, 30)  # 12:30 AM — MCX closed
        assert not is_market_open("MCX", dt)

    def test_cds_closes_at_5pm(self):
        dt = datetime(2026, 3, 12, 17, 30)  # 5:30 PM
        assert not is_market_open("CDS", dt)

    def test_weekend_always_closed(self):
        dt = datetime(2026, 3, 14, 10, 0)  # Saturday
        assert not is_market_open("NSE", dt)

    def test_holiday_always_closed(self):
        dt = datetime(2026, 1, 26, 10, 0)  # Republic Day
        assert not is_market_open("NSE", dt)


# ── Market Status Tests ──────────────────────────────────────

class TestMarketStatus:
    def test_open_status(self):
        dt = datetime(2026, 3, 12, 10, 0)
        status = get_market_status("NSE", dt)
        assert status["is_open"]
        assert status["reason"] == "OPEN"

    def test_weekend_status(self):
        dt = datetime(2026, 3, 14, 10, 0)  # Saturday
        status = get_market_status("NSE", dt)
        assert not status["is_open"]
        assert status["reason"] == "WEEKEND"
        assert "Monday" in status["next_open_hint"]

    def test_holiday_status(self):
        dt = datetime(2026, 1, 26, 10, 0)
        status = get_market_status("NSE", dt)
        assert not status["is_open"]
        assert status["reason"] == "HOLIDAY"

    def test_pre_market_status(self):
        dt = datetime(2026, 3, 12, 9, 0)
        status = get_market_status("NSE", dt)
        assert not status["is_open"]
        assert status["reason"] == "PRE_MARKET"

    def test_post_market_status(self):
        dt = datetime(2026, 3, 12, 16, 0)
        status = get_market_status("NSE", dt)
        assert not status["is_open"]
        assert status["reason"] == "POST_MARKET"


# ── Order Timing Validation Tests ────────────────────────────

class TestOrderTimingValidation:
    def test_valid_during_market_hours(self):
        dt = datetime(2026, 3, 12, 10, 0)
        assert validate_order_timing("NSE", dt) is None  # None = OK

    def test_rejected_on_weekend(self):
        dt = datetime(2026, 3, 14, 10, 0)
        error = validate_order_timing("NSE", dt)
        assert error is not None
        assert "WEEKEND" in error

    def test_rejected_on_holiday(self):
        dt = datetime(2026, 1, 26, 10, 0)
        error = validate_order_timing("NSE", dt)
        assert error is not None
        assert "HOLIDAY" in error

    def test_rejected_before_open(self):
        dt = datetime(2026, 3, 12, 8, 0)
        error = validate_order_timing("NSE", dt)
        assert error is not None
        assert "PRE_MARKET" in error

    def test_mcx_valid_evening(self):
        dt = datetime(2026, 3, 12, 21, 0)
        assert validate_order_timing("MCX", dt) is None


# ── Exchange Hours Config Tests ──────────────────────────────

class TestExchangeHours:
    def test_all_exchanges_have_hours(self):
        for exchange in ["NSE", "BSE", "MCX", "NFO", "CDS"]:
            assert exchange in EXCHANGE_HOURS

    def test_nse_hours_correct(self):
        open_time, close_time = EXCHANGE_HOURS["NSE"]
        assert open_time == time(9, 15)
        assert close_time == time(15, 30)

    def test_mcx_hours_correct(self):
        open_time, close_time = EXCHANGE_HOURS["MCX"]
        assert open_time == time(9, 0)
        assert close_time == time(23, 30)
