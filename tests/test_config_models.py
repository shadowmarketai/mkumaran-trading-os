"""Tests for Config and Database Models."""

from mcp_server.config import Settings, settings


# ── Config ────────────────────────────────────────────────────

def test_settings_instance():
    assert isinstance(settings, Settings)


def test_settings_defaults():
    s = Settings()
    assert s.MCP_SERVER_PORT == 8001
    assert s.RRMS_CAPITAL == 100000
    assert s.RRMS_RISK_PCT == 0.02
    assert s.RRMS_MIN_RRR == 3.0


def test_settings_database_url_exists():
    s = Settings()
    assert len(s.DATABASE_URL) > 0


def test_settings_host_default():
    s = Settings()
    assert s.MCP_SERVER_HOST == "0.0.0.0"


# ── Models (import and instantiate without DB) ────────────────

def test_watchlist_model_import():
    from mcp_server.models import Watchlist
    item = Watchlist(ticker="NSE:RELIANCE", tier=2, active=True, source="test", added_by="system")
    assert item.ticker == "NSE:RELIANCE"
    assert item.tier == 2
    assert item.active is True


def test_signal_model_import():
    from mcp_server.models import Signal
    sig = Signal(
        ticker="NSE:SBIN", direction="LONG", pattern="Double Bottom",
        entry_price=600, stop_loss=590, target=630, rrr=4.0,
        qty=20, risk_amt=200, ai_confidence=75,
        mwa_score="BULL", scanner_count=12, tier=3, source="MWA",
    )
    assert sig.direction == "LONG"
    assert sig.rrr == 4.0


def test_outcome_model_import():
    from mcp_server.models import Outcome
    o = Outcome(signal_id=1, exit_price=650, outcome="WIN", pnl_amount=500, days_held=5, exit_reason="TARGET")
    assert o.outcome == "WIN"
    assert o.exit_reason == "TARGET"


def test_active_trade_model_import():
    from mcp_server.models import ActiveTrade
    t = ActiveTrade(
        signal_id=1, ticker="NSE:TCS", entry_price=3500,
        target=3800, stop_loss=3400, prrr=3.0,
    )
    assert t.ticker == "NSE:TCS"
    assert t.prrr == 3.0


def test_mwa_score_model_import():
    from mcp_server.models import MWAScore
    m = MWAScore(
        direction="BULL", bull_score=65, bear_score=20,
        bull_pct=65.0, bear_pct=20.0, fii_net=1500, dii_net=800,
    )
    assert m.direction == "BULL"
    assert m.fii_net == 1500
