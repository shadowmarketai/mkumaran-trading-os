import logging
import json
from pathlib import Path

import pandas as pd
import yfinance as yf
from mcp_server.asset_registry import get_universe
from mcp_server.market_calendar import now_ist
from mcp_server.data_provider import get_stock_data  # noqa: F401 — re-exported

logger = logging.getLogger(__name__)

# Minimum thresholds for liquid stocks
MIN_VOLUME = 100000  # Average daily volume
MIN_PRICE = 10.0     # Minimum stock price
MAX_PRICE = 50000.0  # Maximum stock price

# Cache path for dynamically fetched Nifty 500 list
_NIFTY500_CACHE = Path(__file__).parent.parent / "data" / "nifty500.json"
_nse_universe_cache: list[str] | None = None


def _fetch_nifty500_from_nse() -> list[str]:
    """Fetch Nifty 500 constituent list from NSE India (free CSV endpoint)."""
    import requests

    url = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/csv,*/*",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        lines = resp.text.strip().split("\n")
        symbols: list[str] = []
        for line in lines[1:]:  # Skip header
            parts = line.split(",")
            if len(parts) >= 3:
                sym = parts[2].strip().strip('"')
                if sym and sym != "Symbol":
                    symbols.append(sym)
        if symbols:
            logger.info("Fetched %d Nifty 500 symbols from NSE", len(symbols))
            return symbols
    except Exception as e:
        logger.warning("Nifty 500 fetch from NSE failed: %s", e)

    # Fallback: try NSE India direct
    try:
        nse_url = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20500"
        sess = requests.Session()
        sess.headers.update(headers)
        sess.get("https://www.nseindia.com", timeout=5)  # Set cookies
        resp = sess.get(nse_url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        symbols = [d["symbol"] for d in data.get("data", []) if d.get("symbol")]
        if symbols:
            logger.info("Fetched %d Nifty 500 symbols from NSE India API", len(symbols))
            return symbols
    except Exception as e:
        logger.warning("Nifty 500 fetch from NSE India API failed: %s", e)

    return []


def _save_nifty500_cache(symbols: list[str]) -> None:
    """Persist Nifty 500 list to disk for offline fallback."""
    try:
        _NIFTY500_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _NIFTY500_CACHE.write_text(json.dumps({
            "symbols": symbols,
            "fetched_at": now_ist().isoformat(),
            "count": len(symbols),
        }))
        logger.info("Nifty 500 cache saved: %d symbols", len(symbols))
    except Exception as e:
        logger.warning("Failed to save Nifty 500 cache: %s", e)


def _load_nifty500_cache() -> list[str]:
    """Load cached Nifty 500 list from disk."""
    try:
        if _NIFTY500_CACHE.exists():
            data = json.loads(_NIFTY500_CACHE.read_text())
            symbols = data.get("symbols", [])
            if symbols:
                logger.info("Loaded %d symbols from Nifty 500 cache", len(symbols))
                return symbols
    except Exception as e:
        logger.warning("Failed to load Nifty 500 cache: %s", e)
    return []


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
    Return expanded NSE universe:
    1. Try dynamic Nifty 500 fetch (cached daily)
    2. Fall back to disk cache
    3. Fall back to hardcoded top 200 liquid stocks
    """
    global _nse_universe_cache

    if _nse_universe_cache:
        return _nse_universe_cache

    # Try dynamic fetch first
    symbols = _fetch_nifty500_from_nse()
    if symbols:
        _save_nifty500_cache(symbols)
        _nse_universe_cache = symbols
        return symbols

    # Try disk cache
    symbols = _load_nifty500_cache()
    if symbols:
        _nse_universe_cache = symbols
        return symbols

    # Hardcoded fallback: expanded to ~200 liquid stocks
    logger.warning("Using hardcoded NSE universe (200 stocks)")
    _nse_universe_cache = _HARDCODED_NSE_UNIVERSE
    return _nse_universe_cache


# Expanded hardcoded fallback (Nifty 200 equivalent)
_HARDCODED_NSE_UNIVERSE: list[str] = [
    # Nifty 50
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
    # Nifty Next 50
    "ACC", "ADANIENT", "ADANIENSOL", "AMBUJACEM", "BANKBARODA",
    "BOSCHLTD", "CHOLAFIN", "COLPAL", "DLF", "GAIL",
    "GODREJPROP", "HAL", "HAVELLS", "HINDPETRO", "ICICIPRULI",
    "IDFCFIRSTB", "INDIGO", "INDUSTOWER", "JSWENERGY", "JUBLFOOD",
    "LICI", "LUPIN", "MARICO", "MUTHOOTFIN", "NAUKRI",
    "PFC", "PGHH", "PIIND", "PNB", "RECLTD",
    "SBICARD", "SBILIFE", "SHREECEM", "SIEMENS", "SRF",
    "TATAPOWER", "TORNTPHARM", "TRENT", "UPL", "VEDL",
    "ZOMATO", "ZYDUSLIFE",
    # Top gainers that were missing + high liquidity mid-caps
    "DMART", "BSE", "MCX", "DALBHARAT", "ABCAPITAL",
    "NMDC", "BANDHANBNK", "MAHABANK", "PNBHOUSING", "KAYNES",
    "GRAVITA", "KALYANKJIL", "NEULANDLAB", "LTF", "RBLBANK",
    "IEX", "PTCIL", "SOBHA", "EIHOTEL", "GRANULES",
    "LENSKART", "SIGNATURE", "SHRIRAMFIN", "TITAGARH", "CUB",
    "ECLERX", "NH",
    # Additional liquid stocks
    "CDSL", "CENTURYTEX", "GUJGASLTD", "JINDALSTEL",
    "BHARATFORG", "SHYAMMETL", "ABFRL",
    "CASTROLIND", "GMRINFRA", "PEL", "LICHSGFIN", "BEL",
    "TANLA", "IRCTC", "IDEA", "IRB", "NBCC",
    "CHENNPETRO", "NFL", "APLLTD", "INDIACEM",
    "ACUTAAS", "LGEINDIA", "VMM", "NSLNISP", "GODREJPROP",
    "MAXHEALTH", "FEDERALBNK", "CANBK", "OFSS", "MFSL",
    "POLYCAB", "ASTRAL", "PERSISTENT", "COFORGE", "LTTS",
    "LAURUSLABS", "AUROPHARMA", "BIOCON", "ALKEM", "IPCALAB",
    "PAGEIND", "TATAELXSI", "NAVINFLUOR", "DEEPAKNTR", "ATUL",
    "SYNGENE", "SUMICHEM", "AARTI", "CLEAN", "SONACOMS",
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
        "timestamp": now_ist().isoformat(),
        "candidates": [],  # Filled by full pipeline
    }
