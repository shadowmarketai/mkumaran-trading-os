"""
MKUMARAN Trading OS — Portfolio Risk Manager

Pre-trade risk checks:
- Sector concentration limits (max 25% per sector)
- Max exposure per asset class
- Total portfolio exposure tracking

Designed to be called from OrderManager._validate_order() as pre-trade gate.
"""

import logging

logger = logging.getLogger(__name__)

# ── Risk Limits ──────────────────────────────────────────────
MAX_SECTOR_PCT = 0.25          # Max 25% capital in one sector
MAX_ASSET_CLASS_PCT = 0.50     # Max 50% in one asset class
MAX_SINGLE_STOCK_PCT = 0.10    # Max 10% in one stock (redundant with order_manager)

# ── NSE Sector Mapping ──────────────────────────────────────
# Maps stock tickers to GICS-style sectors
SECTOR_MAP: dict[str, str] = {
    # Financials
    "HDFCBANK": "FINANCIALS", "ICICIBANK": "FINANCIALS", "SBIN": "FINANCIALS",
    "KOTAKBANK": "FINANCIALS", "AXISBANK": "FINANCIALS", "BAJFINANCE": "FINANCIALS",
    "BAJAJFINSV": "FINANCIALS", "INDUSINDBK": "FINANCIALS", "LICHSGFIN": "FINANCIALS",
    "ABCAPITAL": "FINANCIALS", "PEL": "FINANCIALS", "CDSL": "FINANCIALS",
    # IT
    "TCS": "IT", "INFY": "IT", "WIPRO": "IT", "HCLTECH": "IT",
    "TECHM": "IT", "ECLERX": "IT", "TANLA": "IT",
    # Energy / Oil & Gas
    "RELIANCE": "ENERGY", "ONGC": "ENERGY", "BPCL": "ENERGY",
    "IOC": "ENERGY", "COALINDIA": "ENERGY", "NTPC": "ENERGY",
    "POWERGRID": "ENERGY", "ADANIGREEN": "ENERGY", "CHENNPETRO": "ENERGY",
    # Auto
    "TATAMOTORS": "AUTO", "MARUTI": "AUTO", "M&M": "AUTO",
    "BAJAJ-AUTO": "AUTO", "EICHERMOT": "AUTO", "HEROMOTOCO": "AUTO",
    # Metals & Mining
    "TATASTEEL": "METALS", "JSWSTEEL": "METALS", "HINDALCO": "METALS",
    "JINDALSTEL": "METALS", "SHYAMMETL": "METALS",
    # Pharma
    "SUNPHARMA": "PHARMA", "DRREDDY": "PHARMA", "CIPLA": "PHARMA",
    "DIVISLAB": "PHARMA", "APOLLOHOSP": "PHARMA",
    # FMCG
    "ITC": "FMCG", "NESTLEIND": "FMCG", "BRITANNIA": "FMCG",
    "DABUR": "FMCG", "GODREJCP": "FMCG", "TATACONSUM": "FMCG",
    # Infrastructure / Capital Goods
    "LT": "INFRA", "ADANIPORTS": "INFRA", "GMRINFRA": "INFRA",
    "IRB": "INFRA", "NBCC": "INFRA", "IRCTC": "INFRA",
    # Cement
    "ULTRACEMCO": "CEMENT", "ACC": "CEMENT", "GRASIM": "CEMENT",
    "INDIACEM": "CEMENT",
    # Consumer / Retail
    "TITAN": "CONSUMER", "ASIANPAINT": "CONSUMER", "PIDILITIND": "CONSUMER",
    "BERGEPAINT": "CONSUMER", "ABFRL": "CONSUMER",
    # Telecom
    "BHARTIARTL": "TELECOM", "IDEA": "TELECOM",
    # Others
    "BEL": "DEFENCE", "LICI": "INSURANCE", "NFL": "FERTILIZER",
    "APLLTD": "CHEMICALS", "CASTROLIND": "LUBRICANTS",
    "CENTURYTEX": "TEXTILES", "GUJGASLTD": "GAS",
    "BHARATFORG": "AUTO_ANCILLARY",
}

# MCX commodities are their own "sector"
MCX_SECTOR = "COMMODITY"
CDS_SECTOR = "CURRENCY"
NFO_SECTOR = "FNO_DERIVATIVES"


def get_sector(ticker: str) -> str:
    """Get sector for a ticker. Returns 'UNKNOWN' if not mapped."""
    # Parse exchange:symbol format
    if ":" in ticker:
        exchange, symbol = ticker.split(":", 1)
        if exchange == "MCX":
            return MCX_SECTOR
        if exchange == "CDS":
            return CDS_SECTOR
        if exchange == "NFO":
            return NFO_SECTOR
        ticker = symbol

    return SECTOR_MAP.get(ticker.upper(), "UNKNOWN")


def check_sector_concentration(
    open_positions: list[dict],
    new_ticker: str,
    new_order_value: float,
    capital: float,
) -> str | None:
    """
    Check if adding a new position would breach sector concentration limits.

    Args:
        open_positions: List of position dicts with ticker, entry_price, qty
        new_ticker: The ticker we want to add
        new_order_value: Value of the new order
        capital: Total trading capital

    Returns None if OK, error message if breached.
    """
    if capital <= 0:
        return None  # Can't check without capital

    new_sector = get_sector(new_ticker)

    # Calculate current sector exposure
    sector_exposure: dict[str, float] = {}
    for pos in open_positions:
        sector = get_sector(pos.get("ticker", ""))
        value = pos.get("entry_price", 0) * pos.get("qty", 0)
        sector_exposure[sector] = sector_exposure.get(sector, 0) + value

    # Add the proposed new position
    current_sector_value = sector_exposure.get(new_sector, 0)
    new_total = current_sector_value + new_order_value
    sector_pct = new_total / capital

    if sector_pct > MAX_SECTOR_PCT:
        return (
            f"SECTOR LIMIT: Adding {new_ticker} would put {new_sector} sector at "
            f"{sector_pct:.0%} of capital (limit: {MAX_SECTOR_PCT:.0%}). "
            f"Current: {current_sector_value:,.0f}, new: +{new_order_value:,.0f}"
        )

    return None


def check_asset_class_concentration(
    open_positions: list[dict],
    new_ticker: str,
    new_order_value: float,
    capital: float,
) -> str | None:
    """
    Check asset class concentration (max 50% in equity, commodity, etc.).
    """
    if capital <= 0:
        return None

    # Determine asset class of new ticker
    exchange = "NSE"
    if ":" in new_ticker:
        exchange = new_ticker.split(":")[0]

    asset_class_map = {
        "NSE": "EQUITY", "BSE": "EQUITY",
        "MCX": "COMMODITY", "CDS": "CURRENCY", "NFO": "FNO",
    }
    new_asset_class = asset_class_map.get(exchange, "EQUITY")

    # Calculate current asset class exposure
    class_exposure: dict[str, float] = {}
    for pos in open_positions:
        pos_ticker = pos.get("ticker", "")
        pos_exchange = pos_ticker.split(":")[0] if ":" in pos_ticker else "NSE"
        pos_class = asset_class_map.get(pos_exchange, "EQUITY")
        value = pos.get("entry_price", 0) * pos.get("qty", 0)
        class_exposure[pos_class] = class_exposure.get(pos_class, 0) + value

    current_value = class_exposure.get(new_asset_class, 0)
    new_total = current_value + new_order_value
    class_pct = new_total / capital

    if class_pct > MAX_ASSET_CLASS_PCT:
        return (
            f"ASSET CLASS LIMIT: Adding {new_ticker} would put {new_asset_class} at "
            f"{class_pct:.0%} of capital (limit: {MAX_ASSET_CLASS_PCT:.0%})"
        )

    return None


def validate_portfolio_risk(
    open_positions: list[dict],
    new_ticker: str,
    new_order_value: float,
    capital: float,
) -> str | None:
    """
    Run all portfolio risk checks. Returns None if OK, error string if any check fails.

    Called from OrderManager._validate_order() as pre-trade gate.
    """
    # Sector check
    sector_error = check_sector_concentration(
        open_positions, new_ticker, new_order_value, capital,
    )
    if sector_error:
        return sector_error

    # Asset class check
    class_error = check_asset_class_concentration(
        open_positions, new_ticker, new_order_value, capital,
    )
    if class_error:
        return class_error

    return None


def get_portfolio_exposure(
    open_positions: list[dict],
    capital: float,
) -> dict:
    """Get current portfolio exposure breakdown for dashboard display."""
    sector_exposure: dict[str, float] = {}
    class_exposure: dict[str, float] = {}

    asset_class_map = {
        "NSE": "EQUITY", "BSE": "EQUITY",
        "MCX": "COMMODITY", "CDS": "CURRENCY", "NFO": "FNO",
    }

    total_deployed = 0.0
    for pos in open_positions:
        ticker = pos.get("ticker", "")
        value = pos.get("entry_price", 0) * pos.get("qty", 0)
        total_deployed += value

        sector = get_sector(ticker)
        sector_exposure[sector] = sector_exposure.get(sector, 0) + value

        exchange = ticker.split(":")[0] if ":" in ticker else "NSE"
        asset_class = asset_class_map.get(exchange, "EQUITY")
        class_exposure[asset_class] = class_exposure.get(asset_class, 0) + value

    return {
        "total_deployed": round(total_deployed, 2),
        "deployed_pct": round(total_deployed / capital * 100, 1) if capital > 0 else 0,
        "sector_breakdown": {
            k: {"value": round(v, 2), "pct": round(v / capital * 100, 1) if capital > 0 else 0}
            for k, v in sorted(sector_exposure.items(), key=lambda x: -x[1])
        },
        "asset_class_breakdown": {
            k: {"value": round(v, 2), "pct": round(v / capital * 100, 1) if capital > 0 else 0}
            for k, v in sorted(class_exposure.items(), key=lambda x: -x[1])
        },
        "limits": {
            "max_sector_pct": MAX_SECTOR_PCT * 100,
            "max_asset_class_pct": MAX_ASSET_CLASS_PCT * 100,
        },
    }
