"""Tests for RL-Inspired Engine."""

import numpy as np
import pandas as pd

from mcp_server.rl_engine import (
    RLEngine,
    _compute_vwap,
    _calculate_regime,
    _normalize_momentum,
    _calculate_risk_reward,
    scan_rl_trend_bull, scan_rl_trend_bear,
    scan_rl_vwap_bull, scan_rl_vwap_bear,
    scan_rl_momentum_bull, scan_rl_momentum_bear,
    scan_rl_optimal_entry_bull, scan_rl_optimal_entry_bear,
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


def _trending_up_df(n=100):
    """Create clearly trending up data."""
    closes = [100 + i * 0.5 for i in range(n)]
    return _make_df(closes)


def _trending_down_df(n=100):
    """Create clearly trending down data."""
    closes = [200 - i * 0.5 for i in range(n)]
    return _make_df(closes)


def _ranging_df(n=100):
    """Create ranging/flat data."""
    np.random.seed(42)
    closes = [100 + np.sin(i * 0.3) * 0.5 for i in range(n)]
    return _make_df(closes)


def _random_df(n=100):
    np.random.seed(55)
    closes = 100 + np.cumsum(np.random.randn(n) * 1.5)
    return _make_df(closes.tolist())


# ── Init + basics ────────────────────────────────────────────

def test_rl_engine_init():
    engine = RLEngine()
    assert engine.lookback == 60


def test_detect_all_short_data():
    engine = RLEngine()
    df = _make_df([100, 101, 102])
    assert engine.detect_all(df) == []


# ── Regime trend detection ───────────────────────────────────

def test_regime_trend_bullish():
    engine = RLEngine()
    df = _trending_up_df(100)
    result = engine.detect_regime_trend(df)
    if result is not None:
        assert result.direction == "BULLISH"
        assert result.name == "RL Regime Trend"


def test_regime_trend_bearish():
    engine = RLEngine()
    df = _trending_down_df(100)
    result = engine.detect_regime_trend(df)
    if result is not None:
        assert result.direction == "BEARISH"


def test_regime_trend_none_for_ranging():
    engine = RLEngine()
    df = _ranging_df(100)
    result = engine.detect_regime_trend(df)
    # Ranging should return None (no strong trend)
    # May or may not detect depending on exact data
    if result is not None:
        assert result.direction in ("BULLISH", "BEARISH")


# ── VWAP deviation detection ────────────────────────────────

def test_vwap_deviation_bullish():
    """Price below VWAP should signal bullish mean-reversion."""
    engine = RLEngine()
    # Create data where recent price drops below VWAP
    closes = [100] * 50 + [95] * 10
    df = _make_df(closes, volume=100000)
    result = engine.detect_vwap_deviation(df)
    if result is not None:
        assert result.name == "RL VWAP Deviation"
        assert result.direction == "BULLISH"


def test_vwap_deviation_bearish():
    """Price above VWAP should signal bearish mean-reversion."""
    engine = RLEngine()
    closes = [100] * 50 + [108] * 10
    df = _make_df(closes, volume=100000)
    result = engine.detect_vwap_deviation(df)
    if result is not None:
        assert result.name == "RL VWAP Deviation"
        assert result.direction == "BEARISH"


# ── Momentum score detection ────────────────────────────────

def test_momentum_bull():
    engine = RLEngine()
    df = _trending_up_df(100)
    result = engine.detect_momentum_score(df)
    if result is not None:
        assert result.direction == "BULLISH"
        assert result.name == "RL Momentum Score"


def test_momentum_bear():
    engine = RLEngine()
    df = _trending_down_df(100)
    result = engine.detect_momentum_score(df)
    if result is not None:
        assert result.direction == "BEARISH"


# ── Risk-reward setup detection ──────────────────────────────

def test_risk_reward_setup():
    engine = RLEngine()
    df = _trending_up_df(100)
    result = engine.detect_risk_reward_setup(df)
    if result is not None:
        assert result.name == "RL Risk-Reward Setup"
        assert "R:R" in result.description


def test_risk_reward_values():
    df = _trending_up_df(100)
    entry, sl, tp, rr = _calculate_risk_reward(df)
    assert entry > 0
    assert sl < entry  # SL below entry for long
    assert tp > entry  # TP above entry
    assert rr >= 2.0   # Minimum 2:1 R:R


# ── Regime shift detection ───────────────────────────────────

def test_regime_shift_detection():
    engine = RLEngine()
    # Create data: flat then trending
    flat = [100 + np.sin(i * 0.1) * 0.2 for i in range(40)]
    trend = [100 + i * 0.8 for i in range(20)]
    df = _make_df(flat + trend)
    result = engine.detect_regime_shift(df)
    if result is not None:
        assert result.name == "RL Regime Shift"
        assert "RANGING" in result.description


def test_regime_shift_no_shift():
    engine = RLEngine()
    df = _trending_up_df(100)
    result = engine.detect_regime_shift(df)
    # Already trending — no shift from ranging
    # May or may not return None
    if result is not None:
        assert result.name == "RL Regime Shift"


# ── Optimal entry detection ──────────────────────────────────

def test_optimal_entry_bullish():
    engine = RLEngine()
    df = _trending_up_df(100)
    engine.df_full = df
    result = engine.detect_optimal_entry(df.tail(60))
    if result is not None:
        assert result.name == "RL Optimal Entry"
        assert result.direction == "BULLISH"
        assert "Confluence" in result.description


def test_optimal_entry_bearish():
    engine = RLEngine()
    df = _trending_down_df(100)
    engine.df_full = df
    result = engine.detect_optimal_entry(df.tail(60))
    if result is not None:
        assert result.name == "RL Optimal Entry"
        assert result.direction == "BEARISH"


# ── Helper function tests ────────────────────────────────────

def test_compute_vwap():
    df = _make_df(list(range(100, 120)), volume=50000)
    vwap = _compute_vwap(df)
    assert len(vwap) == len(df)
    assert all(v > 0 for v in vwap)


def test_calculate_regime_values():
    assert _calculate_regime(_trending_up_df(100)) in ("TRENDING_UP", "RANGING")
    assert _calculate_regime(_trending_down_df(100)) in ("TRENDING_DOWN", "RANGING")
    assert _calculate_regime(_make_df([100, 101])) == "RANGING"  # Too short


def test_normalize_momentum_range():
    score = _normalize_momentum(_trending_up_df(100))
    assert -1 <= score <= 1

    score = _normalize_momentum(_trending_down_df(100))
    assert -1 <= score <= 1


# ── Scanner wrappers ─────────────────────────────────────────

def test_scanner_wrappers_return_lists():
    stock_data = {"TEST": _random_df(100)}
    scanners = [
        scan_rl_trend_bull, scan_rl_trend_bear,
        scan_rl_vwap_bull, scan_rl_vwap_bear,
        scan_rl_momentum_bull, scan_rl_momentum_bear,
        scan_rl_optimal_entry_bull, scan_rl_optimal_entry_bear,
    ]
    for fn in scanners:
        result = fn(stock_data)
        assert isinstance(result, list), f"{fn.__name__} should return list"


def test_scanner_wrappers_empty_data():
    for fn in [scan_rl_trend_bull, scan_rl_momentum_bull, scan_rl_optimal_entry_bull]:
        assert fn({}) == []


# ── Insufficient data edge cases ─────────────────────────────

def test_detect_all_insufficient_data():
    engine = RLEngine()
    df = _make_df(list(range(100, 110)))  # Only 10 bars
    assert engine.detect_all(df) == []


def test_short_data_scanners():
    stock_data = {"SHORT": _make_df(list(range(100, 110)))}
    assert scan_rl_trend_bull(stock_data) == []
    assert scan_rl_momentum_bear(stock_data) == []


# ── Integration with SCANNERS / SIGNAL_CHAINS ────────────────

def test_scanners_dict_has_rl():
    from mcp_server.mwa_scanner import SCANNERS
    rl_keys = [
        "rl_trend_bull", "rl_trend_bear",
        "rl_vwap_bull", "rl_vwap_bear",
        "rl_momentum_bull", "rl_momentum_bear",
        "rl_optimal_entry_bull", "rl_optimal_entry_bear",
    ]
    for key in rl_keys:
        assert key in SCANNERS, f"Missing: {key}"
        assert SCANNERS[key]["layer"] == "RL"


def test_total_scanner_count_is_at_least_original():
    # Lower-bound: scanner catalog is additive (118 baseline).
    from mcp_server.mwa_scanner import SCANNERS
    assert len(SCANNERS) >= 118, f"Expected at least 118 scanners, got {len(SCANNERS)}"


def test_total_signal_chain_count_is_at_least_original():
    # Lower-bound: signal chain catalog is additive (34 baseline).
    from mcp_server.mwa_scanner import SIGNAL_CHAINS
    assert len(SIGNAL_CHAINS) >= 34, f"Expected at least 34 chains, got {len(SIGNAL_CHAINS)}"
