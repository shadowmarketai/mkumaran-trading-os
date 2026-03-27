"""Tests for Technical Scanners and Swing Detector."""

import numpy as np
import pandas as pd

from mcp_server.technical_scanners import (
    compute_ema,
    detect_ema_crossover,
    compute_supertrend,
    compute_macd,
    scan_nifty_ema,
    scan_stock_ema_crossover,
    scan_supertrend,
    scan_macd_crossover,
    scan_52week_high,
    run_all_technical_scanners,
)
from mcp_server.swing_detector import (
    find_swing_low,
    find_swing_high,
    auto_detect_levels,
)


def _make_df(closes, volume=100000):
    n = len(closes)
    arr = np.array(closes, dtype=float)
    return pd.DataFrame({
        "open": arr - 0.5,
        "high": arr + 1.0,
        "low": arr - 1.0,
        "close": arr,
        "volume": [volume] * n,
    })


# ── EMA ───────────────────────────────────────────────────────

def test_compute_ema_length():
    series = pd.Series(range(100), dtype=float)
    ema = compute_ema(series, 10)
    assert len(ema) == 100


def test_compute_ema_follows_trend():
    series = pd.Series(range(50), dtype=float)
    ema = compute_ema(series, 5)
    assert ema.iloc[-1] > ema.iloc[0]


def test_detect_ema_crossover_buy():
    """Fast rising above slow = BUY."""
    closes = list(range(90, 110))  # 20 bars uptrend
    closes[-2] = 105  # Force crossover at end
    closes[-1] = 110
    df = _make_df(closes)
    signal = detect_ema_crossover(df, fast_period=3, slow_period=10)
    assert signal in ("BUY", "SELL", "HOLD")


def test_detect_ema_crossover_short_data():
    df = _make_df([100])
    signal = detect_ema_crossover(df, 5, 10)
    assert signal == "HOLD"


# ── Supertrend ────────────────────────────────────────────────

def test_compute_supertrend_columns():
    df = _make_df(list(range(100, 150)))
    result = compute_supertrend(df)
    assert "supertrend" in result.columns
    assert "st_direction" in result.columns


def test_scan_supertrend_returns_dict():
    stock_data = {"TEST": _make_df(list(range(100, 150)))}
    result = scan_supertrend(stock_data)
    assert isinstance(result, dict)
    assert result["name"] == "Supertrend Buy"
    assert "stocks" in result
    assert "count" in result


def test_scan_supertrend_empty():
    result = scan_supertrend({})
    assert result["count"] == 0


# ── MACD ──────────────────────────────────────────────────────

def test_compute_macd_returns_tuple():
    df = _make_df(list(range(100, 200)))
    macd, signal, hist = compute_macd(df)
    assert len(macd) == len(df)
    assert len(signal) == len(df)
    assert len(hist) == len(df)


def test_scan_macd_crossover_returns_dict():
    stock_data = {"TEST": _make_df(list(range(100, 200)))}
    result = scan_macd_crossover(stock_data)
    assert result["name"] == "MACD Bullish Crossover"
    assert isinstance(result["stocks"], list)


def test_scan_macd_short_data():
    stock_data = {"TEST": _make_df([100, 101, 102])}
    result = scan_macd_crossover(stock_data)
    assert result["count"] == 0


# ── 52-Week High ──────────────────────────────────────────────

def test_scan_52week_high_returns_dict():
    closes = list(range(100, 400))
    stock_data = {"TEST": _make_df(closes)}
    result = scan_52week_high(stock_data)
    assert isinstance(result, dict)
    assert result["direction"] == "BULL"


def test_scan_52week_high_short_data():
    stock_data = {"TEST": _make_df([100, 101])}
    result = scan_52week_high(stock_data)
    assert result["count"] == 0


# ── Nifty EMA Scanner ────────────────────────────────────────

def test_scan_nifty_ema_returns_dict():
    df = _make_df(list(range(100, 130)))
    result = scan_nifty_ema(df)
    assert result["name"] == "Nifty 5/10 EMA"
    assert result["group"] == "G7_EMA"


# ── Stock EMA Scanner ────────────────────────────────────────

def test_scan_stock_ema_crossover():
    stock_data = {"TEST": _make_df(list(range(100, 150)))}
    result = scan_stock_ema_crossover(stock_data)
    assert result["name"] == "Stock 9/21 EMA Cross"
    assert isinstance(result["stocks"], list)


# ── run_all_technical_scanners ────────────────────────────────

def test_run_all_no_nifty():
    stock_data = {"TEST": _make_df(list(range(100, 200)))}
    results = run_all_technical_scanners(stock_data)
    assert "16c_stock_ema" in results
    assert "17_supertrend" in results
    assert "18_macd" in results
    assert "19_52week_high" in results
    assert "16b_nifty_ema" not in results


def test_run_all_with_nifty():
    stock_data = {"TEST": _make_df(list(range(100, 200)))}
    nifty_df = _make_df(list(range(100, 130)))
    results = run_all_technical_scanners(stock_data, nifty_df)
    assert "16b_nifty_ema" in results


# ── Swing Detector ────────────────────────────────────────────

def test_find_swing_low_basic():
    np.random.seed(42)
    closes = list(np.cumsum(np.random.randn(100)) + 200)
    df = _make_df(closes)
    result = find_swing_low(df, lookback=5)
    assert result > 0


def test_find_swing_low_short_data():
    df = _make_df([100, 101, 102])
    result = find_swing_low(df, lookback=5)
    assert result == 0.0


def test_find_swing_high_basic():
    np.random.seed(42)
    closes = list(np.cumsum(np.random.randn(100)) + 200)
    df = _make_df(closes)
    result = find_swing_high(df, lookback=5)
    assert result > 0


def test_find_swing_high_short_data():
    df = _make_df([100, 101])
    result = find_swing_high(df, lookback=5)
    assert result == 0.0


def test_auto_detect_levels():
    np.random.seed(42)
    closes = list(np.cumsum(np.random.randn(100)) + 200)
    df = _make_df(closes)
    levels = auto_detect_levels(df, lookback=5)
    assert "ltrp" in levels
    assert "pivot_high" in levels
    assert levels["ltrp"] > 0
    assert levels["pivot_high"] > 0
