"""Smoke tests for tradingview_scanner.

These hit the live scanner.tradingview.com endpoint, so they are marked
`network` and can be skipped with `pytest -m "not network"`. When the
tradingview-screener library is not installed, or when the opt-in flag is
off, the module must still import cleanly and return [].
"""

from __future__ import annotations

import os

import pytest


def test_module_imports_without_flag():
    # Imports must succeed even without TRADINGVIEW_SCANNER_ENABLED set.
    from mcp_server import tradingview_scanner as tv

    assert tv.available_scanners(), "SCANNERS registry must not be empty"
    assert "swing_low" in tv.available_scanners()
    assert "breakout_200dma" in tv.available_scanners()


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("TRADINGVIEW_SCANNER_ENABLED", raising=False)
    # Force module reload so _ENABLED re-reads env.
    import importlib

    from mcp_server import tradingview_scanner as tv

    importlib.reload(tv)
    # Disabled flag → every call returns [] without any network IO.
    assert tv.is_available() is False
    assert tv.run_scanner("swing_low") == []


def test_merge_with_chartink_union_preserves_order():
    from mcp_server.tradingview_scanner import merge_with_chartink

    chartink = {
        "swing_low": ["RELIANCE", "TCS"],
        "breakout_200dma": ["HDFCBANK"],
    }
    tv = {
        "swing_low": ["TCS", "INFY"],  # TCS is dup, INFY is new
        "macd_buy_daily": ["ITC"],  # key only in TV
    }
    merged = merge_with_chartink(chartink, tv)
    assert merged["swing_low"] == ["RELIANCE", "TCS", "INFY"]
    assert merged["breakout_200dma"] == ["HDFCBANK"]
    assert merged["macd_buy_daily"] == ["ITC"]


@pytest.mark.network
def test_run_scanner_live_rsi_above_30(monkeypatch):
    # Live smoke test — hits TradingView. Only runs when the opt-in flag
    # is explicitly set (mirrors production config).
    if not os.environ.get("TRADINGVIEW_SCANNER_ENABLED"):
        pytest.skip("set TRADINGVIEW_SCANNER_ENABLED=true to run live smoke test")

    import importlib

    from mcp_server import tradingview_scanner as tv

    importlib.reload(tv)
    symbols = tv.run_scanner("rsi_above_30", limit=50)
    # rsi_above_30 is the widest NSE filter we ship; if this returns []
    # the lib or endpoint is broken.
    assert len(symbols) > 0, "rsi_above_30 returned zero NSE symbols"
    assert all(isinstance(s, str) and ":" not in s for s in symbols), (
        "symbols must be plain NSE codes without exchange prefix"
    )
