"""
Tests for accuracy improvements:
1. Volatility integration in pattern engines
2. Confidence boost capping
3. Asset-class conditional RRR
4. Transaction cost accuracy
5. Telegram signal parser
6. Sheets tracker data model
"""

import numpy as np
import pandas as pd
import pytest


def _make_ohlcv(n=100, base=100.0, trend=0.5):
    closes = [base]
    for i in range(1, n):
        closes.append(closes[-1] + trend + np.random.randn() * 2)
    closes = np.array(closes, dtype=float)
    return pd.DataFrame({
        "open": closes - 0.5,
        "high": closes + abs(np.random.randn(n) * 2) + 1,
        "low": closes - abs(np.random.randn(n) * 2) - 1,
        "close": closes,
        "volume": np.random.randint(50000, 500000, n),
    })


# ============================================================
# 1. Volatility Integration — engines use scaled_tolerance
# ============================================================

class TestPatternEngineVolatility:

    def test_pattern_engine_has_tol_method(self):
        from mcp_server.pattern_engine import PatternEngine
        engine = PatternEngine()
        assert hasattr(engine, '_tol')

    def test_pattern_engine_has_slope_threshold(self):
        from mcp_server.pattern_engine import PatternEngine
        engine = PatternEngine()
        assert hasattr(engine, '_slope_threshold')

    def test_detect_all_uses_volatility(self):
        """detect_all should set df_full for volatility calculations."""
        from mcp_server.pattern_engine import PatternEngine
        engine = PatternEngine()
        df = _make_ohlcv(100)
        engine.detect_all(df)
        assert engine.df_full is not None

    def test_tol_returns_float(self):
        from mcp_server.pattern_engine import PatternEngine
        engine = PatternEngine()
        engine.df_full = _make_ohlcv(100)
        result = engine._tol(0.03)
        assert isinstance(result, float)
        assert result > 0

    def test_tol_fallback_without_data(self):
        from mcp_server.pattern_engine import PatternEngine
        engine = PatternEngine()
        result = engine._tol(0.03)
        assert result == 0.03  # Fallback to base


class TestSMCEngineVolatility:

    def test_smc_has_tol_method(self):
        from mcp_server.smc_engine import SMCEngine
        engine = SMCEngine()
        assert hasattr(engine, '_tol')

    def test_smc_detect_all_sets_df_full(self):
        from mcp_server.smc_engine import SMCEngine
        engine = SMCEngine()
        df = _make_ohlcv(100)
        engine.detect_all(df)
        assert engine.df_full is not None


class TestWyckoffEngineVolatility:

    def test_wyckoff_has_tol_method(self):
        from mcp_server.wyckoff_engine import WyckoffEngine
        engine = WyckoffEngine()
        assert hasattr(engine, '_tol')


class TestVSAEngineVolatility:

    def test_vsa_has_spread_tol(self):
        from mcp_server.vsa_engine import VSAEngine
        engine = VSAEngine()
        assert hasattr(engine, '_spread_tol')

    def test_vsa_has_tol(self):
        from mcp_server.vsa_engine import VSAEngine
        engine = VSAEngine()
        assert hasattr(engine, '_tol')


class TestHarmonicEngineVolatility:

    def test_harmonic_imports_zigzag_threshold(self):
        from mcp_server.harmonic_engine import zigzag_threshold
        assert callable(zigzag_threshold)

    def test_harmonic_detect_all_sets_df_full(self):
        from mcp_server.harmonic_engine import HarmonicEngine
        engine = HarmonicEngine()
        df = _make_ohlcv(150)
        engine.detect_all(df)
        assert engine.df_full is not None


# ============================================================
# 2. Confidence Boost Capping
# ============================================================

class TestConfidenceBoostCap:

    def test_boost_capped_at_25(self):
        """Total confidence boost should never exceed +25%."""
        from mcp_server.signal_rules import apply_confidence_boosts
        # All possible boosts active: supertrend, 52wk, vol2x, sector, fii, tv, delivery, macd, multi
        scanner_results = {
            "17_supertrend": {"count": 1},
            "19_52week_high": {"count": 1},
            "7_vol_2x": {"count": 1},
            "18_macd": {"count": 1},
            "1_swing_low": {"count": 1},
            "2_upswing": {"count": 1},
            "6_vol_above_avg": {"count": 1},
            "10_50day_high": {"count": 1},
        }
        final, boosts = apply_confidence_boosts(
            base_confidence=50,
            scanner_results=scanner_results,
            tv_confirmed=True,
            delivery_pct=70,
            fii_net=500,
            sector_strength="STRONG",
            direction="LONG",
        )
        # Max should be 50 + 25 = 75
        assert final <= 75
        assert any("capped" in b.lower() for b in boosts)

    def test_small_boost_not_capped(self):
        """Single boost under 25% should not be capped."""
        from mcp_server.signal_rules import apply_confidence_boosts
        scanner_results = {"17_supertrend": {"count": 1}}
        final, boosts = apply_confidence_boosts(
            base_confidence=60,
            scanner_results=scanner_results,
            tv_confirmed=False,
            delivery_pct=40,
            fii_net=0,
            sector_strength="NEUTRAL",
            direction="LONG",
        )
        assert final == 75  # 60 + 15
        assert not any("capped" in b.lower() for b in boosts)


# ============================================================
# 3. Asset-Class Conditional RRR
# ============================================================

class TestAssetClassRRR:

    def test_equity_requires_3_rrr(self):
        from mcp_server.signal_rules import check_auto_reject
        rejected, reason = check_auto_reject(
            rrr=2.5, sector_strength="STRONG", direction="LONG",
            fii_net=100, volume_scanners=["6_vol_above_avg"], cmp=100, ltrp=110,
            ticker="NSE:RELIANCE",
        )
        assert rejected is True
        assert "3.0" in reason

    def test_fno_accepts_2_rrr(self):
        from mcp_server.signal_rules import check_auto_reject
        rejected, _ = check_auto_reject(
            rrr=2.5, sector_strength="STRONG", direction="LONG",
            fii_net=100, volume_scanners=["6_vol_above_avg"], cmp=100, ltrp=110,
            ticker="NFO:NIFTY",
        )
        assert rejected is False  # 2.5 > 2.0 min for NFO

    def test_mcx_accepts_2_rrr(self):
        from mcp_server.signal_rules import check_auto_reject
        rejected, _ = check_auto_reject(
            rrr=2.5, sector_strength="STRONG", direction="LONG",
            fii_net=100, volume_scanners=["6_vol_above_avg"], cmp=100, ltrp=110,
            ticker="MCX:GOLD",
        )
        assert rejected is False

    def test_backward_compatible_no_ticker(self):
        """Without ticker param, default RRR 3.0 applies."""
        from mcp_server.signal_rules import check_auto_reject
        rejected, _ = check_auto_reject(
            rrr=2.5, sector_strength="STRONG", direction="LONG",
            fii_net=100, volume_scanners=["6_vol_above_avg"], cmp=100, ltrp=110,
        )
        assert rejected is True  # Default 3.0 RRR


# ============================================================
# 4. Transaction Cost Accuracy
# ============================================================

class TestTransactionCosts:

    def test_brokerage_uses_lower_of_pct_or_flat(self):
        """Zerodha charges min(0.03% of turnover, Rs.20)."""
        from mcp_server.backtester import _calculate_transaction_cost
        # Small order: 0.03% of 5000 = 1.5 < 20, so brokerage = 1.5
        cost_small = _calculate_transaction_cost(price=50, qty=100, is_sell=False)
        # Large order: 0.03% of 200000 = 60 > 20, so brokerage = 20
        cost_large = _calculate_transaction_cost(price=2000, qty=100, is_sell=False)
        # Small order brokerage component should be less
        assert cost_small < cost_large

    def test_sell_side_has_stt(self):
        from mcp_server.backtester import _calculate_transaction_cost
        buy_cost = _calculate_transaction_cost(100, 10, is_sell=False)
        sell_cost = _calculate_transaction_cost(100, 10, is_sell=True)
        assert sell_cost > buy_cost


# ============================================================
# 5. Telegram Signal Parser
# ============================================================

class TestTelegramParser:

    def test_parse_structured_signal(self):
        from mcp_server.telegram_receiver import parse_signal_message
        signal = parse_signal_message("BUY NSE:RELIANCE @ 2500 SL 2400 TGT 2800")
        assert signal is not None
        assert signal.ticker == "NSE:RELIANCE"
        assert signal.direction == "BUY"
        assert signal.entry_price == 2500
        assert signal.stop_loss == 2400
        assert signal.target == 2800
        assert signal.rrr == 3.0  # (2800-2500)/(2500-2400) = 300/100

    def test_parse_sell_signal(self):
        from mcp_server.telegram_receiver import parse_signal_message
        signal = parse_signal_message("SELL MCX:GOLD @ 70000 SL 71000 TARGET 68000")
        assert signal is not None
        assert signal.direction == "SELL"
        assert signal.ticker == "MCX:GOLD"

    def test_parse_simple_format(self):
        from mcp_server.telegram_receiver import parse_signal_message
        signal = parse_signal_message("BUY RELIANCE 2500 SL 2400 TGT 2800")
        assert signal is not None
        assert "RELIANCE" in signal.ticker
        assert signal.direction == "BUY"

    def test_parse_with_confidence(self):
        from mcp_server.telegram_receiver import parse_signal_message
        signal = parse_signal_message("BUY NSE:SBIN @ 600 SL 580 TGT 680 Confidence: 75")
        assert signal is not None
        assert signal.confidence == 75

    def test_parse_nonsignal_returns_none(self):
        from mcp_server.telegram_receiver import parse_signal_message
        assert parse_signal_message("Hello how are you?") is None
        assert parse_signal_message("") is None
        assert parse_signal_message("short") is None

    def test_parse_long_keyword(self):
        from mcp_server.telegram_receiver import parse_signal_message
        signal = parse_signal_message("LONG NSE:TATAMOTORS Entry: 950 SL: 920 Target: 1050")
        assert signal is not None
        assert signal.direction == "BUY"


class TestTelegramSignalDataclass:

    def test_signal_defaults(self):
        from mcp_server.telegram_receiver import TelegramSignal
        sig = TelegramSignal()
        assert sig.status == "OPEN"
        assert sig.pnl_pct == 0.0
        assert sig.result == ""

    def test_signal_fields(self):
        from mcp_server.telegram_receiver import TelegramSignal
        sig = TelegramSignal(
            ticker="NSE:RELIANCE", direction="BUY",
            entry_price=2500, stop_loss=2400, target=2800,
        )
        assert sig.ticker == "NSE:RELIANCE"
        assert sig.entry_price == 2500


# ============================================================
# 6. API Endpoints
# ============================================================

class TestSignalTrackingEndpoints:

    @pytest.mark.asyncio
    async def test_record_signal_endpoint(self, async_client):
        resp = await async_client.post("/tools/record_signal", json={
            "ticker": "NSE:RELIANCE",
            "direction": "BUY",
            "entry_price": 2500,
            "stop_loss": 2400,
            "target": 2800,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "signal_id" in data

    @pytest.mark.asyncio
    async def test_signal_accuracy_endpoint(self, async_client):
        resp = await async_client.get("/tools/signal_accuracy")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_telegram_webhook_nonsignal(self, async_client):
        resp = await async_client.post("/api/telegram_webhook", json={
            "text": "hello world",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["parsed"] is False

    @pytest.mark.asyncio
    async def test_telegram_webhook_valid_signal(self, async_client):
        resp = await async_client.post("/api/telegram_webhook", json={
            "text": "BUY NSE:SBIN @ 600 SL 580 TGT 680",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["parsed"] is True
        assert "SBIN" in data.get("ticker", "")
