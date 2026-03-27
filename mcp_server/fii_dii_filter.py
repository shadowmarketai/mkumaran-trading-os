import logging
import requests
from datetime import date

from mcp_server.asset_registry import filter_applies

logger = logging.getLogger(__name__)


def get_fii_dii_data() -> dict:
    """
    Fetch FII/DII activity data from NSE.

    Returns:
        Dict with fii_net, dii_net, fii_buy, fii_sell, dii_buy, dii_sell (all in Cr)
    """
    try:
        url = "https://www.nseindia.com/api/fiidiiTradeReact"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://www.nseindia.com/",
        }

        # NSE requires a session with cookies
        session = requests.Session()
        session.get("https://www.nseindia.com/", headers=headers, timeout=10)

        resp = session.get(url, headers=headers, timeout=10)
        data = resp.json()

        fii_data = {}
        dii_data = {}

        for entry in data:
            category = entry.get("category", "")
            if "FII" in category or "FPI" in category:
                fii_data = entry
            elif "DII" in category:
                dii_data = entry

        fii_buy = float(fii_data.get("buyValue", 0))
        fii_sell = float(fii_data.get("sellValue", 0))
        dii_buy = float(dii_data.get("buyValue", 0))
        dii_sell = float(dii_data.get("sellValue", 0))

        result = {
            "date": str(date.today()),
            "fii_buy": round(fii_buy, 2),
            "fii_sell": round(fii_sell, 2),
            "fii_net": round(fii_buy - fii_sell, 2),
            "dii_buy": round(dii_buy, 2),
            "dii_sell": round(dii_sell, 2),
            "dii_net": round(dii_buy - dii_sell, 2),
        }

        logger.info(
            "FII/DII data: FII net: %.2f Cr, DII net: %.2f Cr",
            result["fii_net"], result["dii_net"],
        )

        return result

    except Exception as e:
        logger.error("Failed to fetch FII/DII data: %s", e)
        return {
            "date": str(date.today()),
            "fii_buy": 0, "fii_sell": 0, "fii_net": 0,
            "dii_buy": 0, "dii_sell": 0, "dii_net": 0,
        }


def classify_fii_sentiment(fii_net: float) -> str:
    """Classify FII sentiment based on net flow."""
    if fii_net > 500:
        return "STRONG_BUY"
    elif fii_net > 0:
        return "BUY"
    elif fii_net > -2000:
        return "SELL"
    else:
        return "STRONG_SELL"


def fii_allows_long(fii_net: float, ticker: str = "NSE:DEFAULT") -> bool:
    """
    Check if FII data allows long positions. Reject if selling > 2000 Cr.
    Only applies to equity. Commodities/currencies/F&O always pass.
    """
    if not filter_applies(ticker, "fii_dii"):
        return True
    return fii_net > -2000
