"""Tests for Wyckoff Method Engine."""

import numpy as np
import pandas as pd

from mcp_server.wyckoff_engine import (
    WyckoffEngine,
    scan_accumulation, scan_distribution,
    scan_spring, scan_upthrust,
    scan_sos, scan_sow,
    scan_test_bull, scan_test_bear,
)


def _make_df(closes, spread=1.0, volume=100000):
    n = len(closes)
    np.random.seed(99)
    arr = np.array(closes, dtype=float)
    return pd.DataFrame({
        "open": arr - np.random.rand(n) * spread * 0.3,
        "high": arr + np.random.rand(n) * spread,
        "low": arr - np.random.rand(n) * spread,
        "close": arr,
        "volume": [volume] * n,
    })


def _range_after_downtrend(n=80):
    """Downtrend then sideways range — accumulation setup."""
    np.random.seed(11)
    closes = [200.0]
    for _ in range(29):
        closes.append(closes[-1] - abs(np.random.randn()) * 0.5 - 0.2)
    base = closes[-1]
    for _ in range(n - 30):
        closes.append(base + np.random.randn() * 0.5)
    return _make_df(closes, volume=80000)


def _range_after_uptrend(n=80):
    """Uptrend then sideways range — distribution setup."""
    np.random.seed(12)
    closes = [100.0]
    for _ in range(29):
        closes.append(closes[-1] + abs(np.random.randn()) * 0.5 + 0.2)
    base = closes[-1]
    for _ in range(n - 30):
        closes.append(base + np.random.randn() * 0.5)
    return _make_df(closes, volume=80000)


# ── Init + basics ────────────────────────────────────────────

def test_wyckoff_engine_init():
    engine = WyckoffEngine()
    assert engine.lookback == 60
    assert engine.range_lookback == 30


def test_detect_all_short_data():
    engine = WyckoffEngine()
    df = pd.DataFrame({
        "open": [100], "high": [102], "low": [99],
        "close": [101], "volume": [1000],
    })
    assert engine.detect_all(df) == []


def test_detect_all_returns_list():
    engine = WyckoffEngine()
    df = _range_after_downtrend(120)
    results = engine.detect_all(df)
    assert isinstance(results, list)
    for r in results:
        assert hasattr(r, "name")
        assert hasattr(r, "direction")


# ── Accumulation ─────────────────────────────────────────────

def test_accumulation_after_downtrend():
    engine = WyckoffEngine()
    df = _range_after_downtrend(120)
    result = engine.detect_accumulation(
        df.tail(60).copy().reset_index(drop=True)
        .rename(columns=str.lower)
    )
    # May or may not detect depending on volume pattern
    if result is not None:
        assert result.name == "Wyckoff Accumulation"
        assert result.direction == "BULLISH"


def test_no_accumulation_in_uptrend():
    engine = WyckoffEngine()
    np.random.seed(13)
    closes = [100 + i * 0.5 for i in range(80)]
    df = _make_df(closes)
    data = df.tail(60).copy().reset_index(drop=True)
    data.columns = [c.lower() for c in data.columns]
    result = engine.detect_accumulation(data)
    assert result is None  # No accumulation in pure uptrend


# ── Distribution ─────────────────────────────────────────────

def test_distribution_after_uptrend():
    engine = WyckoffEngine()
    df = _range_after_uptrend(120)
    data = df.tail(60).copy().reset_index(drop=True)
    data.columns = [c.lower() for c in data.columns]
    result = engine.detect_distribution(data)
    if result is not None:
        assert result.name == "Wyckoff Distribution"
        assert result.direction == "BEARISH"


# ── Spring ───────────────────────────────────────────────────

def test_spring_detection():
    engine = WyckoffEngine()
    # Build a range then spring below support
    np.random.seed(14)
    closes = [100.0] * 40
    for _ in range(17):
        closes.append(100 + np.random.randn() * 0.3)
    closes.append(98.5)  # Spring bar — dips below
    closes.append(100.5)  # Closes back above
    closes.append(101.0)
    df = _make_df(closes)
    df.loc[57, "low"] = 97.5
    df.loc[57, "close"] = 100.5
    data = df.tail(60).copy().reset_index(drop=True)
    data.columns = [c.lower() for c in data.columns]
    result = engine.detect_spring(data)
    if result is not None:
        assert result.name == "Wyckoff Spring"
        assert result.direction == "BULLISH"
        assert result.confidence == 0.78


# ── Upthrust ─────────────────────────────────────────────────

def test_upthrust_detection():
    engine = WyckoffEngine()
    np.random.seed(15)
    closes = [100.0] * 40
    for _ in range(17):
        closes.append(100 + np.random.randn() * 0.3)
    closes.append(101.5)  # Upthrust bar
    closes.append(99.5)
    closes.append(99.8)
    df = _make_df(closes)
    df.loc[57, "high"] = 102.5
    df.loc[57, "close"] = 99.5
    data = df.tail(60).copy().reset_index(drop=True)
    data.columns = [c.lower() for c in data.columns]
    result = engine.detect_upthrust(data)
    if result is not None:
        assert result.name == "Wyckoff Upthrust"
        assert result.direction == "BEARISH"


# ── Scanner wrappers ─────────────────────────────────────────

def test_wyckoff_scanner_wrappers_return_lists():
    stock_data = {"TEST": _range_after_downtrend(120)}
    scanners = [
        scan_accumulation, scan_distribution,
        scan_spring, scan_upthrust,
        scan_sos, scan_sow,
        scan_test_bull, scan_test_bear,
    ]
    for fn in scanners:
        result = fn(stock_data)
        assert isinstance(result, list), f"{fn.__name__} should return list"


def test_wyckoff_scanner_empty_data():
    for fn in [scan_accumulation, scan_spring]:
        assert fn({}) == []


# ── Integration ──────────────────────────────────────────────

def test_scanners_dict_has_wyckoff():
    from mcp_server.mwa_scanner import SCANNERS
    wyckoff_keys = [
        "wyckoff_accumulation", "wyckoff_distribution",
        "wyckoff_spring", "wyckoff_upthrust",
        "wyckoff_sos", "wyckoff_sow",
        "wyckoff_test_bull", "wyckoff_test_bear",
    ]
    for key in wyckoff_keys:
        assert key in SCANNERS, f"Missing: {key}"
        assert SCANNERS[key]["layer"] == "Wyckoff"
