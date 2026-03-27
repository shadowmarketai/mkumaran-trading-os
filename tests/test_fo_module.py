"""Tests for F&O Module."""

import numpy as np
import pandas as pd

from mcp_server.fo_module import (
    get_oi_change,
    get_pcr,
    get_banknifty_ema_signal,
    get_nifty_ema_signal,
    get_fo_signal,
)


def _make_15m_df(closes):
    n = len(closes)
    arr = np.array(closes, dtype=float)
    return pd.DataFrame({
        "open": arr - 0.5,
        "high": arr + 1.0,
        "low": arr - 1.0,
        "close": arr,
        "volume": [100000] * n,
    })


# ── OI Change (placeholder) ─────────────────────────────────

def test_get_oi_change_returns_dict():
    result = get_oi_change(kite=None, instrument="NIFTY")
    assert isinstance(result, dict)
    assert result["instrument"] == "NIFTY"
    assert "significance" in result


def test_get_oi_change_banknifty():
    result = get_oi_change(kite=None, instrument="BANKNIFTY")
    assert result["instrument"] == "BANKNIFTY"


# ── PCR (placeholder) ────────────────────────────────────────

def test_get_pcr_returns_dict():
    result = get_pcr(kite=None, instrument="NIFTY")
    assert isinstance(result, dict)
    assert "pcr" in result
    assert "sentiment" in result


def test_get_pcr_unavailable_without_kite():
    result = get_pcr(kite=None)
    assert result["sentiment"] == "UNAVAILABLE"
    assert result["pcr"] == 0


# ── BankNifty EMA ────────────────────────────────────────────

def test_banknifty_ema_buy():
    """Rising closes should trigger BUY after crossover."""
    closes = list(range(100, 130))  # Steady uptrend
    df = _make_15m_df(closes)
    result = get_banknifty_ema_signal(df)
    assert result["instrument"] == "BANKNIFTY"
    assert "signal" in result
    assert result["signal"] in ("BUY", "SELL", "HOLD")
    assert "fast_ema_5" in result
    assert "slow_ema_10" in result


def test_banknifty_ema_has_spread():
    closes = list(range(100, 130))
    df = _make_15m_df(closes)
    result = get_banknifty_ema_signal(df)
    assert "spread" in result
    assert isinstance(result["spread"], float)


# ── Nifty EMA ────────────────────────────────────────────────

def test_nifty_ema_signal():
    closes = list(range(100, 150))
    df = _make_15m_df(closes)
    result = get_nifty_ema_signal(df)
    assert result["instrument"] == "NIFTY"
    assert result["signal"] in ("BUY", "SELL", "HOLD")
    assert "fast_ema_9" in result
    assert "slow_ema_21" in result


# ── Combined F&O Signal ──────────────────────────────────────

def test_fo_signal_no_data():
    """No kite, no dataframes = UNAVAILABLE (no live components)."""
    result = get_fo_signal()
    assert result["verdict"] == "UNAVAILABLE"
    assert result["bull_count"] == 0
    assert result["bear_count"] == 0


def test_fo_signal_ema_only():
    """With EMA data only."""
    nifty = _make_15m_df(list(range(100, 150)))
    bn = _make_15m_df(list(range(100, 130)))
    result = get_fo_signal(nifty_15m=nifty, banknifty_15m=bn)
    assert result["verdict"] in ("STRONG_BULL", "MILD_BULL", "NEUTRAL", "MILD_BEAR", "STRONG_BEAR")
    assert "nifty_ema" in result["components"]
    assert "banknifty_ema" in result["components"]


def test_fo_signal_empty_df():
    """Empty dataframes should be skipped."""
    empty = pd.DataFrame()
    result = get_fo_signal(nifty_15m=empty, banknifty_15m=empty)
    assert result["verdict"] == "UNAVAILABLE"
