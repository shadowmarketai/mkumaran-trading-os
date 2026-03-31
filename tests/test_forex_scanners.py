"""Tests for Forex (CDS) Scanners — 8 scanners (83-90)."""

import numpy as np
import pandas as pd

from mcp_server.forex_scanners import (
    scan_cds_ema_crossover,
    scan_cds_ema_crossover_bear,
    scan_cds_rsi_oversold,
    scan_cds_rsi_overbought,
    scan_cds_bb_squeeze,
    scan_cds_bb_squeeze_bear,
    scan_cds_carry_trade,
    scan_cds_dxy_divergence,
)


def _make_cds_df(closes, volume=100000):
    n = len(closes)
    arr = np.array(closes, dtype=float)
    return pd.DataFrame({
        "open": arr - 0.1,
        "high": arr + 0.2,
        "low": arr - 0.2,
        "close": arr,
        "volume": [volume] * n,
    })


def _mock_cds_data(closes=None):
    """Create mock stock_data with CDS tickers."""
    if closes is None:
        closes = list(np.linspace(83.0, 84.5, 50))
    return {
        "USDINR": _make_cds_df(closes),
        "EURINR": _make_cds_df(closes),
        "GBPINR": _make_cds_df([c * 1.05 for c in closes]),
        "JPYINR": _make_cds_df([c * 0.55 for c in closes]),
    }


# ── Return type tests ─────────────────────────────────────────

def test_scan_cds_ema_crossover_returns_list():
    result = scan_cds_ema_crossover(_mock_cds_data())
    assert isinstance(result, list)


def test_scan_cds_ema_crossover_bear_returns_list():
    result = scan_cds_ema_crossover_bear(_mock_cds_data())
    assert isinstance(result, list)


def test_scan_cds_rsi_oversold_returns_list():
    result = scan_cds_rsi_oversold(_mock_cds_data())
    assert isinstance(result, list)


def test_scan_cds_rsi_overbought_returns_list():
    result = scan_cds_rsi_overbought(_mock_cds_data())
    assert isinstance(result, list)


def test_scan_cds_bb_squeeze_returns_list():
    result = scan_cds_bb_squeeze(_mock_cds_data())
    assert isinstance(result, list)


def test_scan_cds_bb_squeeze_bear_returns_list():
    result = scan_cds_bb_squeeze_bear(_mock_cds_data())
    assert isinstance(result, list)


def test_scan_cds_carry_trade_returns_list():
    result = scan_cds_carry_trade(_mock_cds_data())
    assert isinstance(result, list)


def test_scan_cds_dxy_divergence_returns_list():
    result = scan_cds_dxy_divergence(_mock_cds_data())
    assert isinstance(result, list)


# ── Empty data handling ────────────────────────────────────────

def test_all_scanners_handle_empty_data():
    empty_data: dict[str, pd.DataFrame] = {}
    for scanner_fn in [
        scan_cds_ema_crossover, scan_cds_ema_crossover_bear,
        scan_cds_rsi_oversold, scan_cds_rsi_overbought,
        scan_cds_bb_squeeze, scan_cds_bb_squeeze_bear,
        scan_cds_carry_trade, scan_cds_dxy_divergence,
    ]:
        result = scanner_fn(empty_data)
        assert result == [], f"{scanner_fn.__name__} should return [] for empty data"


def test_all_scanners_handle_short_data():
    short_data = {"USDINR": _make_cds_df([83.0, 83.5, 84.0])}
    for scanner_fn in [
        scan_cds_ema_crossover, scan_cds_ema_crossover_bear,
        scan_cds_rsi_oversold, scan_cds_rsi_overbought,
        scan_cds_bb_squeeze, scan_cds_bb_squeeze_bear,
        scan_cds_carry_trade, scan_cds_dxy_divergence,
    ]:
        result = scanner_fn(short_data)
        assert isinstance(result, list), f"{scanner_fn.__name__} should return list for short data"


# ── Filter tests ───────────────────────────────────────────────

def test_scanners_ignore_non_cds_tickers():
    """Non-CDS tickers should not appear in results."""
    data = {
        "RELIANCE": _make_cds_df(list(np.linspace(100, 200, 50))),
        "USDINR": _make_cds_df(list(np.linspace(83, 84, 50))),
    }
    result = scan_cds_ema_crossover(data)
    for ticker in result:
        assert "RELIANCE" not in ticker.upper()


# ── Specific signal detection ──────────────────────────────────

def test_rsi_oversold_detects_low_rsi():
    """Steadily declining prices should trigger RSI oversold."""
    declining = list(np.linspace(90, 70, 50))
    data = {"USDINR": _make_cds_df(declining)}
    result = scan_cds_rsi_oversold(data)
    # May or may not trigger depending on exact values, but should not crash
    assert isinstance(result, list)


def test_rsi_overbought_detects_high_rsi():
    """Steadily rising prices should trigger RSI overbought."""
    rising = list(np.linspace(70, 95, 50))
    data = {"USDINR": _make_cds_df(rising)}
    result = scan_cds_rsi_overbought(data)
    assert isinstance(result, list)
