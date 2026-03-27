"""
Multi-Asset Registry: Exchange/AssetClass enums, symbol resolver, universe lists.

Supports: NSE (Equity), BSE (Equity), MCX (Commodity), CDS (Currency), NFO (F&O).
"""

import logging
from enum import Enum

logger = logging.getLogger(__name__)


# ── Enums ────────────────────────────────────────────────────


class Exchange(str, Enum):
    NSE = "NSE"
    BSE = "BSE"
    MCX = "MCX"
    CDS = "CDS"
    NFO = "NFO"


class AssetClass(str, Enum):
    EQUITY = "EQUITY"
    COMMODITY = "COMMODITY"
    CURRENCY = "CURRENCY"
    FNO = "FNO"


# ── Exchange Configuration ───────────────────────────────────


EXCHANGE_CONFIG: dict[str, dict] = {
    Exchange.NSE: {
        "asset_class": AssetClass.EQUITY,
        "yf_suffix": ".NS",
        "kite_exchange": "NSE",
        "filters": ["delivery", "fii_dii", "sector", "earnings"],
        "scanners": ["chartink", "python"],
        "description": "National Stock Exchange - Equity",
    },
    Exchange.BSE: {
        "asset_class": AssetClass.EQUITY,
        "yf_suffix": ".BO",
        "kite_exchange": "BSE",
        "filters": ["delivery", "fii_dii", "sector", "earnings"],
        "scanners": ["python"],
        "description": "Bombay Stock Exchange - Equity",
    },
    Exchange.MCX: {
        "asset_class": AssetClass.COMMODITY,
        "yf_suffix": None,  # MCX uses Kite API or global futures proxies
        "kite_exchange": "MCX",
        "filters": ["oi_buildup"],
        "scanners": ["python"],
        "description": "Multi Commodity Exchange",
    },
    Exchange.CDS: {
        "asset_class": AssetClass.CURRENCY,
        "yf_suffix": "=X",
        "kite_exchange": "CDS",
        "filters": [],
        "scanners": ["python"],
        "description": "Currency Derivatives Segment",
    },
    Exchange.NFO: {
        "asset_class": AssetClass.FNO,
        "yf_suffix": None,  # F&O uses Kite API
        "kite_exchange": "NFO",
        "filters": ["oi_buildup"],
        "scanners": ["python"],
        "description": "NSE Futures & Options",
    },
}


# ── yfinance Proxy Tickers for MCX Commodities ──────────────
# MCX doesn't have direct yfinance support; use global futures as proxies

MCX_YF_PROXY: dict[str, str] = {
    "GOLD": "GC=F",
    "GOLDM": "GC=F",
    "SILVER": "SI=F",
    "SILVERM": "SI=F",
    "CRUDEOIL": "CL=F",
    "NATURALGAS": "NG=F",
    "COPPER": "HG=F",
    "ZINC": "ZN=F",       # LME via yfinance not available; fallback
    "ALUMINIUM": "ALI=F",
    "LEAD": "PB=F",
    "NICKEL": "NI=F",
    "COTTON": "CT=F",
    "MENTHAOIL": None,     # No global proxy
}


# ── Universe Lists ───────────────────────────────────────────


MCX_UNIVERSE: list[str] = [
    "GOLD", "GOLDM", "SILVER", "SILVERM",
    "CRUDEOIL", "NATURALGAS",
    "COPPER", "ZINC", "ALUMINIUM", "LEAD", "NICKEL",
    "COTTON",
]

CDS_UNIVERSE: list[str] = [
    "USDINR", "EURINR", "GBPINR", "JPYINR",
]

NFO_INDEX_UNIVERSE: list[str] = [
    "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY",
]


# ── Symbol Resolution ───────────────────────────────────────


def parse_ticker(ticker: str) -> tuple[str, str]:
    """
    Parse 'EXCHANGE:SYMBOL' into (exchange, symbol).
    Default exchange is NSE if no prefix.

    Examples:
        'NSE:RELIANCE' -> ('NSE', 'RELIANCE')
        'MCX:GOLD'     -> ('MCX', 'GOLD')
        'RELIANCE'     -> ('NSE', 'RELIANCE')
        'CDS:USDINR'   -> ('CDS', 'USDINR')
    """
    if ":" in ticker:
        parts = ticker.split(":", 1)
        return parts[0].upper(), parts[1].upper()
    return "NSE", ticker.upper()


def resolve_yf_symbol(ticker: str) -> str | None:
    """
    Convert EXCHANGE:SYMBOL to yfinance-compatible ticker.

    Returns None if no yfinance equivalent exists (use Kite API instead).

    Examples:
        'NSE:RELIANCE' -> 'RELIANCE.NS'
        'BSE:RELIANCE' -> 'RELIANCE.BO'
        'MCX:GOLD'     -> 'GC=F'
        'CDS:USDINR'   -> 'USDINR=X'
        'NFO:NIFTY'    -> None (use Kite)
    """
    exchange, symbol = parse_ticker(ticker)

    if exchange in ("NSE", "BSE"):
        suffix = EXCHANGE_CONFIG[Exchange(exchange)]["yf_suffix"]
        return f"{symbol}{suffix}"

    if exchange == "MCX":
        proxy = MCX_YF_PROXY.get(symbol)
        if proxy:
            return proxy
        logger.warning("No yfinance proxy for MCX:%s", symbol)
        return None

    if exchange == "CDS":
        return f"{symbol}=X"

    if exchange == "NFO":
        # F&O needs Kite API for live data
        return None

    logger.warning("Unknown exchange: %s", exchange)
    return None


def get_exchange(ticker: str) -> Exchange:
    """Get Exchange enum from ticker string."""
    exchange_str, _ = parse_ticker(ticker)
    try:
        return Exchange(exchange_str)
    except ValueError:
        return Exchange.NSE


def get_asset_class(ticker: str) -> AssetClass:
    """Get AssetClass for a ticker."""
    exchange = get_exchange(ticker)
    return EXCHANGE_CONFIG[exchange]["asset_class"]


def get_applicable_filters(ticker: str) -> list[str]:
    """Get list of filter names applicable to this ticker's asset class."""
    exchange = get_exchange(ticker)
    return EXCHANGE_CONFIG[exchange]["filters"]


def filter_applies(ticker: str, filter_name: str) -> bool:
    """Check if a specific filter applies to this ticker."""
    return filter_name in get_applicable_filters(ticker)


def get_universe(exchange: str | Exchange = Exchange.NSE) -> list[str]:
    """
    Get the universe of tradeable instruments for an exchange.

    Returns list of symbols (without exchange prefix).
    """
    if isinstance(exchange, str):
        try:
            exchange = Exchange(exchange.upper())
        except ValueError:
            return []

    if exchange in (Exchange.NSE, Exchange.BSE):
        # Import here to avoid circular dependency
        from mcp_server.nse_scanner import _get_nse_universe
        return _get_nse_universe()

    if exchange == Exchange.MCX:
        return MCX_UNIVERSE.copy()

    if exchange == Exchange.CDS:
        return CDS_UNIVERSE.copy()

    if exchange == Exchange.NFO:
        return NFO_INDEX_UNIVERSE.copy()

    return []


def format_ticker(exchange: str | Exchange, symbol: str) -> str:
    """Format exchange + symbol into standard ticker format."""
    if isinstance(exchange, Exchange):
        exchange = exchange.value
    return f"{exchange}:{symbol}"


# ── Supported Exchanges Summary ──────────────────────────────


def get_supported_exchanges() -> list[dict]:
    """Return summary of all supported exchanges."""
    return [
        {
            "exchange": ex.value,
            "asset_class": cfg["asset_class"].value,
            "description": cfg["description"],
            "filters": cfg["filters"],
            "scanners": cfg["scanners"],
            "universe_size": len(get_universe(ex)),
        }
        for ex, cfg in EXCHANGE_CONFIG.items()
    ]
