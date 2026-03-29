"""
Unified Data Provider: Kite Connect primary + yfinance fallback.

Provides a single get_stock_data() function that:
1. Tries Kite Connect historical data API (native MCX/NFO/CDS support)
2. Falls back to yfinance if Kite is unavailable or fails

Usage:
    from mcp_server.data_provider import get_stock_data
    df = get_stock_data("NSE:RELIANCE", period="1y", interval="1d")
"""

import logging
import time
from datetime import datetime, timedelta, date

import pandas as pd
import yfinance as yf

from mcp_server.asset_registry import parse_ticker, resolve_yf_symbol, EXCHANGE_CONFIG, Exchange
from mcp_server.config import settings

logger = logging.getLogger(__name__)


# ── Kite Interval Mapping ──────────────────────────────────────

_INTERVAL_MAP: dict[str, str] = {
    "1m": "minute",
    "3m": "3minute",
    "5m": "5minute",
    "10m": "10minute",
    "15m": "15minute",
    "30m": "30minute",
    "1h": "60minute",
    "1d": "day",
    "1wk": "week",
    "1mo": "month",
}

# ── Period → Days Mapping ──────────────────────────────────────

_PERIOD_TO_DAYS: dict[str, int] = {
    "1d": 1,
    "5d": 5,
    "1mo": 30,
    "3mo": 90,
    "6mo": 180,
    "1y": 365,
    "2y": 730,
    "5y": 1825,
}


# ── Instrument Token Cache ─────────────────────────────────────

_instrument_cache: dict[str, int] = {}
_cache_loaded_date: str | None = None


def _load_instrument_cache() -> None:
    """
    Load instrument tokens from Kite for all exchanges.
    Refreshes once per day (tokens change daily for NFO/CDS expiries).
    """
    global _instrument_cache, _cache_loaded_date

    today = str(date.today())
    if _cache_loaded_date == today and _instrument_cache:
        return

    try:
        from mcp_server.kite_auth import get_authenticated_kite
        kite = get_authenticated_kite()

        _instrument_cache.clear()
        exchanges_to_load = ["NSE", "BSE", "MCX", "CDS", "NFO"]

        for exch in exchanges_to_load:
            try:
                instruments = kite.instruments(exch)
                for inst in instruments:
                    key = f"{exch}:{inst['tradingsymbol']}"
                    _instrument_cache[key] = inst["instrument_token"]
                logger.info("Loaded %d instruments for %s", len(instruments), exch)
            except Exception as e:
                logger.warning("Failed to load instruments for %s: %s", exch, e)

        _cache_loaded_date = today
        logger.info("Instrument cache loaded: %d total tokens", len(_instrument_cache))

    except Exception as e:
        logger.warning("Instrument cache load failed (Kite unavailable): %s", e)


def _resolve_instrument_token(ticker: str) -> int | None:
    """Resolve EXCHANGE:SYMBOL to Kite instrument token."""
    _load_instrument_cache()

    exchange, symbol = parse_ticker(ticker)
    key = f"{exchange}:{symbol}"

    token = _instrument_cache.get(key)
    if token is not None:
        return token

    logger.debug("No instrument token for %s", key)
    return None


# ── yfinance Rate Limiter ──────────────────────────────────────

_YF_MIN_DELAY = 0.5
_YF_MAX_RETRIES = 3
_YF_RETRY_BACKOFF = 2.0
_last_yf_request_time = 0.0


def _rate_limited_download(symbol: str, **kwargs) -> pd.DataFrame:
    """
    yfinance download with rate limiting and retry logic.
    Prevents rate-limit blocks when scanning 400+ stocks.
    """
    global _last_yf_request_time

    for attempt in range(_YF_MAX_RETRIES):
        elapsed = time.time() - _last_yf_request_time
        if elapsed < _YF_MIN_DELAY:
            time.sleep(_YF_MIN_DELAY - elapsed)

        try:
            _last_yf_request_time = time.time()
            data = yf.download(symbol, progress=False, **kwargs)
            if not data.empty:
                return data
            if attempt < _YF_MAX_RETRIES - 1:
                wait = _YF_RETRY_BACKOFF ** attempt
                logger.warning(
                    "Empty data for %s, retry %d/%d in %.1fs",
                    symbol, attempt + 1, _YF_MAX_RETRIES, wait,
                )
                time.sleep(wait)
        except Exception as e:
            if attempt < _YF_MAX_RETRIES - 1:
                wait = _YF_RETRY_BACKOFF ** attempt
                logger.warning(
                    "yfinance error for %s: %s — retry %d/%d in %.1fs",
                    symbol, e, attempt + 1, _YF_MAX_RETRIES, wait,
                )
                time.sleep(wait)
            else:
                logger.error(
                    "yfinance failed after %d retries for %s: %s",
                    _YF_MAX_RETRIES, symbol, e,
                )

    return pd.DataFrame()


# ── Kite Historical Data ──────────────────────────────────────


def fetch_kite_historical(
    ticker: str,
    period: str = "1y",
    interval: str = "1d",
) -> pd.DataFrame:
    """
    Fetch OHLCV data from Kite Connect historical API.

    Args:
        ticker: EXCHANGE:SYMBOL (e.g., NSE:RELIANCE, MCX:GOLD)
        period: Data period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y)
        interval: Candle interval (1m, 5m, 15m, 1h, 1d, 1wk, 1mo)

    Returns:
        DataFrame with [open, high, low, close, volume] or empty DataFrame on failure.
    """
    token = _resolve_instrument_token(ticker)
    if token is None:
        raise ValueError(f"No instrument token for {ticker}")

    kite_interval = _INTERVAL_MAP.get(interval)
    if kite_interval is None:
        raise ValueError(f"Unsupported interval: {interval}")

    days = _PERIOD_TO_DAYS.get(period)
    if days is None:
        raise ValueError(f"Unsupported period: {period}")

    to_date = datetime.now()
    from_date = to_date - timedelta(days=days)

    from mcp_server.kite_auth import get_authenticated_kite
    kite = get_authenticated_kite()

    records = kite.historical_data(
        instrument_token=token,
        from_date=from_date,
        to_date=to_date,
        interval=kite_interval,
    )

    if not records:
        raise ValueError(f"Kite returned no data for {ticker}")

    df = pd.DataFrame(records)

    # Normalize column names
    col_map = {"date": "date", "open": "open", "high": "high",
               "low": "low", "close": "close", "volume": "volume"}
    df.rename(columns={k: v for k, v in col_map.items() if k in df.columns}, inplace=True)

    if "date" in df.columns:
        df.set_index("date", inplace=True)

    required = ["open", "high", "low", "close", "volume"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Missing column {col} in Kite data for {ticker}")

    logger.info(
        "Kite: fetched %d bars for %s (%s, %s)",
        len(df), ticker, period, interval,
    )
    return df[required]


# ── yfinance Fallback ─────────────────────────────────────────


def _yfinance_fetch(
    ticker: str,
    period: str = "1y",
    interval: str = "1d",
) -> pd.DataFrame:
    """
    Fetch OHLCV data via yfinance (fallback path).
    Same behavior as the original get_stock_data() in nse_scanner.py.
    """
    yf_symbol = resolve_yf_symbol(ticker)
    if yf_symbol is None:
        logger.warning("No yfinance symbol for %s — Kite API required", ticker)
        return pd.DataFrame()

    try:
        data = _rate_limited_download(yf_symbol, period=period, interval=interval)

        if data.empty:
            logger.warning("No data returned for %s (yf: %s)", ticker, yf_symbol)
            return pd.DataFrame()

        # Normalize column names to lowercase
        data.columns = [
            c.lower() if isinstance(c, str) else c[0].lower()
            for c in data.columns
        ]

        # Handle MultiIndex columns from yfinance
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
            data.columns = [c.lower() for c in data.columns]

        required = ["open", "high", "low", "close", "volume"]
        for col in required:
            if col not in data.columns:
                logger.error("Missing column %s in data for %s", col, ticker)
                return pd.DataFrame()

        logger.info(
            "yfinance: fetched %d bars for %s (yf: %s, %s, %s)",
            len(data), ticker, yf_symbol, period, interval,
        )
        return data[required]

    except Exception as e:
        logger.error("Failed to fetch data for %s (yf: %s): %s", ticker, yf_symbol, e)
        return pd.DataFrame()


# ── Unified get_stock_data() ──────────────────────────────────


def get_stock_data(
    ticker: str,
    period: str = "1y",
    interval: str = "1d",
    force_refresh: bool = False,
    **kwargs,
) -> pd.DataFrame:
    """
    Fetch OHLCV data for any instrument.

    Strategy: Cache first → Kite → yfinance fallback (configurable via DATA_PROVIDER_PRIMARY).
    Cache layer stores results in PostgreSQL for sub-second warm reads.

    Supports multi-exchange tickers:
        NSE:RELIANCE, BSE:RELIANCE, MCX:GOLD, CDS:USDINR, NFO:NIFTY

    Args:
        ticker: Symbol with optional exchange prefix (EXCHANGE:SYMBOL)
        period: Data period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y)
        interval: Data interval (1m, 5m, 15m, 1h, 1d, 1wk, 1mo)
        force_refresh: Skip cache check and force API fetch (default False)

    Returns:
        DataFrame with open, high, low, close, volume columns (lowercase)
    """
    # Step 1: Check cache (unless force_refresh)
    if not force_refresh and settings.OHLCV_CACHE_ENABLED:
        try:
            from mcp_server.ohlcv_cache import check_cache
            from mcp_server.db import SessionLocal

            cache_session = SessionLocal()
            try:
                cached_df = check_cache(ticker, period, interval, cache_session)
                if cached_df is not None and not cached_df.empty:
                    return cached_df
            finally:
                cache_session.close()
        except Exception as e:
            logger.debug("Cache check skipped: %s", e)

    # Step 2: Fetch from API (existing logic)
    source = "yfinance"
    primary = settings.DATA_PROVIDER_PRIMARY

    if primary == "kite":
        # Try Kite first
        try:
            df = fetch_kite_historical(ticker, period=period, interval=interval)
            if not df.empty:
                source = "kite"
                _store_to_cache(ticker, interval, df, source)
                return df
        except Exception as e:
            logger.warning(
                "Kite failed for %s: %s — falling back to yfinance", ticker, e,
            )

        # Fallback to yfinance
        df = _yfinance_fetch(ticker, period=period, interval=interval)
        if not df.empty:
            _store_to_cache(ticker, interval, df, "yfinance")
        return df

    else:
        # yfinance primary (Kite disabled)
        df = _yfinance_fetch(ticker, period=period, interval=interval)
        if not df.empty:
            _store_to_cache(ticker, interval, df, "yfinance")
            return df

        # Try Kite as fallback even if yfinance is primary
        try:
            df = fetch_kite_historical(ticker, period=period, interval=interval)
            if not df.empty:
                _store_to_cache(ticker, interval, df, "kite")
            return df
        except Exception as e:
            logger.warning("Kite fallback also failed for %s: %s", ticker, e)
            return pd.DataFrame()


def _store_to_cache(ticker: str, interval: str, df: pd.DataFrame, source: str) -> None:
    """Non-fatal cache store — logs warning on failure, never blocks data return."""
    if not settings.OHLCV_CACHE_ENABLED:
        return
    try:
        from mcp_server.ohlcv_cache import store_cache
        from mcp_server.db import SessionLocal

        cache_session = SessionLocal()
        try:
            store_cache(ticker, interval, df, source, cache_session)
        finally:
            cache_session.close()
    except Exception as e:
        logger.warning("Cache store failed for %s: %s", ticker, e)
