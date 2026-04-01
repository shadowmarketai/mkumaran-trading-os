"""Tests for MWA Signal Generator — ATR-based trade levels."""

import numpy as np
import pandas as pd

from mcp_server.mwa_signal_generator import (
    _compute_atr,
    _count_bull_bear,
    _resolve_asset_class,
    _resolve_exchange,
    generate_mwa_signals,
)


def _make_ohlcv(n: int = 30, base: float = 100.0, volatility: float = 2.0) -> pd.DataFrame:
    """Create a synthetic OHLCV DataFrame with n rows."""
    np.random.seed(42)
    closes = base + np.cumsum(np.random.randn(n) * volatility)
    highs = closes + np.abs(np.random.randn(n)) * volatility
    lows = closes - np.abs(np.random.randn(n)) * volatility
    opens = closes + np.random.randn(n) * 0.5
    volumes = np.random.randint(10000, 500000, size=n)
    return pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })


# ── ATR tests ────────────────────────────────────────────────


def test_compute_atr_valid():
    df = _make_ohlcv(30)
    atr = _compute_atr(df, period=14)
    assert atr > 0, "ATR should be positive for valid OHLCV"


def test_compute_atr_insufficient_bars():
    df = _make_ohlcv(10)
    atr = _compute_atr(df, period=14)
    assert atr == 0.0, "ATR should be 0 when bars < period+1"


# ── Exchange / asset class resolution ────────────────────────


def test_resolve_exchange_nse():
    assert _resolve_exchange("RELIANCE") == "NSE"


def test_resolve_exchange_mcx():
    assert _resolve_exchange("GOLD") == "MCX"


def test_resolve_exchange_cds():
    assert _resolve_exchange("USDINR") == "CDS"


def test_resolve_asset_class():
    assert _resolve_asset_class("NSE") == "EQUITY"
    assert _resolve_asset_class("MCX") == "COMMODITY"
    assert _resolve_asset_class("CDS") == "CURRENCY"


# ── Bull/Bear count ──────────────────────────────────────────


def test_count_bull_bear():
    scanner_results = {
        "swing_low": ["RELIANCE", "TCS"],
        "upswing": ["RELIANCE"],
        "swing_high": ["RELIANCE"],
    }
    bull, bear = _count_bull_bear("RELIANCE", scanner_results)
    assert bull == 2, "RELIANCE should appear in 2 bull scanners"
    assert bear == 1, "RELIANCE should appear in 1 bear scanner"


# ── Full signal generation ───────────────────────────────────


def test_generate_mwa_signals_long():
    stock_data = {"RELIANCE": _make_ohlcv(30, base=2500, volatility=30)}
    scanner_results = {
        "swing_low": ["RELIANCE"],
        "upswing": ["RELIANCE"],
        "volume_avg": ["RELIANCE"],
    }

    signals = generate_mwa_signals(
        promoted=["RELIANCE"],
        stock_data=stock_data,
        mwa_direction="BULL",
        scanner_results=scanner_results,
    )

    assert len(signals) == 1
    sig = signals[0]
    assert sig["ticker"] == "RELIANCE"
    assert sig["direction"] == "LONG"
    assert sig["sl"] < sig["entry"] < sig["target"]
    assert sig["rrr"] >= 1.0
    assert sig["qty"] >= 1
    assert sig["exchange"] == "NSE"
    assert sig["asset_class"] == "EQUITY"
    assert sig["scanner_count"] == 3


def test_generate_mwa_signals_short():
    stock_data = {"INFY": _make_ohlcv(30, base=1500, volatility=20)}
    scanner_results = {
        "swing_high": ["INFY"],
        "downswing": ["INFY"],
        "rsi_below_30": ["INFY"],
    }

    signals = generate_mwa_signals(
        promoted=["INFY"],
        stock_data=stock_data,
        mwa_direction="BEAR",
        scanner_results=scanner_results,
    )

    assert len(signals) == 1
    sig = signals[0]
    assert sig["direction"] == "SHORT"
    assert sig["sl"] > sig["entry"] > sig["target"]


def test_generate_mwa_signals_empty_stock_data():
    signals = generate_mwa_signals(
        promoted=["RELIANCE"],
        stock_data={},
        mwa_direction="BULL",
        scanner_results={},
    )
    assert signals == []


def test_generate_mwa_signals_insufficient_bars():
    stock_data = {"TCS": _make_ohlcv(5)}
    signals = generate_mwa_signals(
        promoted=["TCS"],
        stock_data=stock_data,
        mwa_direction="BULL",
        scanner_results={"swing_low": ["TCS"]},
    )
    assert signals == [], "Should skip stocks with fewer than 15 bars"
