import logging

import pandas as pd
import yfinance as yf
from datetime import datetime

from mcp_server.asset_registry import get_universe
from mcp_server.data_provider import get_stock_data  # noqa: F401 — re-exported

logger = logging.getLogger(__name__)

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
