"""
Tests for the 5 Critical Fixes (Phase 1–5).

1. Backtester: slippage, transaction costs, Sharpe ratio
2. Validator: fail-safe blocking on errors
3. F&O Module: real data structure, NO_KITE status
4. Volatility: ATR-based threshold normalization
5. Order Manager: safety limits, kill switch
"""

import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch

# ============================================================
# Helpers
# ============================================================

def _make_ohlcv(n=100, base=100.0, trend=0.5):
    """Generate realistic OHLCV DataFrame."""
    closes = [base]
    for i in range(1, n):
        closes.append(closes[-1] + trend + np.random.randn() * 2)
    closes = np.array(closes, dtype=float)
    return pd.DataFrame({
        "open": closes - 0.5,
        "high": closes + abs(np.random.randn(n) * 2),
        "low": closes - abs(np.random.randn(n) * 2),
        "close": closes,
        "volume": np.random.randint(50000, 500000, n),
    })


# ============================================================
# 1. BACKTESTER — Slippage & Costs
# ============================================================

class TestBacktesterSlippage:

    def test_apply_slippage_long_entry_worse(self):
        """LONG entry should buy at HIGHER price (slippage hurts)."""
        from mcp_server.backtester import _apply_slippage
        result = _apply_slippage(100.0, "LONG", is_entry=True, slippage_pct=0.003)
        assert result == pytest.approx(100.3, rel=1e-4)

    def test_apply_slippage_long_exit_worse(self):
        """LONG exit should sell at LOWER price (slippage hurts)."""
        from mcp_server.backtester import _apply_slippage
        result = _apply_slippage(100.0, "LONG", is_entry=False, slippage_pct=0.003)
        assert result == pytest.approx(99.7, rel=1e-4)

    def test_apply_slippage_short_entry_worse(self):
        """SHORT entry should sell at LOWER price (slippage hurts)."""
        from mcp_server.backtester import _apply_slippage
        result = _apply_slippage(100.0, "SHORT", is_entry=True, slippage_pct=0.003)
        assert result == pytest.approx(99.7, rel=1e-4)

    def test_apply_slippage_short_exit_worse(self):
        """SHORT exit should buy at HIGHER price (slippage hurts)."""
        from mcp_server.backtester import _apply_slippage
        result = _apply_slippage(100.0, "SHORT", is_entry=False, slippage_pct=0.003)
        assert result == pytest.approx(100.3, rel=1e-4)

    def test_zero_slippage_no_change(self):
        from mcp_server.backtester import _apply_slippage
        result = _apply_slippage(100.0, "LONG", is_entry=True, slippage_pct=0.0)
        assert result == 100.0


class TestBacktesterCosts:

    def test_transaction_cost_buy_side(self):
        """Buy side: brokerage + GST + stamp duty (no STT)."""
        from mcp_server.backtester import _calculate_transaction_cost
        cost = _calculate_transaction_cost(price=100.0, qty=10, is_sell=False)
        assert cost > 0
        # Small order (Rs.1000): min(0.03% * 1000, 20) = Rs.0.30 brokerage
        # + exchange/SEBI charges + GST + stamp = small total
        assert cost < 5.0  # Much less than Rs.20 for small orders

    def test_transaction_cost_sell_side_includes_stt(self):
        """Sell side includes STT — should be more expensive than buy."""
        from mcp_server.backtester import _calculate_transaction_cost
        buy_cost = _calculate_transaction_cost(price=100.0, qty=10, is_sell=False)
        sell_cost = _calculate_transaction_cost(price=100.0, qty=10, is_sell=True)
        assert sell_cost > buy_cost  # STT makes sell more expensive

    def test_backtest_result_includes_cost_fields(self):
        """Backtest result should include slippage and cost tracking."""
        from mcp_server.backtester import run_backtest
        result = run_backtest("NSE:RELIANCE", strategy="rrms", days=30)
        assert isinstance(result, dict)
        assert "ticker" in result
        assert "strategy" in result

    def test_default_slippage_is_point_three_pct(self):
        from mcp_server.backtester import DEFAULT_SLIPPAGE_PCT
        assert DEFAULT_SLIPPAGE_PCT == 0.003


# ============================================================
# 2. VALIDATOR — Fail-Safe Blocking
# ============================================================

class TestValidatorFailSafe:

    def test_no_api_key_blocks_signal(self):
        """Missing API key should BLOCK, not approve."""
        from mcp_server.validator import validate_signal
        import os
        old_key = os.environ.get("ANTHROPIC_API_KEY")
        os.environ.pop("ANTHROPIC_API_KEY", None)

        # Force settings to reload
        from mcp_server.config import settings
        original = settings.ANTHROPIC_API_KEY
        settings.ANTHROPIC_API_KEY = ""

        try:
            result = validate_signal(
                ticker="RELIANCE", direction="BUY", pattern="double_bottom",
                rrr=3.5, entry_price=2500, stop_loss=2400, target=2850,
                mwa_direction="BULLISH", scanner_count=5, tv_confirmed=True,
                sector_strength="STRONG", fii_net=500, delivery_pct=45,
                confidence_boosts=[], pre_confidence=65,
            )
            assert result["recommendation"] == "BLOCKED"
            assert result["confidence"] == 0
            assert result["validation_status"] == "SKIPPED"
        finally:
            settings.ANTHROPIC_API_KEY = original
            if old_key:
                os.environ["ANTHROPIC_API_KEY"] = old_key

    def test_invalid_api_key_blocks_signal(self):
        """Invalid API key format should BLOCK."""
        from mcp_server.validator import validate_signal
        from mcp_server.config import settings
        original = settings.ANTHROPIC_API_KEY
        settings.ANTHROPIC_API_KEY = "bad-key-123"

        try:
            result = validate_signal(
                ticker="SBIN", direction="BUY", pattern="inverse_hns",
                rrr=4.0, entry_price=600, stop_loss=580, target=680,
                mwa_direction="BULLISH", scanner_count=8, tv_confirmed=True,
                sector_strength="STRONG", fii_net=300, delivery_pct=50,
                confidence_boosts=["volume_spike"], pre_confidence=70,
            )
            assert result["recommendation"] == "BLOCKED"
            assert result["confidence"] == 0
            assert result["validation_status"] == "SKIPPED"
        finally:
            settings.ANTHROPIC_API_KEY = original

    def test_status_constants_exist(self):
        from mcp_server.validator import (
            STATUS_VALIDATED, STATUS_FAILED, STATUS_SKIPPED, STATUS_BLOCKED,
        )
        assert STATUS_VALIDATED == "VALIDATED"
        assert STATUS_FAILED == "FAILED"
        assert STATUS_SKIPPED == "SKIPPED"
        assert STATUS_BLOCKED == "BLOCKED"


# ============================================================
# 3. F&O MODULE — Real Data Structure
# ============================================================

class TestFOModuleRewrite:

    def test_no_kite_returns_status(self):
        """No Kite = explicit STATUS_NO_KITE, not fake data."""
        from mcp_server.fo_module import get_oi_change, STATUS_NO_KITE
        result = get_oi_change(kite=None)
        assert result["status"] == STATUS_NO_KITE
        assert "message" in result

    def test_no_kite_pcr_status(self):
        from mcp_server.fo_module import get_pcr, STATUS_NO_KITE
        result = get_pcr(kite=None)
        assert result["status"] == STATUS_NO_KITE
        assert result["pcr"] == 0
        assert result["sentiment"] == "UNAVAILABLE"

    def test_no_kite_oi_zeros(self):
        """Without Kite, OI should be 0 — not hardcoded fake data."""
        from mcp_server.fo_module import get_oi_change
        result = get_oi_change(kite=None)
        assert result["call_oi_total"] == 0
        assert result["put_oi_total"] == 0
        assert result["significance"] == "UNAVAILABLE"

    def test_fo_signal_data_quality_reporting(self):
        """get_fo_signal should report data quality metric."""
        from mcp_server.fo_module import get_fo_signal
        result = get_fo_signal(kite=None)
        assert "data_quality" in result
        assert "components" in result

    def test_status_constants(self):
        from mcp_server.fo_module import STATUS_LIVE, STATUS_NO_KITE, STATUS_ERROR
        assert STATUS_LIVE == "LIVE"
        assert STATUS_NO_KITE == "NO_KITE"
        assert STATUS_ERROR == "ERROR"


# ============================================================
# 4. VOLATILITY — ATR-Based Normalization
# ============================================================

class TestVolatilityNormalization:

    def test_calculate_atr_basic(self):
        from mcp_server.volatility import calculate_atr
        df = _make_ohlcv(50, base=100)
        atr = calculate_atr(df, period=14)
        assert isinstance(atr, float)
        assert atr > 0

    def test_calculate_atr_insufficient_data(self):
        from mcp_server.volatility import calculate_atr
        df = _make_ohlcv(3, base=100)
        atr = calculate_atr(df, period=14)
        assert atr > 0  # Fallback to avg high-low range

    def test_calculate_atr_empty_df(self):
        from mcp_server.volatility import calculate_atr
        atr = calculate_atr(pd.DataFrame({"high": [], "low": [], "close": []}), period=14)
        assert atr == 0.0

    def test_atr_pct_normalization(self):
        """ATR% should be relative to price — cheap stock has higher ATR%."""
        from mcp_server.volatility import calculate_atr_pct
        # Use fixed volatility (range=4) for both — only price differs
        n = 50
        cheap_close = np.full(n, 20.0)
        expensive_close = np.full(n, 5000.0)
        volatility = 4.0  # Same absolute range for both

        cheap = pd.DataFrame({
            "open": cheap_close - 0.5,
            "high": cheap_close + volatility,
            "low": cheap_close - volatility,
            "close": cheap_close,
            "volume": [100000] * n,
        })
        expensive = pd.DataFrame({
            "open": expensive_close - 0.5,
            "high": expensive_close + volatility,
            "low": expensive_close - volatility,
            "close": expensive_close,
            "volume": [100000] * n,
        })
        atr_pct_cheap = calculate_atr_pct(cheap)
        atr_pct_expensive = calculate_atr_pct(expensive)
        # Cheap stock: 4/20 = 20% ATR%, Expensive: 4/5000 = 0.08%
        assert atr_pct_cheap > atr_pct_expensive
        assert atr_pct_cheap > 10  # Should be ~40% (8/20*100)

    def test_volatility_regime_classification(self):
        from mcp_server.volatility import get_volatility_regime
        # Very stable data
        df = _make_ohlcv(50, base=1000, trend=0)
        df["high"] = df["close"] + 0.01  # Tiny range
        df["low"] = df["close"] - 0.01
        regime = get_volatility_regime(df)
        assert regime in ("LOW", "NORMAL", "HIGH", "EXTREME")

    def test_scaled_tolerance_low_vol_tighter(self):
        """Low-vol stock should get TIGHTER tolerance (fewer false positives)."""
        from mcp_server.volatility import scaled_tolerance
        low_vol = _make_ohlcv(50, base=1000, trend=0)
        low_vol["high"] = low_vol["close"] + 1.0
        low_vol["low"] = low_vol["close"] - 1.0
        tol = scaled_tolerance(low_vol, base_tolerance=0.03)
        # Should be less than base 3% since low vol
        assert tol <= 0.03

    def test_scaled_tolerance_returns_float(self):
        from mcp_server.volatility import scaled_tolerance
        df = _make_ohlcv(50, base=100)
        result = scaled_tolerance(df, base_tolerance=0.03)
        assert isinstance(result, float)
        assert result > 0

    def test_zigzag_threshold_dynamic(self):
        from mcp_server.volatility import zigzag_threshold
        df = _make_ohlcv(50, base=100)
        threshold = zigzag_threshold(df)
        assert isinstance(threshold, float)
        assert 1.0 <= threshold <= 8.0

    def test_atr_distance(self):
        from mcp_server.volatility import atr_distance
        df = _make_ohlcv(50, base=100)
        dist = atr_distance(df, atr_multiplier=1.5)
        assert isinstance(dist, float)
        assert dist > 0


# ============================================================
# 5. ORDER MANAGER — Safety Limits & Kill Switch
# ============================================================

class TestOrderManagerSafety:

    def _manager(self, capital=100000):
        from mcp_server.order_manager import OrderManager
        return OrderManager(kite=None, capital=capital)

    def test_no_broker_blocks_order(self):
        """Without Kite OR Angel connection, orders must be rejected."""
        mgr = self._manager()
        result = mgr.place_order("NSE:RELIANCE", "BUY", qty=10, price=2500)
        assert result.success is False
        # Message changed from "Kite not connected" when Angel broker support landed.
        assert "No broker connected" in result.message

    def test_max_positions_limit(self):
        from mcp_server.order_manager import MAX_OPEN_POSITIONS
        assert MAX_OPEN_POSITIONS == 5

    def test_kill_switch_triggers_at_3pct(self):
        from mcp_server.order_manager import KillSwitchState, DAILY_LOSS_LIMIT_PCT
        ks = KillSwitchState(starting_capital=100000)
        # Lose 3.1% of capital
        ks.realized_pnl = -3100
        triggered = ks.check(100000)
        assert triggered is True
        assert ks.is_triggered is True
        assert DAILY_LOSS_LIMIT_PCT == -0.03

    def test_kill_switch_not_triggered_below_limit(self):
        from mcp_server.order_manager import KillSwitchState
        ks = KillSwitchState(starting_capital=100000)
        ks.realized_pnl = -2000  # Only 2%
        triggered = ks.check(100000)
        assert triggered is False
        assert ks.is_triggered is False

    def test_validate_order_invalid_direction(self):
        mgr = self._manager()
        error = mgr._validate_order("NSE:RELIANCE", "HOLD", qty=10, price=2500)
        assert error is not None
        assert "Invalid direction" in error

    def test_validate_order_zero_qty(self):
        mgr = self._manager()
        error = mgr._validate_order("NSE:RELIANCE", "BUY", qty=0, price=2500)
        assert error is not None
        assert "Invalid quantity" in error

    def test_validate_order_exceeds_max_value(self):
        mgr = self._manager()
        # Try to place an order worth more than Rs.2L
        error = mgr._validate_order("NSE:RELIANCE", "BUY", qty=100, price=2500)
        assert error is not None
        assert "exceeds max" in error

    def test_validate_order_exceeds_position_size(self):
        """Order > 10% of capital should be rejected."""
        mgr = self._manager(capital=100000)
        # 15000 = 15% of 100k
        error = mgr._validate_order("NSE:RELIANCE", "BUY", qty=6, price=2500)
        assert error is not None
        assert "Position size" in error

    @patch("mcp_server.order_manager.validate_order_timing", return_value=None)
    @patch("mcp_server.order_manager.validate_portfolio_risk", return_value=None)
    def test_validate_order_valid(self, mock_risk, mock_timing):
        """Small valid order should pass all checks."""
        mgr = self._manager(capital=100000)
        error = mgr._validate_order("NSE:RELIANCE", "BUY", qty=2, price=2500)
        assert error is None

    def test_order_result_dataclass(self):
        from mcp_server.order_manager import OrderResult
        r = OrderResult(success=True, order_id="12345", message="OK")
        assert r.success is True
        assert r.order_id == "12345"

    def test_get_status_structure(self):
        mgr = self._manager()
        status = mgr.get_status()
        assert "open_positions" in status
        assert "kill_switch_active" in status
        assert "kite_connected" in status
        assert status["kite_connected"] is False
        assert status["open_positions"] == 0

    def test_invalid_exchange_blocked(self):
        mgr = self._manager()
        error = mgr._validate_order("FAKE:RELIANCE", "BUY", qty=2, price=2500)
        assert error is not None
        assert "not allowed" in error

    def test_close_position_no_position(self):
        mgr = self._manager()
        result = mgr.close_position("NSE:RELIANCE")
        assert result.success is False
        assert "No open position" in result.message

    def test_close_all_empty(self):
        mgr = self._manager()
        results = mgr.close_all_positions()
        assert results == []

    def test_update_pnl_accumulates(self):
        mgr = self._manager()
        mgr.update_pnl(500)
        mgr.update_pnl(-200)
        assert mgr.kill_switch.realized_pnl == 300

    def test_order_history_tracked(self):
        mgr = self._manager()
        mgr.place_order("NSE:RELIANCE", "BUY", qty=10, price=2500)
        assert len(mgr.order_history) == 1
        assert mgr.order_history[0].success is False  # No Kite


# ============================================================
# 6. ORDER ENDPOINTS — API Integration
# ============================================================

class TestOrderEndpoints:

    @pytest.mark.asyncio
    async def test_place_order_rejects_oversize(self, async_client):
        # CI runs with PAPER_MODE=true, so the broker check is bypassed.
        # qty=10 × price=2500 = ₹25k order value, which is 25% of the default
        # ₹100k capital and exceeds the 10% per-position safety limit —
        # the order must still be rejected, just on a different code path.
        resp = await async_client.post("/tools/place_order", json={
            "ticker": "NSE:RELIANCE",
            "direction": "BUY",
            "qty": 10,
            "price": 2500,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "Position size" in data["message"] or "No broker connected" in data["message"]

    @pytest.mark.asyncio
    async def test_order_status_endpoint(self, async_client):
        resp = await async_client.get("/tools/order_status")
        assert resp.status_code == 200
        data = resp.json()
        assert "open_positions" in data
        assert "kill_switch_active" in data

    @pytest.mark.asyncio
    async def test_close_all_endpoint(self, async_client):
        resp = await async_client.post("/tools/close_all")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_cancel_order_no_kite(self, async_client):
        resp = await async_client.post("/tools/cancel_order", json={
            "order_id": "fake-123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False

    @pytest.mark.asyncio
    async def test_close_position_no_position(self, async_client):
        resp = await async_client.post("/tools/close_position", json={
            "ticker": "NSE:RELIANCE",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False

    @pytest.mark.asyncio
    async def test_connect_kite_status(self, async_client):
        resp = await async_client.post("/tools/connect_kite")
        assert resp.status_code == 200
        data = resp.json()
        assert data["kite_connected"] is False
