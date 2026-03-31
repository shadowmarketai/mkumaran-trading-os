"""Tests for Commodity (MCX) Scanners — 8 scanners (91-98)."""

import numpy as np
import pandas as pd

from mcp_server.commodity_scanners import (
    scan_mcx_ema_crossover,
    scan_mcx_ema_crossover_bear,
    scan_mcx_rsi_oversold,
    scan_mcx_rsi_overbought,
    scan_mcx_gold_silver_ratio,
    scan_mcx_gold_silver_ratio_bear,
    scan_mcx_crude_momentum,
    scan_mcx_metal_strength,
)


def _make_mcx_df(closes, volume=50000):
    n = len(closes)
    arr = np.array(closes, dtype=float)
    return pd.DataFrame({
        "open": arr - 5,
        "high": arr + 10,
        "low": arr - 10,
        "close": arr,
        "volume": [volume] * n,
    })


def _mock_mcx_data():
    """Create mock stock_data with MCX tickers."""
    gold_prices = list(np.linspace(58000, 62000, 50))
    silver_prices = list(np.linspace(72000, 75000, 50))
    crude_prices = list(np.linspace(5500, 6000, 50))
    return {
        "GOLD": _make_mcx_df(gold_prices),
        "SILVER": _make_mcx_df(silver_prices),
        "CRUDEOIL": _make_mcx_df(crude_prices),
        "NATURALGAS": _make_mcx_df(list(np.linspace(200, 250, 50))),
        "COPPER": _make_mcx_df(list(np.linspace(700, 750, 50))),
    }


# ── Return type tests ─────────────────────────────────────────

def test_scan_mcx_ema_crossover_returns_list():
    result = scan_mcx_ema_crossover(_mock_mcx_data())
    assert isinstance(result, list)


def test_scan_mcx_ema_crossover_bear_returns_list():
    result = scan_mcx_ema_crossover_bear(_mock_mcx_data())
    assert isinstance(result, list)


def test_scan_mcx_rsi_oversold_returns_list():
    result = scan_mcx_rsi_oversold(_mock_mcx_data())
    assert isinstance(result, list)


def test_scan_mcx_rsi_overbought_returns_list():
    result = scan_mcx_rsi_overbought(_mock_mcx_data())
    assert isinstance(result, list)


def test_scan_mcx_gold_silver_ratio_returns_list():
    result = scan_mcx_gold_silver_ratio(_mock_mcx_data())
    assert isinstance(result, list)


def test_scan_mcx_gold_silver_ratio_bear_returns_list():
    result = scan_mcx_gold_silver_ratio_bear(_mock_mcx_data())
    assert isinstance(result, list)


def test_scan_mcx_crude_momentum_returns_list():
    result = scan_mcx_crude_momentum(_mock_mcx_data())
    assert isinstance(result, list)


def test_scan_mcx_metal_strength_returns_list():
    result = scan_mcx_metal_strength(_mock_mcx_data())
    assert isinstance(result, list)


# ── Empty data handling ────────────────────────────────────────

def test_all_scanners_handle_empty_data():
    empty_data: dict[str, pd.DataFrame] = {}
    for scanner_fn in [
        scan_mcx_ema_crossover, scan_mcx_ema_crossover_bear,
        scan_mcx_rsi_oversold, scan_mcx_rsi_overbought,
        scan_mcx_gold_silver_ratio, scan_mcx_gold_silver_ratio_bear,
        scan_mcx_crude_momentum, scan_mcx_metal_strength,
    ]:
        result = scanner_fn(empty_data)
        assert result == [], f"{scanner_fn.__name__} should return [] for empty data"


def test_all_scanners_handle_short_data():
    short_data = {"GOLD": _make_mcx_df([58000, 58500, 59000])}
    for scanner_fn in [
        scan_mcx_ema_crossover, scan_mcx_ema_crossover_bear,
        scan_mcx_rsi_oversold, scan_mcx_rsi_overbought,
        scan_mcx_gold_silver_ratio, scan_mcx_gold_silver_ratio_bear,
        scan_mcx_crude_momentum, scan_mcx_metal_strength,
    ]:
        result = scanner_fn(short_data)
        assert isinstance(result, list), f"{scanner_fn.__name__} should return list for short data"


# ── Filter tests ───────────────────────────────────────────────

def test_scanners_ignore_non_mcx_tickers():
    """Non-MCX tickers should not appear in results."""
    data = {
        "RELIANCE": _make_mcx_df(list(np.linspace(2500, 2700, 50))),
        "GOLD": _make_mcx_df(list(np.linspace(58000, 62000, 50))),
    }
    result = scan_mcx_ema_crossover(data)
    for ticker in result:
        assert "RELIANCE" not in ticker.upper()


# ── Gold/Silver ratio paired data test ─────────────────────────

def test_gold_silver_ratio_with_paired_data():
    """Gold/silver ratio scanner needs both GOLD and SILVER data."""
    # Only gold, no silver — should return empty
    gold_only = {"GOLD": _make_mcx_df(list(np.linspace(58000, 62000, 50)))}
    result = scan_mcx_gold_silver_ratio(gold_only)
    assert result == []

    # Only silver, no gold — should return empty
    silver_only = {"SILVER": _make_mcx_df(list(np.linspace(72000, 75000, 50)))}
    result = scan_mcx_gold_silver_ratio(silver_only)
    assert result == []


def test_gold_silver_ratio_bear_with_paired_data():
    """Gold/silver ratio bear scanner needs both GOLD and SILVER data."""
    gold_only = {"GOLD": _make_mcx_df(list(np.linspace(58000, 62000, 50)))}
    result = scan_mcx_gold_silver_ratio_bear(gold_only)
    assert result == []


# ── Specific signal detection ──────────────────────────────────

def test_crude_momentum_targets_energy():
    """Crude momentum scanner should only look at energy tickers."""
    data = {
        "GOLD": _make_mcx_df(list(np.linspace(58000, 62000, 50))),
        "CRUDEOIL": _make_mcx_df(list(np.linspace(5500, 6000, 50))),
    }
    result = scan_mcx_crude_momentum(data)
    # GOLD should never appear in crude momentum results
    for ticker in result:
        clean = ticker.upper().replace("MCX:", "")
        assert clean in {"CRUDEOIL", "CL=F", "NATURALGAS", "NG=F"}
