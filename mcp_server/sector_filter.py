import logging
import yfinance as yf
from datetime import datetime, timedelta

from mcp_server.asset_registry import filter_applies

logger = logging.getLogger(__name__)

SECTOR_INDICES: dict[str, str] = {
    "IT": "^CNXIT",
    "Banking": "^NSEBANK",
    "Pharma": "^CNXPHARMA",
    "Auto": "^CNXAUTO",
    "Metal": "^CNXMETAL",
    "Energy": "^CNXENERGY",
    "FMCG": "^CNXFMCG",
    "Realty": "^CNXREALTY",
    "Infrastructure": "^CNXINFRA",
    "Media": "^CNXMEDIA",
    "PSU Bank": "^CNXPSUBANK",
    "Financial": "^CNXFIN",
}

STOCK_SECTORS: dict[str, str] = {
    "RELIANCE": "Energy",
    "SBIN": "Banking",
    "HDFCBANK": "Banking",
    "ICICIBANK": "Banking",
    "TCS": "IT",
    "INFY": "IT",
    "TATASTEEL": "Metal",
    "JINDALSTEL": "Metal",
    "BAJAJ-AUTO": "Auto",
    "BHARATFORG": "Auto",
    "BEL": "Infrastructure",
    "GMRINFRA": "Infrastructure",
    "LICHSGFIN": "Financial",
    "ABCAPITAL": "Financial",
    "ACC": "Infrastructure",
    "CDSL": "Financial",
    "CENTURYTEX": "FMCG",
    "GUJGASLTD": "Energy",
    "ECLERX": "IT",
    "SHYAMMETL": "Metal",
    "CASTROLIND": "Energy",
    "PEL": "Financial",
    "ABFRL": "FMCG",
    "LICI": "Financial",
}


def get_sector_strength() -> dict[str, str]:
    """
    Calculate sector strength based on 4-week and 1-week returns.

    Returns: Dict of {sector_name: "STRONG" | "NEUTRAL" | "WEAK"}
    """
    end = datetime.now()
    start_4w = end - timedelta(weeks=4)

    results: dict[str, str] = {}

    for sector, symbol in SECTOR_INDICES.items():
        try:
            data = yf.download(symbol, start=start_4w, end=end, progress=False)

            if len(data) < 5:
                results[sector] = "NEUTRAL"
                continue

            # 4-week return
            ret_4w = (data['Close'].iloc[-1] - data['Close'].iloc[0]) / data['Close'].iloc[0] * 100

            # 1-week return
            week_start = max(0, len(data) - 5)
            ret_1w = (data['Close'].iloc[-1] - data['Close'].iloc[week_start]) / data['Close'].iloc[week_start] * 100

            # Classification
            if ret_4w > 3 and ret_1w > 1:
                strength = "STRONG"
            elif ret_4w < -3 or ret_1w < -2:
                strength = "WEAK"
            else:
                strength = "NEUTRAL"

            results[sector] = strength
            logger.info("Sector %s: 4w=%.1f%%, 1w=%.1f%% -> %s", sector, ret_4w, ret_1w, strength)

        except Exception as e:
            logger.error("Failed to get sector data for %s: %s", sector, e)
            results[sector] = "NEUTRAL"

    return results


def get_stock_sector(ticker: str) -> str:
    """Get the sector for a given stock."""
    symbol = ticker.replace("NSE:", "")
    return STOCK_SECTORS.get(symbol, "Unknown")


def sector_allows_trade(ticker: str, direction: str, sector_strength: dict[str, str]) -> bool:
    """
    Check if sector rotation allows this trade.
    Block: WEAK sector longs, STRONG sector shorts.
    Only applies to equity (NSE/BSE). Commodities/currencies/F&O always pass.
    """
    if not filter_applies(ticker, "sector"):
        return True

    sector = get_stock_sector(ticker)
    strength = sector_strength.get(sector, "NEUTRAL")

    if direction == "LONG" and strength == "WEAK":
        logger.info("REJECTED: %s LONG blocked -- sector %s is WEAK", ticker, sector)
        return False

    if direction == "SHORT" and strength == "STRONG":
        logger.info("REJECTED: %s SHORT blocked -- sector %s is STRONG", ticker, sector)
        return False

    return True
