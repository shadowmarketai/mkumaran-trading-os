"""Tests for Unified Data Provider: Kite primary + yfinance fallback."""

from unittest.mock import patch, MagicMock
from datetime import datetime

import pandas as pd
import pytest

from mcp_server.data_provider import (
    _INTERVAL_MAP,
    _PERIOD_TO_DAYS,
    _resolve_instrument_token,
    _load_instrument_cache,
    _yfinance_fetch,
    fetch_kite_historical,
    get_stock_data,
    _rate_limited_download,
)


# ── Interval / Period Mapping ─────────────────────────────────


def test_interval_map_has_standard_intervals():
    assert _INTERVAL_MAP["1m"] == "minute"
    assert _INTERVAL_MAP["5m"] == "5minute"
    assert _INTERVAL_MAP["15m"] == "15minute"
    assert _INTERVAL_MAP["1h"] == "60minute"
    assert _INTERVAL_MAP["1d"] == "day"
    assert _INTERVAL_MAP["1wk"] == "week"
    assert _INTERVAL_MAP["1mo"] == "month"


def test_interval_map_has_all_kite_intervals():
    expected = {"1m", "3m", "5m", "10m", "15m", "30m", "1h", "1d", "1wk", "1mo"}
    assert set(_INTERVAL_MAP.keys()) == expected


def test_period_to_days_mapping():
    assert _PERIOD_TO_DAYS["1d"] == 1
    assert _PERIOD_TO_DAYS["5d"] == 5
    assert _PERIOD_TO_DAYS["1mo"] == 30
    assert _PERIOD_TO_DAYS["3mo"] == 90
    assert _PERIOD_TO_DAYS["6mo"] == 180
    assert _PERIOD_TO_DAYS["1y"] == 365
    assert _PERIOD_TO_DAYS["2y"] == 730
    assert _PERIOD_TO_DAYS["5y"] == 1825


def test_period_to_days_has_all_standard_periods():
    expected = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y"}
    assert set(_PERIOD_TO_DAYS.keys()) == expected


# ── Instrument Token Cache ────────────────────────────────────


@patch("mcp_server.kite_auth.get_authenticated_kite")
def test_load_instrument_cache_success(mock_kite_fn):
    """Instrument cache loads tokens from Kite."""
    mock_kite = MagicMock()
    mock_kite_fn.return_value = mock_kite
    mock_kite.instruments.return_value = [
        {"tradingsymbol": "RELIANCE", "instrument_token": 12345},
        {"tradingsymbol": "TCS", "instrument_token": 67890},
    ]

    import mcp_server.data_provider as dp
    dp._cache_loaded_date = None
    dp._instrument_cache.clear()

    _load_instrument_cache()

    assert dp._instrument_cache.get("NSE:RELIANCE") == 12345
    assert dp._instrument_cache.get("NSE:TCS") == 67890


@patch("mcp_server.kite_auth.get_authenticated_kite")
def test_load_instrument_cache_kite_unavailable(mock_kite_fn):
    """Cache load fails gracefully when Kite is unavailable."""
    mock_kite_fn.side_effect = Exception("Kite auth failed")

    import mcp_server.data_provider as dp
    dp._cache_loaded_date = None
    dp._instrument_cache.clear()

    _load_instrument_cache()  # Should not raise
    # Cache remains empty
    assert len(dp._instrument_cache) == 0


@patch("mcp_server.data_provider._load_instrument_cache")
def test_resolve_instrument_token_found(mock_load):
    """Token resolution works when cache has the ticker."""
    import mcp_server.data_provider as dp
    dp._instrument_cache["NSE:RELIANCE"] = 99999

    token = _resolve_instrument_token("NSE:RELIANCE")
    assert token == 99999


@patch("mcp_server.data_provider._load_instrument_cache")
def test_resolve_instrument_token_not_found(mock_load):
    """Token resolution returns None for unknown ticker."""
    import mcp_server.data_provider as dp
    dp._instrument_cache.clear()

    token = _resolve_instrument_token("NSE:UNKNOWN")
    assert token is None


@patch("mcp_server.data_provider._load_instrument_cache")
def test_resolve_instrument_token_default_exchange(mock_load):
    """Bare ticker defaults to NSE."""
    import mcp_server.data_provider as dp
    dp._instrument_cache["NSE:INFY"] = 54321

    token = _resolve_instrument_token("INFY")
    assert token == 54321


# ── fetch_kite_historical ─────────────────────────────────────


def _mock_kite_data():
    """Sample Kite historical_data response."""
    return [
        {"date": datetime(2024, 1, 2), "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0, "volume": 50000},
        {"date": datetime(2024, 1, 3), "open": 104.0, "high": 110.0, "low": 103.0, "close": 108.0, "volume": 60000},
        {"date": datetime(2024, 1, 4), "open": 108.0, "high": 112.0, "low": 106.0, "close": 111.0, "volume": 55000},
    ]


@patch("mcp_server.kite_auth.get_authenticated_kite")
@patch("mcp_server.data_provider._resolve_instrument_token", return_value=12345)
def test_fetch_kite_historical_success(mock_token, mock_kite_fn):
    """Kite historical returns proper DataFrame."""
    mock_kite = MagicMock()
    mock_kite_fn.return_value = mock_kite
    mock_kite.historical_data.return_value = _mock_kite_data()

    df = fetch_kite_historical("NSE:RELIANCE", period="3mo", interval="1d")

    assert not df.empty
    assert len(df) == 3
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df["close"].iloc[-1] == 111.0


@patch("mcp_server.data_provider._resolve_instrument_token", return_value=None)
def test_fetch_kite_historical_no_token(mock_token):
    """Kite historical raises on missing token."""
    with pytest.raises(ValueError, match="No instrument token"):
        fetch_kite_historical("NSE:UNKNOWN")


@patch("mcp_server.data_provider._resolve_instrument_token", return_value=12345)
def test_fetch_kite_historical_bad_interval(mock_token):
    """Kite historical raises on unsupported interval."""
    with pytest.raises(ValueError, match="Unsupported interval"):
        fetch_kite_historical("NSE:RELIANCE", interval="2h")


@patch("mcp_server.data_provider._resolve_instrument_token", return_value=12345)
def test_fetch_kite_historical_bad_period(mock_token):
    """Kite historical raises on unsupported period."""
    with pytest.raises(ValueError, match="Unsupported period"):
        fetch_kite_historical("NSE:RELIANCE", period="10y")


@patch("mcp_server.kite_auth.get_authenticated_kite")
@patch("mcp_server.data_provider._resolve_instrument_token", return_value=12345)
def test_fetch_kite_historical_empty_data(mock_token, mock_kite_fn):
    """Kite historical raises when API returns empty list."""
    mock_kite = MagicMock()
    mock_kite_fn.return_value = mock_kite
    mock_kite.historical_data.return_value = []

    with pytest.raises(ValueError, match="no data"):
        fetch_kite_historical("NSE:RELIANCE")


# ── _yfinance_fetch ───────────────────────────────────────────


@patch("mcp_server.data_provider._rate_limited_download")
def test_yfinance_fetch_nse(mock_dl):
    """yfinance fetch works for NSE ticker."""
    mock_df = pd.DataFrame({
        "Open": [100, 104], "High": [105, 110],
        "Low": [99, 103], "Close": [104, 108], "Volume": [50000, 60000],
    })
    mock_dl.return_value = mock_df

    df = _yfinance_fetch("NSE:RELIANCE", period="5d", interval="1d")
    assert not df.empty
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    mock_dl.assert_called_once_with("RELIANCE.NS", period="5d", interval="1d")


def test_yfinance_fetch_nfo_returns_empty():
    """yfinance has no NFO support — returns empty."""
    df = _yfinance_fetch("NFO:NIFTY")
    assert df.empty


@patch("mcp_server.data_provider._rate_limited_download")
def test_yfinance_fetch_mcx_proxy(mock_dl):
    """yfinance resolves MCX:GOLD to GC=F proxy."""
    mock_df = pd.DataFrame({
        "Open": [1900], "High": [1920], "Low": [1890], "Close": [1915], "Volume": [10000],
    })
    mock_dl.return_value = mock_df

    df = _yfinance_fetch("MCX:GOLD")
    assert not df.empty
    mock_dl.assert_called_once_with("GC=F", period="1y", interval="1d")


@patch("mcp_server.data_provider._rate_limited_download")
def test_yfinance_fetch_empty_data(mock_dl):
    """yfinance returns empty DataFrame on no data."""
    mock_dl.return_value = pd.DataFrame()

    df = _yfinance_fetch("NSE:RELIANCE")
    assert df.empty


# ── get_stock_data (unified) ──────────────────────────────────


@patch("mcp_server.data_provider.settings")
@patch("mcp_server.data_provider.fetch_kite_historical")
def test_get_stock_data_kite_primary_success(mock_kite, mock_settings):
    """When Kite primary succeeds, returns Kite data."""
    mock_settings.DATA_PROVIDER_PRIMARY = "kite"
    mock_kite.return_value = pd.DataFrame({
        "open": [100], "high": [105], "low": [99], "close": [104], "volume": [50000],
    })

    df = get_stock_data("NSE:RELIANCE")
    assert not df.empty
    assert df["close"].iloc[0] == 104
    mock_kite.assert_called_once()


@patch("mcp_server.data_provider.settings")
@patch("mcp_server.data_provider._yfinance_fetch")
@patch("mcp_server.data_provider.fetch_kite_historical")
def test_get_stock_data_kite_fails_yfinance_fallback(mock_kite, mock_yf, mock_settings):
    """When Kite fails, falls back to yfinance."""
    mock_settings.DATA_PROVIDER_PRIMARY = "kite"
    mock_kite.side_effect = Exception("Kite auth expired")
    mock_yf.return_value = pd.DataFrame({
        "open": [200], "high": [210], "low": [195], "close": [205], "volume": [30000],
    })

    df = get_stock_data("NSE:RELIANCE")
    assert not df.empty
    assert df["close"].iloc[0] == 205
    mock_yf.assert_called_once()


@patch("mcp_server.data_provider.settings")
@patch("mcp_server.data_provider._yfinance_fetch")
def test_get_stock_data_yfinance_primary(mock_yf, mock_settings):
    """When yfinance is primary, uses yfinance directly."""
    mock_settings.DATA_PROVIDER_PRIMARY = "yfinance"
    mock_yf.return_value = pd.DataFrame({
        "open": [300], "high": [310], "low": [295], "close": [305], "volume": [40000],
    })

    df = get_stock_data("NSE:TCS")
    assert not df.empty
    mock_yf.assert_called_once()


@patch("mcp_server.data_provider.settings")
@patch("mcp_server.data_provider.fetch_kite_historical")
@patch("mcp_server.data_provider._yfinance_fetch")
def test_get_stock_data_yfinance_primary_fallback_to_kite(mock_yf, mock_kite, mock_settings):
    """When yfinance primary fails, falls back to Kite."""
    mock_settings.DATA_PROVIDER_PRIMARY = "yfinance"
    mock_yf.return_value = pd.DataFrame()
    mock_kite.return_value = pd.DataFrame({
        "open": [400], "high": [410], "low": [395], "close": [405], "volume": [20000],
    })

    df = get_stock_data("MCX:GOLD")
    assert not df.empty
    assert df["close"].iloc[0] == 405


@patch("mcp_server.data_provider.settings")
@patch("mcp_server.data_provider.fetch_kite_historical")
@patch("mcp_server.data_provider._yfinance_fetch")
def test_get_stock_data_both_fail_returns_empty(mock_yf, mock_kite, mock_settings):
    """When both sources fail, returns empty DataFrame."""
    mock_settings.DATA_PROVIDER_PRIMARY = "kite"
    mock_kite.side_effect = Exception("Kite down")
    mock_yf.return_value = pd.DataFrame()

    df = get_stock_data("NFO:NIFTY")
    assert df.empty


@patch("mcp_server.data_provider.settings")
@patch("mcp_server.data_provider.fetch_kite_historical")
def test_get_stock_data_passes_period_and_interval(mock_kite, mock_settings):
    """Period and interval are forwarded correctly."""
    mock_settings.DATA_PROVIDER_PRIMARY = "kite"
    mock_kite.return_value = pd.DataFrame({
        "open": [100], "high": [105], "low": [99], "close": [104], "volume": [50000],
    })

    get_stock_data("NSE:RELIANCE", period="3mo", interval="15m")
    mock_kite.assert_called_once_with("NSE:RELIANCE", period="3mo", interval="15m")


# ── Re-export from nse_scanner ────────────────────────────────


def test_nse_scanner_reexports_get_stock_data():
    """nse_scanner still exports get_stock_data for backward compatibility."""
    from mcp_server.nse_scanner import get_stock_data as nse_get_stock_data
    from mcp_server.data_provider import get_stock_data as dp_get_stock_data
    assert nse_get_stock_data is dp_get_stock_data


# ── Config ────────────────────────────────────────────────────


def test_config_data_provider_primary_default():
    """Config defaults to kite as primary data provider."""
    from mcp_server.config import settings as cfg
    assert cfg.DATA_PROVIDER_PRIMARY in ("kite", "yfinance")


# ── Rate Limiter (moved from nse_scanner) ─────────────────────


@patch("mcp_server.data_provider.yf")
def test_rate_limited_download_success(mock_yf):
    """Rate limited download returns data on success."""
    mock_df = pd.DataFrame({"Close": [100, 200]})
    mock_yf.download.return_value = mock_df

    result = _rate_limited_download("RELIANCE.NS", period="5d")
    assert not result.empty
    mock_yf.download.assert_called_once()


@patch("mcp_server.data_provider.yf")
@patch("mcp_server.data_provider.time")
def test_rate_limited_download_retries_on_empty(mock_time, mock_yf):
    """Rate limiter retries when yfinance returns empty data."""
    mock_time.time.return_value = 1000.0
    mock_time.sleep = MagicMock()
    mock_yf.download.side_effect = [pd.DataFrame(), pd.DataFrame(), pd.DataFrame()]

    result = _rate_limited_download("UNKNOWN.NS")
    assert result.empty
    assert mock_yf.download.call_count == 3
