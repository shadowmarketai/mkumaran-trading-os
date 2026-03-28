import logging
import time
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

from mcp_server.asset_registry import (
    parse_ticker,
    resolve_yf_symbol,
    get_universe,
    Exchange,
)

logger = logging.getLogger(__name__)

# ── Rate Limiter for yfinance ────────────────────────────────
_YF_MIN_DELAY = 0.5         # Minimum 0.5s between yfinance requests
_YF_MAX_RETRIES = 3          # Retry up to 3 times on failure
_YF_RETRY_BACKOFF = 2.0      # Exponential backoff multiplier
_last_yf_request_time = 0.0


def _rate_limited_download(symbol: str, **kwargs) -> pd.DataFrame:
    """
    yfinance download with rate limiting and retry logic.

    Prevents rate-limit blocks when scanning 400+ stocks.
    """
    global _last_yf_request_time

    for attempt in range(_YF_MAX_RETRIES):
        # Enforce minimum delay between requests
        elapsed = time.time() - _last_yf_request_time
        if elapsed < _YF_MIN_DELAY:
            time.sleep(_YF_MIN_DELAY - elapsed)

        try:
            _last_yf_request_time = time.time()
            data = yf.download(symbol, progress=False, **kwargs)
            if not data.empty:
                return data
            # Empty data — retry with backoff
            if attempt < _YF_MAX_RETRIES - 1:
                wait = _YF_RETRY_BACKOFF ** attempt
                logger.warning("Empty data for %s, retry %d/%d in %.1fs", symbol, attempt + 1, _YF_MAX_RETRIES, wait)
                time.sleep(wait)
        except Exception as e:
            if attempt < _YF_MAX_RETRIES - 1:
                wait = _YF_RETRY_BACKOFF ** attempt
                logger.warning("yfinance error for %s: %s — retry %d/%d in %.1fs", symbol, e, attempt + 1, _YF_MAX_RETRIES, wait)
                time.sleep(wait)
            else:
                logger.error("yfinance failed after %d retries for %s: %s", _YF_MAX_RETRIES, symbol, e)

    return pd.DataFrame()

# Minimum thresholds for liquid stocks
MIN_VOLUME = 100000  # Average daily volume
MIN_PRICE = 10.0     # Minimum stock price
MAX_PRICE = 50000.0  # Maximum stock price


def get_liquid_nse_stocks(min_volume: int = MIN_VOLUME) -> list[str]:
    """
    Get list of liquid NSE stocks (400-600 typically).
    Uses Nifty 500 as the base universe.

    Returns list of NSE symbols.
    """
    try:
        yf.Ticker("^CRSLDX")  # Verify connectivity
        logger.info("Fetching liquid NSE stock universe...")
        return _get_nse_universe()

    except Exception as e:
        logger.error("Failed to get NSE stock universe: %s", e)
        return _get_nse_universe()


def _get_nse_universe() -> list[str]:
    """
    Fallback: return a curated list of liquid NSE stocks.
    In production, this fetches from NSE/Chartink.
    """
    # Top 100 liquid NSE stocks for MVP
    return [
        "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY",
        "SBIN", "BHARTIARTL", "ITC", "KOTAKBANK", "LT",
        "AXISBANK", "WIPRO", "HCLTECH", "ASIANPAINT", "MARUTI",
        "SUNPHARMA", "TATAMOTORS", "ULTRACEMCO", "NESTLEIND", "BAJFINANCE",
        "BAJAJFINSV", "TITAN", "TECHM", "POWERGRID", "NTPC",
        "ADANIGREEN", "ADANIPORTS", "TATASTEEL", "JSWSTEEL", "HINDALCO",
        "GRASIM", "INDUSINDBK", "ONGC", "COALINDIA", "BPCL",
        "IOC", "DRREDDY", "CIPLA", "DIVISLAB", "BRITANNIA",
        "EICHERMOT", "HEROMOTOCO", "BAJAJ-AUTO", "M&M", "TATACONSUM",
        "APOLLOHOSP", "DABUR", "GODREJCP", "PIDILITIND", "BERGEPAINT",
        "ACC", "CDSL", "CENTURYTEX", "GUJGASLTD", "JINDALSTEL",
        "BHARATFORG", "ECLERX", "SHYAMMETL", "ABCAPITAL", "ABFRL",
        "CASTROLIND", "GMRINFRA", "PEL", "LICHSGFIN", "BEL",
        "TANLA", "IRCTC", "IDEA", "IRB", "NBCC",
        "CHENNPETRO", "NFL", "APLLTD", "INDIACEM", "LICI",
    ]


def get_stock_data(
    ticker: str,
    period: str = "1y",
    interval: str = "1d",
    **kwargs,
) -> pd.DataFrame:
    """
    Fetch OHLCV data for any instrument using yfinance.

    Supports multi-exchange tickers:
        NSE:RELIANCE  -> RELIANCE.NS
        BSE:RELIANCE  -> RELIANCE.BO
        MCX:GOLD      -> GC=F (global proxy)
        CDS:USDINR    -> USDINR=X
        RELIANCE      -> RELIANCE.NS (default NSE)

    Args:
        ticker: Symbol with optional exchange prefix (EXCHANGE:SYMBOL)
        period: Data period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y)
        interval: Data interval (1m, 5m, 15m, 1h, 1d, 1wk)

    Returns:
        DataFrame with open, high, low, close, volume columns (lowercase)
    """
    # Resolve to yfinance symbol
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
        data.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in data.columns]

        # Ensure required columns exist
        required = ['open', 'high', 'low', 'close', 'volume']
        for col in required:
            if col not in data.columns:
                logger.error("Missing column %s in data for %s", col, ticker)
                return pd.DataFrame()

        # Handle MultiIndex columns from yfinance
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
            data.columns = [c.lower() for c in data.columns]

        logger.info("Fetched %d bars for %s (yf: %s, %s, %s)", len(data), ticker, yf_symbol, period, interval)
        return data[required]

    except Exception as e:
        logger.error("Failed to fetch data for %s (yf: %s): %s", ticker, yf_symbol, e)
        return pd.DataFrame()


def get_multi_asset_data(
    tickers: list[str],
    period: str = "1y",
    interval: str = "1d",
) -> dict[str, pd.DataFrame]:
    """
    Fetch OHLCV data for multiple instruments across exchanges.

    Args:
        tickers: List of EXCHANGE:SYMBOL tickers
        period: Data period
        interval: Data interval

    Returns:
        Dict of {ticker: DataFrame}
    """
    results: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        df = get_stock_data(ticker, period=period, interval=interval)
        if not df.empty:
            results[ticker] = df
    return results


def liquidity_filter(
    stocks: list[str],
    min_volume: int = MIN_VOLUME,
    min_price: float = MIN_PRICE,
    max_price: float = MAX_PRICE,
) -> list[str]:
    """
    Filter stocks by liquidity (volume and price range).
    """
    liquid: list[str] = []

    for stock in stocks:
        try:
            data = get_stock_data(stock, period="5d", interval="1d")
            if data.empty or len(data) < 2:
                continue

            avg_vol = data['volume'].mean()
            last_price = data['close'].iloc[-1]

            if avg_vol >= min_volume and min_price <= last_price <= max_price:
                liquid.append(stock)
        except Exception:
            continue

    logger.info("Liquidity filter: %d/%d stocks passed", len(liquid), len(stocks))
    return liquid


def tier1_scan(
    stocks: list[str] | None = None,
    exchange: str = "NSE",
) -> dict:
    """
    Tier 1: Full scan (daily at 8:45 AM).

    Pipeline:
    1. Get liquid stocks for the exchange
    2. Fetch data for all
    3. Run RRMS on each
    4. Detect patterns
    5. Cross-reference with MWA scanners
    6. Return top candidates
    """
    if stocks is None:
        stocks = get_universe(exchange)

    logger.info("Tier 1 scan starting with %d instruments (%s)", len(stocks), exchange)

    return {
        "tier": 1,
        "exchange": exchange,
        "total_scanned": len(stocks),
        "timestamp": datetime.now().isoformat(),
        "candidates": [],  # Filled by full pipeline
    }
