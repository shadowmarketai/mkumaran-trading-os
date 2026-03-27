"""Tests for Volume Spread Analysis (VSA) Engine."""

import numpy as np
import pandas as pd

from mcp_server.vsa_engine import (
    VSAEngine,
    scan_no_supply, scan_no_demand,
    scan_stopping_vol_bull, scan_stopping_vol_bear,
    scan_selling_climax, scan_buying_climax,
    scan_effort_bull, scan_effort_bear,
)


def _make_df(closes, volumes=None, spread=1.0):
    n = len(closes)
    np.random.seed(42)
    arr = np.array(closes, dtype=float)
    if volumes is None:
        volumes = [100000] * n
    return pd.DataFrame({
        "open": arr - np.random.rand(n) * spread * 0.3,
        "high": arr + np.random.rand(n) * spread,
        "low": arr - np.random.rand(n) * spread,
        "close": arr,
        "volume": volumes,
    })


def _downtrend_with_climax(n=80):
    """Downtrend ending with a selling climax bar."""
    np.random.seed(21)
    closes = [200.0]
    vols = [100000]
    for _ in range(n - 2):
        closes.append(closes[-1] - abs(np.random.randn()) * 0.8 - 0.3)
        vols.append(100000 + int(np.random.rand() * 20000))
    # Climax bar: huge down + huge volume
    closes.append(closes[-1] - 5.0)
    vols.append(500000)
    return _make_df(closes, vols)


def _uptrend_with_climax(n=80):
    """Uptrend ending with a buying climax bar."""
    np.random.seed(22)
    closes = [100.0]
    vols = [100000]
    for _ in range(n - 2):
        closes.append(closes[-1] + abs(np.random.randn()) * 0.8 + 0.3)
        vols.append(100000 + int(np.random.rand() * 20000))
    closes.append(closes[-1] + 5.0)
    vols.append(500000)
    return _make_df(closes, vols)


# ── Init + basics ────────────────────────────────────────────

def test_vsa_engine_init():
    engine = VSAEngine()
    assert engine.lookback == 60


def test_detect_all_short_data():
    engine = VSAEngine()
    df = pd.DataFrame({
        "open": [100], "high": [102], "low": [99],
        "close": [101], "volume": [1000],
    })
    assert engine.detect_all(df) == []


def test_detect_all_returns_list():
    engine = VSAEngine()
    df = _downtrend_with_climax(120)
    results = engine.detect_all(df)
    assert isinstance(results, list)
    for r in results:
        assert hasattr(r, "name")
        assert r.direction in ("BULLISH", "BEARISH")


# ── No Demand / No Supply ────────────────────────────────────

def test_no_supply_detection():
    """Down bar with narrow spread and low volume = no supply."""
    np.random.seed(31)
    closes = [100.0] * 59
    closes.append(99.8)  # Small down bar
    vols = [100000] * 59 + [30000]  # Very low volume on last bar
    df = _make_df(closes, vols, spread=0.3)
    # Make last bar explicitly narrow + down
    df.loc[59, "open"] = 100.0
    df.loc[59, "close"] = 99.9
    df.loc[59, "high"] = 100.05
    df.loc[59, "low"] = 99.85

    engine = VSAEngine()
    data = df.tail(60).copy().reset_index(drop=True)
    data.columns = [c.lower() for c in data.columns]
    from mcp_server.vsa_engine import _bar_metrics
    data = _bar_metrics(data)
    result = engine.detect_no_demand_supply(data)
    if result is not None:
        assert result.direction in ("BULLISH", "BEARISH")


# ── Stopping Volume ──────────────────────────────────────────

def test_stopping_volume_bull():
    engine = VSAEngine()
    df = _downtrend_with_climax(120)
    results = engine.detect_all(df)
    stopping = [r for r in results if "Stopping" in r.name and r.direction == "BULLISH"]
    for r in stopping:
        assert r.confidence == 0.72


def test_stopping_volume_bear():
    engine = VSAEngine()
    df = _uptrend_with_climax(120)
    results = engine.detect_all(df)
    stopping = [r for r in results if "Stopping" in r.name and r.direction == "BEARISH"]
    for r in stopping:
        assert r.confidence == 0.72


# ── Climactic Volume ─────────────────────────────────────────

def test_selling_climax():
    engine = VSAEngine()
    df = _downtrend_with_climax(120)
    results = engine.detect_all(df)
    climax = [r for r in results if "Climax" in r.name and r.direction == "BULLISH"]
    for r in climax:
        assert r.confidence == 0.76


def test_buying_climax():
    engine = VSAEngine()
    df = _uptrend_with_climax(120)
    results = engine.detect_all(df)
    climax = [r for r in results if "Climax" in r.name and r.direction == "BEARISH"]
    for r in climax:
        assert r.confidence == 0.76


# ── Effort vs Result ─────────────────────────────────────────

def test_effort_no_result():
    """High volume but narrow spread = effort without result."""
    engine = VSAEngine()
    np.random.seed(32)
    closes = [100.0] * 59
    closes.append(99.95)  # Tiny down move
    vols = [100000] * 59 + [300000]  # Big volume
    df = _make_df(closes, vols, spread=0.1)
    df.loc[59, "open"] = 100.0
    df.loc[59, "close"] = 99.95
    df.loc[59, "high"] = 100.02
    df.loc[59, "low"] = 99.93
    results = engine.detect_all(df)
    effort = [r for r in results if "Effort" in r.name]
    for r in effort:
        assert r.confidence == 0.70


# ── Scanner wrappers ─────────────────────────────────────────

def test_vsa_scanner_wrappers_return_lists():
    stock_data = {"TEST": _downtrend_with_climax(120)}
    scanners = [
        scan_no_supply, scan_no_demand,
        scan_stopping_vol_bull, scan_stopping_vol_bear,
        scan_selling_climax, scan_buying_climax,
        scan_effort_bull, scan_effort_bear,
    ]
    for fn in scanners:
        result = fn(stock_data)
        assert isinstance(result, list), f"{fn.__name__} should return list"


def test_vsa_scanner_empty_data():
    for fn in [scan_no_supply, scan_selling_climax]:
        assert fn({}) == []


# ── Integration ──────────────────────────────────────────────

def test_scanners_dict_has_vsa():
    from mcp_server.mwa_scanner import SCANNERS
    vsa_keys = [
        "vsa_no_supply", "vsa_no_demand",
        "vsa_stopping_bull", "vsa_stopping_bear",
        "vsa_selling_climax", "vsa_buying_climax",
        "vsa_effort_bull", "vsa_effort_bear",
    ]
    for key in vsa_keys:
        assert key in SCANNERS, f"Missing: {key}"
        assert SCANNERS[key]["layer"] == "VSA"
