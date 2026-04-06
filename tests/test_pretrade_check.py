"""Tests for the pre-trade checklist module."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch, MagicMock

from mcp_server.models import Signal, MWAScore, ActiveTrade
from mcp_server.pretrade_check import (
    check_market_hours,
    check_active_positions,
    check_rrr,
    check_mwa_direction,
    check_ai_confidence,
    check_price_zone,
    check_fii_flow,
    check_news_impact,
    check_delivery_pct,
    check_sector_strength,
    run_pretrade_checks,
)


def _make_signal(**overrides):
    """Create a test Signal object with sensible defaults."""
    defaults = {
        "id": 1,
        "signal_date": date.today(),
        "ticker": "RELIANCE",
        "exchange": "NSE",
        "asset_class": "EQUITY",
        "direction": "LONG",
        "pattern": "MWA Scan",
        "entry_price": Decimal("2500.00"),
        "stop_loss": Decimal("2400.00"),
        "target": Decimal("2800.00"),
        "rrr": Decimal("3.0"),
        "qty": 10,
        "risk_amt": Decimal("1000.00"),
        "ai_confidence": 72,
        "tv_confirmed": True,
        "mwa_score": "BULL",
        "scanner_count": 5,
        "tier": 1,
        "source": "mwa_scan",
        "timeframe": "1D",
        "status": "OPEN",
    }
    defaults.update(overrides)
    sig = Signal()
    for k, v in defaults.items():
        setattr(sig, k, v)
    return sig


def _make_mwa(**overrides):
    """Create a test MWAScore object."""
    defaults = {
        "id": 1,
        "score_date": date.today(),
        "direction": "BULL",
        "bull_score": Decimal("65.0"),
        "bear_score": Decimal("35.0"),
        "bull_pct": Decimal("65.0"),
        "bear_pct": Decimal("35.0"),
        "fii_net": Decimal("500.00"),
        "dii_net": Decimal("800.00"),
        "sector_strength": {"IT": "STRONG", "PHARMA": "NEUTRAL", "AUTO": "WEAK"},
    }
    defaults.update(overrides)
    mwa = MWAScore()
    for k, v in defaults.items():
        setattr(mwa, k, v)
    return mwa


# ── Check 1: Market Hours ────────────────────────────────────

@patch("mcp_server.pretrade_check.check_market_hours.__module__", "mcp_server.pretrade_check")
class TestMarketHours:
    @patch("mcp_server.market_calendar.get_market_status")
    def test_market_open(self, mock_status):
        mock_status.return_value = {"is_open": True, "reason": "OPEN"}
        sig = _make_signal()
        result = check_market_hours(sig)
        assert result["status"] == "PASS"

    @patch("mcp_server.market_calendar.get_market_status")
    def test_market_closed(self, mock_status):
        mock_status.return_value = {"is_open": False, "reason": "WEEKEND"}
        sig = _make_signal()
        result = check_market_hours(sig)
        assert result["status"] == "FAIL"


# ── Check 2: Active Positions ────────────────────────────────

class TestActivePositions:
    def test_under_limit(self, db_session):
        result = check_active_positions(db_session)
        assert result["status"] == "PASS"
        assert "0/5" in result["detail"]

    def test_at_limit(self, db_session):
        for i in range(5):
            t = ActiveTrade()
            t.ticker = f"STOCK{i}"
            t.entry_price = Decimal("100")
            db_session.add(t)
        db_session.flush()
        result = check_active_positions(db_session)
        assert result["status"] == "FAIL"


# ── Check 3: RRR ─────────────────────────────────────────────

class TestRRR:
    def test_equity_pass(self):
        sig = _make_signal(rrr=Decimal("3.5"))
        result = check_rrr(sig)
        assert result["status"] == "PASS"

    def test_equity_fail(self):
        sig = _make_signal(rrr=Decimal("2.0"))
        result = check_rrr(sig)
        assert result["status"] == "FAIL"

    def test_equity_warn(self):
        sig = _make_signal(rrr=Decimal("2.5"))
        result = check_rrr(sig)
        assert result["status"] == "WARN"

    def test_mcx_lower_threshold(self):
        sig = _make_signal(exchange="MCX", rrr=Decimal("2.0"))
        result = check_rrr(sig)
        assert result["status"] == "PASS"


# ── Check 4: MWA Direction ───────────────────────────────────

class TestMWADirection:
    def test_aligned_long_bull(self, db_session):
        mwa = _make_mwa(direction="BULL")
        db_session.add(mwa)
        db_session.flush()
        sig = _make_signal(direction="LONG")
        result = check_mwa_direction(sig, db_session)
        assert result["status"] == "PASS"

    def test_opposing_long_bear(self, db_session):
        mwa = _make_mwa(direction="BEAR")
        db_session.add(mwa)
        db_session.flush()
        sig = _make_signal(direction="LONG")
        result = check_mwa_direction(sig, db_session)
        assert result["status"] == "FAIL"

    def test_sideways_warn(self, db_session):
        mwa = _make_mwa(direction="SIDEWAYS")
        db_session.add(mwa)
        db_session.flush()
        sig = _make_signal(direction="LONG")
        result = check_mwa_direction(sig, db_session)
        assert result["status"] == "WARN"

    def test_no_mwa_data(self, db_session):
        sig = _make_signal()
        result = check_mwa_direction(sig, db_session)
        assert result["status"] == "WARN"


# ── Check 5: AI Confidence ───────────────────────────────────

class TestAIConfidence:
    def test_high_confidence(self):
        sig = _make_signal(ai_confidence=75)
        assert check_ai_confidence(sig)["status"] == "PASS"

    def test_borderline(self):
        sig = _make_signal(ai_confidence=40)
        assert check_ai_confidence(sig)["status"] == "WARN"

    def test_low_confidence(self):
        sig = _make_signal(ai_confidence=20)
        assert check_ai_confidence(sig)["status"] == "FAIL"


# ── Check 6: Price Zone ─────────────────────────────────────

class TestPriceZone:
    @patch("mcp_server.data_provider.get_stock_data")
    def test_within_zone(self, mock_data):
        import pandas as pd
        mock_data.return_value = pd.DataFrame({"close": [2510.0]})
        sig = _make_signal(entry_price=Decimal("2500.00"))
        result = check_price_zone(sig)
        assert result["status"] == "PASS"

    @patch("mcp_server.data_provider.get_stock_data")
    def test_outside_zone(self, mock_data):
        import pandas as pd
        mock_data.return_value = pd.DataFrame({"close": [2700.0]})
        sig = _make_signal(entry_price=Decimal("2500.00"))
        result = check_price_zone(sig)
        assert result["status"] == "FAIL"

    @patch("mcp_server.data_provider.get_stock_data")
    def test_warn_zone(self, mock_data):
        import pandas as pd
        mock_data.return_value = pd.DataFrame({"close": [2580.0]})
        sig = _make_signal(entry_price=Decimal("2500.00"))
        result = check_price_zone(sig)
        assert result["status"] == "WARN"


# ── Check 7: FII Flow ───────────────────────────────────────

class TestFIIFlow:
    def test_fii_positive(self, db_session):
        mwa = _make_mwa(fii_net=Decimal("500"))
        db_session.add(mwa)
        db_session.flush()
        sig = _make_signal(direction="LONG")
        result = check_fii_flow(sig, db_session)
        assert result["status"] == "PASS"

    def test_fii_heavy_selling(self, db_session):
        mwa = _make_mwa(fii_net=Decimal("-3000"))
        db_session.add(mwa)
        db_session.flush()
        sig = _make_signal(direction="LONG")
        result = check_fii_flow(sig, db_session)
        assert result["status"] == "FAIL"

    def test_fii_moderate_selling(self, db_session):
        mwa = _make_mwa(fii_net=Decimal("-1500"))
        db_session.add(mwa)
        db_session.flush()
        sig = _make_signal(direction="LONG")
        result = check_fii_flow(sig, db_session)
        assert result["status"] == "WARN"

    def test_fii_short_direction(self, db_session):
        mwa = _make_mwa(fii_net=Decimal("-3000"))
        db_session.add(mwa)
        db_session.flush()
        sig = _make_signal(direction="SHORT")
        result = check_fii_flow(sig, db_session)
        assert result["status"] == "PASS"


# ── Check 8: News Impact ────────────────────────────────────

class TestNewsImpact:
    @patch("mcp_server.news_monitor.get_latest_news")
    def test_no_high_news(self, mock_news):
        mock_news.return_value = []
        sig = _make_signal()
        result = check_news_impact(sig)
        assert result["status"] == "PASS"

    @patch("mcp_server.news_monitor.get_latest_news")
    def test_high_news_present(self, mock_news):
        item = MagicMock()
        item.title = "RBI Rate Decision"
        mock_news.return_value = [item]
        sig = _make_signal()
        result = check_news_impact(sig)
        assert result["status"] == "WARN"


# ── Check 9: Delivery % ─────────────────────────────────────

class TestDeliveryPct:
    @patch("mcp_server.delivery_filter.get_delivery_data")
    def test_high_delivery(self, mock_data):
        mock_data.return_value = {"RELIANCE": 55.0}
        sig = _make_signal(ticker="RELIANCE", exchange="NSE", asset_class="EQUITY")
        result = check_delivery_pct(sig)
        assert result["status"] == "PASS"

    @patch("mcp_server.delivery_filter.get_delivery_data")
    def test_low_delivery(self, mock_data):
        mock_data.return_value = {"RELIANCE": 25.0}
        sig = _make_signal(ticker="RELIANCE", exchange="NSE", asset_class="EQUITY")
        result = check_delivery_pct(sig)
        assert result["status"] == "WARN"

    def test_non_equity_skip(self):
        sig = _make_signal(exchange="MCX", asset_class="COMMODITY")
        result = check_delivery_pct(sig)
        assert result["status"] == "PASS"
        assert "Not applicable" in result["detail"]


# ── Check 10: Sector Strength ────────────────────────────────

class TestSectorStrength:
    def test_balanced_sectors(self, db_session):
        mwa = _make_mwa(sector_strength={"IT": "STRONG", "PHARMA": "STRONG", "AUTO": "WEAK"})
        db_session.add(mwa)
        db_session.flush()
        sig = _make_signal(direction="LONG")
        result = check_sector_strength(sig, db_session)
        assert result["status"] == "PASS"

    def test_weak_majority_for_long(self, db_session):
        mwa = _make_mwa(sector_strength={"IT": "WEAK", "PHARMA": "WEAK", "AUTO": "STRONG"})
        db_session.add(mwa)
        db_session.flush()
        sig = _make_signal(direction="LONG")
        result = check_sector_strength(sig, db_session)
        assert result["status"] == "WARN"


# ── Overall Verdict ──────────────────────────────────────────

class TestOverallVerdict:
    @patch("mcp_server.pretrade_check.check_market_hours")
    @patch("mcp_server.pretrade_check.check_active_positions")
    @patch("mcp_server.pretrade_check.check_rrr")
    @patch("mcp_server.pretrade_check.check_mwa_direction")
    @patch("mcp_server.pretrade_check.check_ai_confidence")
    @patch("mcp_server.pretrade_check.check_price_zone")
    @patch("mcp_server.pretrade_check.check_fii_flow")
    @patch("mcp_server.pretrade_check.check_news_impact")
    @patch("mcp_server.pretrade_check.check_delivery_pct")
    @patch("mcp_server.pretrade_check.check_sector_strength")
    def test_all_pass_go(self, *mocks):
        for m in mocks:
            m.return_value = {"name": "Test", "status": "PASS", "detail": "ok"}
        sig = _make_signal()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = sig
        result = run_pretrade_checks(1, db)
        assert result["verdict"] == "GO"
        assert result["pass_count"] == 10

    @patch("mcp_server.pretrade_check.check_market_hours")
    @patch("mcp_server.pretrade_check.check_active_positions")
    @patch("mcp_server.pretrade_check.check_rrr")
    @patch("mcp_server.pretrade_check.check_mwa_direction")
    @patch("mcp_server.pretrade_check.check_ai_confidence")
    @patch("mcp_server.pretrade_check.check_price_zone")
    @patch("mcp_server.pretrade_check.check_fii_flow")
    @patch("mcp_server.pretrade_check.check_news_impact")
    @patch("mcp_server.pretrade_check.check_delivery_pct")
    @patch("mcp_server.pretrade_check.check_sector_strength")
    def test_any_fail_block(self, *mocks):
        for m in mocks:
            m.return_value = {"name": "Test", "status": "PASS", "detail": "ok"}
        # First mock (sector_strength, last positional) returns FAIL
        mocks[0].return_value = {"name": "Sector", "status": "FAIL", "detail": "bad"}
        sig = _make_signal()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = sig
        result = run_pretrade_checks(1, db)
        assert result["verdict"] == "BLOCK"
        assert result["fail_count"] >= 1

    @patch("mcp_server.pretrade_check.check_market_hours")
    @patch("mcp_server.pretrade_check.check_active_positions")
    @patch("mcp_server.pretrade_check.check_rrr")
    @patch("mcp_server.pretrade_check.check_mwa_direction")
    @patch("mcp_server.pretrade_check.check_ai_confidence")
    @patch("mcp_server.pretrade_check.check_price_zone")
    @patch("mcp_server.pretrade_check.check_fii_flow")
    @patch("mcp_server.pretrade_check.check_news_impact")
    @patch("mcp_server.pretrade_check.check_delivery_pct")
    @patch("mcp_server.pretrade_check.check_sector_strength")
    def test_warn_only_caution(self, *mocks):
        for m in mocks:
            m.return_value = {"name": "Test", "status": "PASS", "detail": "ok"}
        mocks[0].return_value = {"name": "Sector", "status": "WARN", "detail": "caution"}
        sig = _make_signal()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = sig
        result = run_pretrade_checks(1, db)
        assert result["verdict"] == "CAUTION"
        assert result["warn_count"] >= 1

    def test_signal_not_found(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        result = run_pretrade_checks(999, db)
        assert result["verdict"] == "BLOCK"
        assert "not found" in result.get("error", "")
