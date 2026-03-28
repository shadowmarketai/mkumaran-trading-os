"""Tests for OrderManager — trailing SL, partial exit, market hours, portfolio risk."""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, time, date

from mcp_server.order_manager import (
    OrderManager,
    OrderResult,
    KillSwitchState,
    MAX_OPEN_POSITIONS,
    DAILY_LOSS_LIMIT_PCT,
    MAX_POSITION_SIZE_PCT,
    MAX_ORDER_VALUE,
    DEFAULT_TRAIL_PCT,
    DEFAULT_TRAIL_ACTIVATION_PCT,
)


# ── Fixtures ─────────────────────────────────────────────────

@pytest.fixture
def manager():
    """OrderManager with mock Kite and 5L capital."""
    kite = MagicMock()
    kite.place_order.return_value = "ORD-12345"
    m = OrderManager(kite=kite, capital=500000)
    return m


@pytest.fixture
def manager_with_position(manager):
    """Manager with one open LONG position."""
    manager.open_positions.append({
        "order_id": "ORD-001",
        "ticker": "NSE:RELIANCE",
        "direction": "BUY",
        "qty": 10,
        "entry_price": 2500.0,
        "stop_loss": 2400.0,
        "target": 2800.0,
        "timestamp": "2026-01-15T10:00:00",
        "tag": "test",
    })
    return manager


@pytest.fixture
def manager_with_short(manager):
    """Manager with one open SHORT position."""
    manager.open_positions.append({
        "order_id": "ORD-002",
        "ticker": "NSE:TATAMOTORS",
        "direction": "SELL",
        "qty": 20,
        "entry_price": 600.0,
        "stop_loss": 630.0,
        "target": 540.0,
        "timestamp": "2026-01-15T10:00:00",
        "tag": "test",
    })
    return manager


# ── Basic Order Tests ────────────────────────────────────────

class TestBasicOrders:
    def test_no_kite_blocks_order(self):
        m = OrderManager(kite=None, capital=100000)
        result = m.place_order("NSE:RELIANCE", "BUY", qty=10, price=2500)
        assert not result.success
        assert "Kite not connected" in result.message

    @patch("mcp_server.order_manager.validate_order_timing", return_value=None)
    @patch("mcp_server.order_manager.validate_portfolio_risk", return_value=None)
    def test_place_order_success(self, mock_risk, mock_timing, manager):
        result = manager.place_order("NSE:RELIANCE", "BUY", qty=5, price=2500)
        assert result.success
        assert result.order_id == "ORD-12345"
        assert len(manager.open_positions) == 1

    def test_max_positions_enforced(self, manager):
        for i in range(MAX_OPEN_POSITIONS):
            manager.open_positions.append({"ticker": f"T{i}", "qty": 1, "entry_price": 100})
        result = manager.place_order("NSE:NEW", "BUY", qty=1, price=100)
        assert not result.success
        assert "Max positions" in result.message

    def test_invalid_direction(self, manager):
        result = manager.place_order("NSE:RELIANCE", "HOLD", qty=5, price=2500)
        assert not result.success
        assert "Invalid direction" in result.message

    def test_max_order_value(self, manager):
        result = manager.place_order("NSE:RELIANCE", "BUY", qty=100, price=3000)
        assert not result.success
        assert "exceeds max" in result.message

    def test_position_size_limit(self, manager):
        # 10% of 500000 = 50000. 30 shares at 2500 = 75000 > 50000
        result = manager.place_order("NSE:RELIANCE", "BUY", qty=30, price=2500)
        assert not result.success
        assert "Position size" in result.message

    def test_invalid_exchange(self, manager):
        result = manager.place_order("FOREX:EURUSD", "BUY", qty=1, price=100)
        assert not result.success
        assert "not allowed" in result.message


# ── Kill Switch Tests ────────────────────────────────────────

class TestKillSwitch:
    def test_kill_switch_triggers_on_loss(self):
        ks = KillSwitchState(starting_capital=100000)
        ks.realized_pnl = -3100  # -3.1%
        assert ks.check(100000) is True
        assert ks.is_triggered

    def test_kill_switch_not_triggered_on_small_loss(self):
        ks = KillSwitchState(starting_capital=100000)
        ks.realized_pnl = -2000  # -2%
        assert ks.check(100000) is False
        assert not ks.is_triggered

    def test_kill_switch_resets_on_new_day(self):
        ks = KillSwitchState(starting_capital=100000)
        ks.realized_pnl = -3100
        ks.check(100000)
        assert ks.is_triggered

        # Simulate new day
        ks.date = date(2020, 1, 1)
        ks.check(100000)
        assert not ks.is_triggered

    def test_kill_switch_blocks_order(self, manager):
        manager.kill_switch.realized_pnl = -20000  # -4% of 500k
        manager.kill_switch.check(500000)
        result = manager.place_order("NSE:RELIANCE", "BUY", qty=1, price=100)
        assert not result.success
        assert "KILL SWITCH" in result.message


# ── Trailing Stop Loss Tests ─────────────────────────────────

class TestTrailingSL:
    def test_trail_not_active_below_activation(self, manager_with_position):
        # Entry 2500, activation at 3% = 2575. Current 2550 = +2%
        result = manager_with_position.update_trailing_sl("NSE:RELIANCE", 2550.0)
        assert not result["updated"]
        assert "not active" in result["message"]

    def test_trail_activates_and_moves_sl(self, manager_with_position):
        # Entry 2500, activation at 3% = 2575. Current 2600 = +4%
        result = manager_with_position.update_trailing_sl("NSE:RELIANCE", 2600.0)
        assert result["updated"]
        # New SL = 2600 * (1 - 0.02) = 2548
        assert result["new_sl"] == 2548.0
        assert result["old_sl"] == 2400.0

    def test_trail_only_moves_up(self, manager_with_position):
        # First: trail to 2548
        manager_with_position.update_trailing_sl("NSE:RELIANCE", 2600.0)
        # Then: price dips to 2580, SL should NOT move down
        result = manager_with_position.update_trailing_sl("NSE:RELIANCE", 2580.0)
        assert not result["updated"]
        assert "already tighter" in result["message"]

    def test_trail_moves_higher_on_new_high(self, manager_with_position):
        # Trail to 2548
        manager_with_position.update_trailing_sl("NSE:RELIANCE", 2600.0)
        # New high: 2700. SL should move to 2700 * 0.98 = 2646
        result = manager_with_position.update_trailing_sl("NSE:RELIANCE", 2700.0)
        assert result["updated"]
        assert result["new_sl"] == 2646.0

    def test_trail_short_position(self, manager_with_short):
        # SHORT entry 600, SL 630, current 570 = +5% profit
        result = manager_with_short.update_trailing_sl("NSE:TATAMOTORS", 570.0)
        assert result["updated"]
        # New SL = 570 * (1 + 0.02) = 581.4
        assert result["new_sl"] == 581.40

    def test_trail_short_only_moves_down(self, manager_with_short):
        # First trail
        manager_with_short.update_trailing_sl("NSE:TATAMOTORS", 570.0)
        # Price goes up (bad for short), SL should NOT move up
        result = manager_with_short.update_trailing_sl("NSE:TATAMOTORS", 585.0)
        assert not result["updated"]

    def test_trail_nonexistent_position(self, manager):
        result = manager.update_trailing_sl("NSE:DOESNTEXIST", 100.0)
        assert not result["updated"]

    def test_custom_trail_pct(self, manager_with_position):
        # 1% trail, 2% activation
        result = manager_with_position.update_trailing_sl(
            "NSE:RELIANCE", 2600.0, trail_pct=0.01, activation_pct=0.02,
        )
        assert result["updated"]
        # 2600 * 0.99 = 2574
        assert result["new_sl"] == 2574.0


# ── SL Hit Check Tests ───────────────────────────────────────

class TestSLHitCheck:
    def test_sl_hit_long(self, manager_with_position):
        result = manager_with_position.check_sl_hit("NSE:RELIANCE", 2390.0)
        assert result["hit"]
        assert result["action"] == "CLOSE"

    def test_sl_not_hit_long(self, manager_with_position):
        result = manager_with_position.check_sl_hit("NSE:RELIANCE", 2500.0)
        assert not result["hit"]
        assert result["action"] == "HOLD"

    def test_sl_hit_short(self, manager_with_short):
        result = manager_with_short.check_sl_hit("NSE:TATAMOTORS", 635.0)
        assert result["hit"]
        assert result["action"] == "CLOSE"


# ── Partial Exit Tests ───────────────────────────────────────

class TestPartialExit:
    @patch("mcp_server.order_manager.validate_order_timing", return_value=None)
    @patch("mcp_server.order_manager.validate_portfolio_risk", return_value=None)
    def test_partial_exit_50pct(self, mock_risk, mock_timing, manager_with_position):
        result = manager_with_position.partial_exit("NSE:RELIANCE", exit_pct=0.50)
        assert result.success
        # Started with 10, sold 5, remaining 5
        pos = manager_with_position.open_positions[0]
        assert pos["qty"] == 5
        assert pos["partial_exits"] == 1

    def test_partial_exit_nonexistent(self, manager):
        result = manager.partial_exit("NSE:DOESNTEXIST")
        assert not result.success

    def test_partial_exit_invalid_pct(self, manager_with_position):
        result = manager_with_position.partial_exit("NSE:RELIANCE", exit_pct=0.0)
        assert not result.success

    def test_partial_exit_full_blocked(self, manager_with_position):
        # 100% would exit entire position — should be blocked
        result = manager_with_position.partial_exit("NSE:RELIANCE", exit_pct=1.0)
        assert not result.success


# ── Exit Strategy Tests ──────────────────────────────────────

class TestExitStrategy:
    def test_in_loss_hold(self, manager_with_position):
        result = manager_with_position.evaluate_exit_strategy("NSE:RELIANCE", 2450.0)
        assert result["action"] == "HOLD"
        assert result["profit_pct"] < 0

    def test_small_profit_hold(self, manager_with_position):
        result = manager_with_position.evaluate_exit_strategy("NSE:RELIANCE", 2540.0)
        assert result["action"] == "HOLD"

    def test_trail_zone(self, manager_with_position):
        result = manager_with_position.evaluate_exit_strategy("NSE:RELIANCE", 2600.0)
        assert result["action"] == "TRAIL"

    def test_partial_50_zone(self, manager_with_position):
        result = manager_with_position.evaluate_exit_strategy("NSE:RELIANCE", 2660.0)
        assert result["action"] == "PARTIAL_50"

    def test_partial_25_zone(self, manager_with_position):
        result = manager_with_position.evaluate_exit_strategy("NSE:RELIANCE", 2720.0)
        assert result["action"] in ("PARTIAL_25", "PARTIAL_50")

    def test_nonexistent_position(self, manager):
        result = manager.evaluate_exit_strategy("NSE:DOESNTEXIST", 100.0)
        assert result["action"] == "NONE"


# ── Status Tests ─────────────────────────────────────────────

class TestStatus:
    def test_status_includes_trail_info(self, manager_with_position):
        manager_with_position.update_trailing_sl("NSE:RELIANCE", 2600.0)
        status = manager_with_position.get_status()
        pos = status["positions"][0]
        assert "trail_active" in pos
        assert "stop_loss" in pos
        assert "partial_exits" in pos

    def test_status_empty(self, manager):
        status = manager.get_status()
        assert status["open_positions"] == 0
        assert status["capital"] == 500000
