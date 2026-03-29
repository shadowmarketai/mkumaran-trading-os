"""
Tests for Paper Trading Mode (Feature 1)

Validates:
- Paper order generates PAPER- IDs, skips Kite, tracks positions
- Kill switch, max positions, position sizing still enforced
- Cancel/close work in paper mode
- get_status shows paper_mode=True
"""

import pytest
from unittest.mock import patch

from mcp_server.order_manager import OrderManager, MAX_OPEN_POSITIONS


# All tests mock market hours and portfolio risk to isolate paper trading logic
_MOCK_TIMING = patch("mcp_server.order_manager.validate_order_timing", return_value=None)
_MOCK_RISK = patch("mcp_server.order_manager.validate_portfolio_risk", return_value=None)


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def paper_manager():
    """OrderManager in paper mode (no Kite)."""
    return OrderManager(kite=None, capital=100000, paper_mode=True)


@pytest.fixture
def live_manager():
    """OrderManager in live mode (no Kite connected)."""
    return OrderManager(kite=None, capital=100000, paper_mode=False)


# ── Paper Order ID Format ───────────────────────────────────────


@_MOCK_TIMING
@_MOCK_RISK
def test_paper_order_generates_paper_id(mock_risk, mock_timing, paper_manager):
    """Paper orders should generate PAPER-XXXXXX IDs."""
    result = paper_manager.place_order("NSE:RELIANCE", "BUY", qty=2, price=2500)
    assert result.success is True
    assert result.order_id.startswith("PAPER-")
    assert result.order_id == "PAPER-000001"


@_MOCK_TIMING
@_MOCK_RISK
def test_paper_order_increments_counter(mock_risk, mock_timing, paper_manager):
    """Each paper order should get a unique incrementing ID."""
    r1 = paper_manager.place_order("NSE:RELIANCE", "BUY", qty=2, price=2500)
    r2 = paper_manager.place_order("NSE:TCS", "BUY", qty=1, price=3000)
    assert r1.order_id == "PAPER-000001"
    assert r2.order_id == "PAPER-000002"


@_MOCK_TIMING
@_MOCK_RISK
def test_paper_order_message_prefix(mock_risk, mock_timing, paper_manager):
    """Paper order message should include [PAPER] prefix."""
    result = paper_manager.place_order("NSE:RELIANCE", "BUY", qty=2, price=2500)
    assert "[PAPER]" in result.message


# ── Kite Not Called ─────────────────────────────────────────────


@_MOCK_TIMING
@_MOCK_RISK
def test_paper_order_does_not_require_kite(mock_risk, mock_timing, paper_manager):
    """Paper mode should succeed even with kite=None."""
    assert paper_manager.kite is None
    result = paper_manager.place_order("NSE:RELIANCE", "BUY", qty=2, price=2500)
    assert result.success is True


def test_live_mode_fails_without_kite(live_manager):
    """Live mode should fail with kite=None."""
    result = live_manager.place_order("NSE:RELIANCE", "BUY", qty=2, price=2500)
    assert result.success is False
    assert "Kite not connected" in result.message


# ── Position Tracking ───────────────────────────────────────────


@_MOCK_TIMING
@_MOCK_RISK
def test_paper_order_tracks_position(mock_risk, mock_timing, paper_manager):
    """Paper orders should be tracked in open_positions."""
    paper_manager.place_order("NSE:RELIANCE", "BUY", qty=2, price=2500)
    assert len(paper_manager.open_positions) == 1
    pos = paper_manager.open_positions[0]
    assert pos["ticker"] == "NSE:RELIANCE"
    assert pos["direction"] == "BUY"
    assert pos["qty"] == 2
    assert pos["order_id"] == "PAPER-000001"


# ── Safety Controls Still Active ────────────────────────────────


@_MOCK_TIMING
@_MOCK_RISK
def test_paper_kill_switch_enforced(mock_risk, mock_timing, paper_manager):
    """Kill switch should still work in paper mode."""
    paper_manager.kill_switch.is_triggered = True
    paper_manager.kill_switch.trigger_reason = "Test trigger"
    result = paper_manager.place_order("NSE:RELIANCE", "BUY", qty=1, price=100)
    assert result.success is False
    assert "KILL SWITCH" in result.message


@_MOCK_TIMING
@_MOCK_RISK
def test_paper_max_positions_enforced(mock_risk, mock_timing, paper_manager):
    """Max positions limit should still work in paper mode."""
    for i in range(MAX_OPEN_POSITIONS):
        r = paper_manager.place_order(f"NSE:STOCK{i}", "BUY", qty=1, price=100)
        assert r.success is True

    result = paper_manager.place_order("NSE:OVERFLOW", "BUY", qty=1, price=100)
    assert result.success is False
    assert "Max positions" in result.message


@_MOCK_TIMING
@_MOCK_RISK
def test_paper_position_sizing_enforced(mock_risk, mock_timing, paper_manager):
    """Position size limit should still work in paper mode."""
    # 10% of 100000 = 10000 max value. 100 shares * 200 = 20000 > 10%
    result = paper_manager.place_order("NSE:RELIANCE", "BUY", qty=100, price=200)
    assert result.success is False
    assert "Position size" in result.message


# ── Cancel in Paper Mode ────────────────────────────────────────


@_MOCK_TIMING
@_MOCK_RISK
def test_paper_cancel_removes_position(mock_risk, mock_timing, paper_manager):
    """Cancel should remove the position in paper mode."""
    paper_manager.place_order("NSE:RELIANCE", "BUY", qty=2, price=2500)
    assert len(paper_manager.open_positions) == 1

    result = paper_manager.cancel_order("PAPER-000001")
    assert result.success is True
    assert "[PAPER]" in result.message
    assert len(paper_manager.open_positions) == 0


def test_paper_cancel_nonexistent_fails(paper_manager):
    """Cancel of non-existent order should fail."""
    result = paper_manager.cancel_order("PAPER-999999")
    assert result.success is False
    assert "not found" in result.message.lower()


# ── Close Position in Paper Mode ────────────────────────────────


@_MOCK_TIMING
@_MOCK_RISK
def test_paper_close_position(mock_risk, mock_timing, paper_manager):
    """Close position should work in paper mode, creating an opposite order."""
    paper_manager.place_order("NSE:RELIANCE", "BUY", qty=2, price=2500)
    result = paper_manager.close_position("NSE:RELIANCE")
    assert result.success is True
    assert result.order_id.startswith("PAPER-")


# ── get_status ──────────────────────────────────────────────────


def test_paper_status_shows_paper_mode(paper_manager):
    """get_status should include paper_mode=True."""
    status = paper_manager.get_status()
    assert status["paper_mode"] is True


def test_live_status_shows_not_paper_mode(live_manager):
    """get_status should include paper_mode=False for live mode."""
    status = live_manager.get_status()
    assert status["paper_mode"] is False


@_MOCK_TIMING
@_MOCK_RISK
def test_paper_status_has_order_id(mock_risk, mock_timing, paper_manager):
    """Positions in status should include order_id."""
    paper_manager.place_order("NSE:RELIANCE", "BUY", qty=2, price=2500)
    status = paper_manager.get_status()
    assert len(status["positions"]) == 1
    assert status["positions"][0]["order_id"] == "PAPER-000001"
