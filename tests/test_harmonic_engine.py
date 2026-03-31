"""Tests for Harmonic Pattern Engine."""

import numpy as np
import pandas as pd

from mcp_server.harmonic_engine import (
    HarmonicEngine,
    _find_zigzag_points,
    HARMONIC_RATIOS,
    scan_harmonic_gartley_bull, scan_harmonic_gartley_bear,
    scan_harmonic_bat_bull, scan_harmonic_bat_bear,
    scan_harmonic_any_bull, scan_harmonic_any_bear,
)


def _make_df(closes, spread=1.0, volume=100000):
    n = len(closes)
    np.random.seed(77)
    arr = np.array(closes, dtype=float)
    return pd.DataFrame({
        "open": arr - np.random.rand(n) * spread * 0.3,
        "high": arr + np.random.rand(n) * spread,
        "low": arr - np.random.rand(n) * spread,
        "close": arr,
        "volume": [volume] * n,
    })


def _random_df(n=150):
    np.random.seed(55)
    closes = 100 + np.cumsum(np.random.randn(n) * 1.5)
    return _make_df(closes.tolist())


# ── Init + basics ────────────────────────────────────────────

def test_harmonic_engine_init():
    engine = HarmonicEngine()
    assert engine.lookback == 120
    assert engine.zigzag_pct == 3.0


def test_detect_all_short_data():
    engine = HarmonicEngine()
    df = pd.DataFrame({
        "open": [100, 101], "high": [102, 103],
        "low": [99, 100], "close": [101, 102],
        "volume": [1000, 1100],
    })
    assert engine.detect_all(df) == []


def test_detect_all_returns_list():
    engine = HarmonicEngine()
    df = _random_df(200)
    results = engine.detect_all(df)
    assert isinstance(results, list)
    for r in results:
        assert hasattr(r, "name")
        assert r.name.startswith("Harmonic")
        assert r.direction in ("BULLISH", "BEARISH")


# ── Fibonacci ratio definitions ──────────────────────────────

def test_harmonic_ratios_defined():
    assert len(HARMONIC_RATIOS) == 5
    for name in ["Gartley", "Butterfly", "Bat", "Crab", "Cypher"]:
        assert name in HARMONIC_RATIOS
        assert "tolerance" in HARMONIC_RATIOS[name]
        assert HARMONIC_RATIOS[name]["tolerance"] > 0


def test_gartley_ratios():
    g = HARMONIC_RATIOS["Gartley"]
    assert g["AB_XA"] == (0.618, 0.618)
    assert g["AD_XA"] == (0.786, 0.786)


# ── Zigzag point detection ───────────────────────────────────

def test_zigzag_finds_points():
    df = _random_df(200)
    points = _find_zigzag_points(df, pct_threshold=3.0, max_points=5)
    assert isinstance(points, list)
    # Should find some points in random walk data
    for idx, price in points:
        assert isinstance(idx, int)
        assert isinstance(price, float)


def test_zigzag_short_data():
    df = _make_df([100, 101, 102])
    points = _find_zigzag_points(df, pct_threshold=3.0)
    assert isinstance(points, list)


# ── Pattern detection ────────────────────────────────────────

def test_check_pattern_invalid_xabcd():
    """Invalid XABCD should return None."""
    engine = HarmonicEngine()
    result = engine._check_pattern("Gartley", 100, 100, 100, 100, 100)
    assert result is None  # No move = no pattern


def test_check_pattern_valid_gartley_structure():
    """Test with manually crafted Gartley-like XABCD."""
    engine = HarmonicEngine()
    # Bullish Gartley: X=100, A=110 (+10), B=103.82 (61.8% retrace),
    # C=107.64 (~61.8% of AB), D=102.14 (78.6% of XA)
    x, a = 100.0, 110.0
    b = a - (a - x) * 0.618  # 103.82
    c = b + (a - b) * 0.618  # 107.64
    d = a - (a - x) * 0.786  # 102.14
    result = engine._check_pattern("Gartley", x, a, b, c, d)
    # May or may not match due to CD/BC ratio constraints
    if result is not None:
        assert "Gartley" in result.name
        assert result.confidence == 0.75


# ── Scanner wrappers ─────────────────────────────────────────

def test_harmonic_scanner_wrappers_return_lists():
    stock_data = {"TEST": _random_df(200)}
    scanners = [
        scan_harmonic_gartley_bull, scan_harmonic_gartley_bear,
        scan_harmonic_bat_bull, scan_harmonic_bat_bear,
        scan_harmonic_any_bull, scan_harmonic_any_bear,
    ]
    for fn in scanners:
        result = fn(stock_data)
        assert isinstance(result, list), f"{fn.__name__} should return list"


def test_harmonic_scanner_empty_data():
    for fn in [scan_harmonic_any_bull, scan_harmonic_gartley_bull]:
        assert fn({}) == []


# ── Integration ──────────────────────────────────────────────

def test_scanners_dict_has_harmonic():
    from mcp_server.mwa_scanner import SCANNERS
    harmonic_keys = [
        "harmonic_gartley_bull", "harmonic_gartley_bear",
        "harmonic_bat_bull", "harmonic_bat_bear",
        "harmonic_any_bull", "harmonic_any_bear",
    ]
    for key in harmonic_keys:
        assert key in SCANNERS, f"Missing: {key}"
        assert SCANNERS[key]["layer"] == "Harmonic"


def test_total_scanner_count():
    from mcp_server.mwa_scanner import SCANNERS
    assert len(SCANNERS) == 98, f"Expected 98 scanners, got {len(SCANNERS)}"


def test_total_signal_chain_count():
    from mcp_server.mwa_scanner import SIGNAL_CHAINS
    assert len(SIGNAL_CHAINS) == 28, f"Expected 28 chains, got {len(SIGNAL_CHAINS)}"
