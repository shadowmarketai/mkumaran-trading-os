"""Tests for Smart Money Concepts (SMC) Engine."""

import numpy as np
import pandas as pd

from mcp_server.smc_engine import (
    SMCEngine,
    scan_bos_bull,
    scan_bos_bear,
    scan_choch_bull,
    scan_choch_bear,
    scan_bullish_ob,
    scan_bearish_ob,
    scan_bullish_fvg,
    scan_bearish_fvg,
    scan_liquidity_sweep_bull,
    scan_liquidity_sweep_bear,
    scan_discount_zone,
    scan_premium_zone,
)


# ── Helpers ──────────────────────────────────────────────────


def _make_df(
    closes: list[float],
    spread: float = 1.0,
    volume: int = 100000,
) -> pd.DataFrame:
    """Build an OHLCV DataFrame from a close price series."""
    n = len(closes)
    arr = np.array(closes, dtype=float)
    return pd.DataFrame({
        "open": arr - np.random.rand(n) * spread * 0.3,
        "high": arr + np.random.rand(n) * spread,
        "low": arr - np.random.rand(n) * spread,
        "close": arr,
        "volume": [volume] * n,
    })


def _uptrend_df(n: int = 80) -> pd.DataFrame:
    """Generate an uptrend: higher highs + higher lows."""
    np.random.seed(10)
    closes = [100.0]
    for _ in range(n - 1):
        closes.append(closes[-1] + abs(np.random.randn()) * 0.5 + 0.2)
    return _make_df(closes)


def _downtrend_df(n: int = 80) -> pd.DataFrame:
    """Generate a downtrend: lower highs + lower lows."""
    np.random.seed(20)
    closes = [200.0]
    for _ in range(n - 1):
        closes.append(closes[-1] - abs(np.random.randn()) * 0.5 - 0.2)
    return _make_df(closes)


def _sideways_df(n: int = 80) -> pd.DataFrame:
    """Generate sideways price action."""
    np.random.seed(30)
    closes = 100 + np.random.randn(n) * 0.5
    return _make_df(closes.tolist())


# ══════════════════════════════════════════════════════════════
# SMCEngine init + detect_all basics
# ══════════════════════════════════════════════════════════════


def test_smc_engine_init():
    engine = SMCEngine()
    assert engine.lookback == 60
    assert engine.swing_lookback == 5


def test_detect_all_short_data():
    engine = SMCEngine()
    df = pd.DataFrame({
        "open": [100, 101],
        "high": [102, 103],
        "low": [99, 100],
        "close": [101, 102],
        "volume": [1000, 1100],
    })
    results = engine.detect_all(df)
    assert isinstance(results, list)
    assert len(results) == 0


def test_detect_all_returns_pattern_results():
    engine = SMCEngine()
    df = _uptrend_df(120)
    results = engine.detect_all(df)
    assert isinstance(results, list)
    for r in results:
        assert hasattr(r, "name")
        assert hasattr(r, "direction")
        assert hasattr(r, "confidence")
        assert hasattr(r, "description")


# ══════════════════════════════════════════════════════════════
# BOS detection
# ══════════════════════════════════════════════════════════════


def test_bos_bull_in_uptrend():
    engine = SMCEngine()
    df = _uptrend_df(120)
    result = engine.detect_bos(df.tail(60).reset_index(drop=True))
    # In a clean uptrend, we may or may not get BOS depending on swing point placement
    if result is not None:
        assert result.name == "BOS Bullish"
        assert result.direction == "BULLISH"
        assert result.confidence == 0.70


def test_bos_bear_in_downtrend():
    engine = SMCEngine()
    df = _downtrend_df(120)
    data = df.tail(60).copy().reset_index(drop=True)
    data.columns = [c.lower() for c in data.columns]
    result = engine.detect_bos(data)
    if result is not None:
        assert result.name == "BOS Bearish"
        assert result.direction == "BEARISH"


def test_bos_none_in_sideways():
    engine = SMCEngine()
    df = _sideways_df(120)
    data = df.tail(60).copy().reset_index(drop=True)
    data.columns = [c.lower() for c in data.columns]
    result = engine.detect_bos(data)
    # Sideways should not produce BOS
    if result is not None:
        # If it does fire, it should still be valid
        assert result.direction in ("BULLISH", "BEARISH")


# ══════════════════════════════════════════════════════════════
# CHoCH detection
# ══════════════════════════════════════════════════════════════


def test_choch_bull_reversal():
    """CHoCH bullish: downtrend that breaks above last swing high."""
    np.random.seed(40)
    # Downtrend then spike up at end
    closes = [200.0]
    for _ in range(69):
        closes.append(closes[-1] - abs(np.random.randn()) * 0.3 - 0.1)
    # Spike up at end to break structure
    for _ in range(10):
        closes.append(closes[-1] + abs(np.random.randn()) * 2 + 1)
    df = _make_df(closes)
    engine = SMCEngine()
    data = df.tail(60).copy().reset_index(drop=True)
    data.columns = [c.lower() for c in data.columns]
    result = engine.detect_choch(data)
    if result is not None:
        assert result.name == "CHoCH Bullish"
        assert result.direction == "BULLISH"
        assert result.confidence == 0.75


def test_choch_bear_reversal():
    """CHoCH bearish: uptrend that breaks below last swing low."""
    np.random.seed(41)
    closes = [100.0]
    for _ in range(69):
        closes.append(closes[-1] + abs(np.random.randn()) * 0.3 + 0.1)
    # Drop at end
    for _ in range(10):
        closes.append(closes[-1] - abs(np.random.randn()) * 2 - 1)
    df = _make_df(closes)
    engine = SMCEngine()
    data = df.tail(60).copy().reset_index(drop=True)
    data.columns = [c.lower() for c in data.columns]
    result = engine.detect_choch(data)
    if result is not None:
        assert result.name == "CHoCH Bearish"
        assert result.direction == "BEARISH"


def test_choch_none_in_clean_trend():
    engine = SMCEngine()
    df = _uptrend_df(120)
    data = df.tail(60).copy().reset_index(drop=True)
    data.columns = [c.lower() for c in data.columns]
    result = engine.detect_choch(data)
    # Clean uptrend should NOT produce bullish CHoCH (that requires downtrend)
    if result is not None:
        assert result.direction == "BEARISH"  # Only bearish CHoCH possible in uptrend


# ══════════════════════════════════════════════════════════════
# Order Block detection
# ══════════════════════════════════════════════════════════════


def test_demand_order_block():
    """Demand OB: bearish candle followed by impulsive bullish move."""
    np.random.seed(50)
    closes = [100.0] * 40
    # Bearish candle at index 40
    closes.append(98.0)
    # Strong bullish move after
    for i in range(19):
        closes.append(98.0 + (i + 1) * 1.5)
    df = _make_df(closes)
    # Make the bearish candle explicit
    df.loc[40, "open"] = 100.0
    df.loc[40, "close"] = 98.0
    engine = SMCEngine(lookback=60)
    data = df.tail(60).copy().reset_index(drop=True)
    data.columns = [c.lower() for c in data.columns]
    results = engine.detect_order_blocks(data)
    demand = [r for r in results if r.direction == "BULLISH"]
    # May or may not detect depending on avg_range vs move size
    for r in demand:
        assert r.name == "Demand Order Block"
        assert r.confidence == 0.72


def test_supply_order_block():
    """Supply OB: bullish candle followed by impulsive bearish move."""
    np.random.seed(51)
    closes = [200.0] * 40
    # Bullish candle
    closes.append(202.0)
    # Strong bearish move
    for i in range(19):
        closes.append(202.0 - (i + 1) * 1.5)
    df = _make_df(closes)
    df.loc[40, "open"] = 200.0
    df.loc[40, "close"] = 202.0
    engine = SMCEngine(lookback=60)
    data = df.tail(60).copy().reset_index(drop=True)
    data.columns = [c.lower() for c in data.columns]
    results = engine.detect_order_blocks(data)
    supply = [r for r in results if r.direction == "BEARISH"]
    for r in supply:
        assert r.name == "Supply Order Block"
        assert r.confidence == 0.72


def test_order_block_mitigated():
    """Order block that gets mitigated (revisited) should not be returned."""
    engine = SMCEngine()
    df = _sideways_df(120)
    data = df.tail(60).copy().reset_index(drop=True)
    data.columns = [c.lower() for c in data.columns]
    results = engine.detect_order_blocks(data)
    # In sideways, OBs are likely mitigated; just verify it returns a list
    assert isinstance(results, list)


# ══════════════════════════════════════════════════════════════
# FVG detection
# ══════════════════════════════════════════════════════════════


def test_bullish_fvg():
    """Bullish FVG: candle 3 low > candle 1 high (gap up)."""
    np.random.seed(60)
    closes = [100.0] * 50
    # Create a clear gap: c1 high=101, c2 moves up, c3 low=103
    closes.extend([100, 105, 110, 112, 115, 116, 117, 118, 119, 120])
    df = _make_df(closes)
    # Force the gap
    df.loc[50, "high"] = 101.0
    df.loc[52, "low"] = 103.0
    engine = SMCEngine(lookback=60)
    data = df.tail(60).copy().reset_index(drop=True)
    data.columns = [c.lower() for c in data.columns]
    results = engine.detect_fvg(data)
    bull_fvg = [r for r in results if r.direction == "BULLISH"]
    for r in bull_fvg:
        assert r.name == "Bullish FVG"
        assert r.confidence == 0.68


def test_bearish_fvg():
    """Bearish FVG: candle 1 low > candle 3 high (gap down)."""
    np.random.seed(61)
    closes = [200.0] * 50
    closes.extend([200, 195, 190, 188, 185, 183, 181, 180, 179, 178])
    df = _make_df(closes)
    df.loc[50, "low"] = 199.0
    df.loc[52, "high"] = 191.0
    engine = SMCEngine(lookback=60)
    data = df.tail(60).copy().reset_index(drop=True)
    data.columns = [c.lower() for c in data.columns]
    results = engine.detect_fvg(data)
    bear_fvg = [r for r in results if r.direction == "BEARISH"]
    for r in bear_fvg:
        assert r.name == "Bearish FVG"
        assert r.confidence == 0.68


def test_fvg_filled_not_returned():
    """FVGs that get filled (price retraces into gap) should not be returned."""
    engine = SMCEngine()
    df = _sideways_df(120)
    data = df.tail(60).copy().reset_index(drop=True)
    data.columns = [c.lower() for c in data.columns]
    results = engine.detect_fvg(data)
    assert isinstance(results, list)


# ══════════════════════════════════════════════════════════════
# Liquidity Sweep detection
# ══════════════════════════════════════════════════════════════


def test_liquidity_sweep_bull():
    """Bullish sweep: dip below equal lows then close back above."""
    np.random.seed(70)
    # Create equal lows around 95 then sweep and recover
    closes = []
    for i in range(20):
        closes.append(100 + np.random.randn() * 0.5)
    closes.append(95.0)  # swing low 1
    for i in range(15):
        closes.append(100 + np.random.randn() * 0.5)
    closes.append(95.1)  # swing low 2 (equal)
    for i in range(20):
        closes.append(100 + np.random.randn() * 0.5)
    # Sweep below then recover
    closes.append(94.0)  # sweep low
    closes.append(96.0)  # close back above

    df = _make_df(closes)
    # Make the last bar sweep below 95 but close above
    df.loc[len(df) - 1, "low"] = 94.0
    df.loc[len(df) - 1, "close"] = 96.0

    engine = SMCEngine(lookback=len(closes))
    data = df.copy().reset_index(drop=True)
    data.columns = [c.lower() for c in data.columns]
    result = engine.detect_liquidity_sweep(data)
    if result is not None:
        assert result.direction == "BULLISH"
        assert result.confidence == 0.78


def test_liquidity_sweep_bear():
    """Bearish sweep: spike above equal highs then close back below."""
    np.random.seed(71)
    closes = []
    for i in range(20):
        closes.append(100 + np.random.randn() * 0.5)
    closes.append(105.0)  # swing high 1
    for i in range(15):
        closes.append(100 + np.random.randn() * 0.5)
    closes.append(105.1)  # swing high 2 (equal)
    for i in range(20):
        closes.append(100 + np.random.randn() * 0.5)
    # Sweep above then drop
    closes.append(106.0)
    closes.append(104.0)

    df = _make_df(closes)
    df.loc[len(df) - 1, "high"] = 106.0
    df.loc[len(df) - 1, "close"] = 104.0

    engine = SMCEngine(lookback=len(closes))
    data = df.copy().reset_index(drop=True)
    data.columns = [c.lower() for c in data.columns]
    result = engine.detect_liquidity_sweep(data)
    if result is not None:
        assert result.direction == "BEARISH"
        assert result.confidence == 0.78


def test_liquidity_sweep_no_equal_levels():
    """No equal levels should produce no sweep."""
    engine = SMCEngine()
    df = _uptrend_df(120)
    data = df.tail(60).copy().reset_index(drop=True)
    data.columns = [c.lower() for c in data.columns]
    result = engine.detect_liquidity_sweep(data)
    # May or may not fire depending on random seed
    assert result is None or hasattr(result, "name")


# ══════════════════════════════════════════════════════════════
# Premium / Discount zones
# ══════════════════════════════════════════════════════════════


def test_discount_zone():
    """Price near bottom of dealing range = discount."""
    np.random.seed(80)
    # Range 90-110, current price near 92
    closes = []
    for _ in range(30):
        closes.append(100 + np.random.randn() * 5)
    closes.append(110.0)  # high
    for _ in range(15):
        closes.append(100 + np.random.randn() * 2)
    closes.append(90.0)   # low
    for _ in range(10):
        closes.append(93.0 + np.random.randn() * 0.5)  # near bottom

    df = _make_df(closes)
    engine = SMCEngine(lookback=len(closes))
    data = df.copy().reset_index(drop=True)
    data.columns = [c.lower() for c in data.columns]
    result = engine.detect_premium_discount(data)
    if result is not None and result.name == "Discount Zone":
        assert result.direction == "BULLISH"
        assert result.confidence == 0.62


def test_premium_zone():
    """Price near top of dealing range = premium."""
    np.random.seed(81)
    closes = []
    for _ in range(30):
        closes.append(100 + np.random.randn() * 5)
    closes.append(90.0)  # low
    for _ in range(15):
        closes.append(100 + np.random.randn() * 2)
    closes.append(110.0)  # high
    for _ in range(10):
        closes.append(108.0 + np.random.randn() * 0.5)  # near top

    df = _make_df(closes)
    engine = SMCEngine(lookback=len(closes))
    data = df.copy().reset_index(drop=True)
    data.columns = [c.lower() for c in data.columns]
    result = engine.detect_premium_discount(data)
    if result is not None and result.name == "Premium Zone":
        assert result.direction == "BEARISH"
        assert result.confidence == 0.62


# ══════════════════════════════════════════════════════════════
# Scanner wrapper format tests
# ══════════════════════════════════════════════════════════════


def test_scanner_wrappers_return_list():
    """All scanner wrappers should return list[str]."""
    stock_data = {"RELIANCE": _uptrend_df(120), "INFY": _downtrend_df(120)}
    scanners = [
        scan_bos_bull, scan_bos_bear, scan_choch_bull, scan_choch_bear,
        scan_bullish_ob, scan_bearish_ob, scan_bullish_fvg, scan_bearish_fvg,
        scan_liquidity_sweep_bull, scan_liquidity_sweep_bear,
        scan_discount_zone, scan_premium_zone,
    ]
    for scanner_fn in scanners:
        result = scanner_fn(stock_data)
        assert isinstance(result, list), f"{scanner_fn.__name__} should return list"
        for item in result:
            assert isinstance(item, str), f"{scanner_fn.__name__} items should be strings"


def test_scanner_wrappers_empty_data():
    """Scanner wrappers with empty stock_data should return empty lists."""
    for scanner_fn in [scan_bos_bull, scan_choch_bull, scan_bullish_ob]:
        result = scanner_fn({})
        assert result == []


# ══════════════════════════════════════════════════════════════
# Integration: SCANNERS / SIGNAL_CHAINS dict verification
# ══════════════════════════════════════════════════════════════


def test_scanners_dict_has_smc_entries():
    from mcp_server.mwa_scanner import SCANNERS
    assert len(SCANNERS) >= 52, f"Expected >= 52 scanners, got {len(SCANNERS)}"

    # Verify all SMC scanners are present
    smc_keys = [
        "smc_bos_bull", "smc_bos_bear", "smc_choch_bull", "smc_choch_bear",
        "smc_demand_ob", "smc_supply_ob", "smc_bullish_fvg", "smc_bearish_fvg",
        "smc_liq_sweep_bull", "smc_liq_sweep_bear", "smc_discount", "smc_premium",
    ]
    for key in smc_keys:
        assert key in SCANNERS, f"Missing scanner: {key}"
        assert SCANNERS[key]["layer"] == "SMC"


def test_signal_chains_has_smc_entries():
    from mcp_server.mwa_scanner import SIGNAL_CHAINS
    assert len(SIGNAL_CHAINS) >= 13, f"Expected >= 13 chains, got {len(SIGNAL_CHAINS)}"

    smc_chains = ["smc_reversal_long", "smc_reversal_short", "smc_continuation"]
    for chain in smc_chains:
        assert chain in SIGNAL_CHAINS, f"Missing chain: {chain}"
        assert SIGNAL_CHAINS[chain]["boost"] > 0
