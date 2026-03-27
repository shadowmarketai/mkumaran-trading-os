import logging
from datetime import date, timedelta
import requests

from mcp_server.asset_registry import filter_applies

logger = logging.getLogger(__name__)

NSE_BHAV_URL = "https://archives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{date}_F_0000.csv.zip"


def get_delivery_data(target_date: date | None = None) -> dict[str, float]:
    """
    Fetch delivery percentage data from NSE bhav copy.

    Returns dict of {symbol: delivery_pct}
    """
    if target_date is None:
        target_date = date.today()

    # NSE bhav data is available after market hours (after 6 PM)
    # Try today, if not available try yesterday
    delivery_data: dict[str, float] = {}

    for delta in range(3):  # Try last 3 days (skip weekends)
        check_date = target_date - timedelta(days=delta)

        try:
            headers = {
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/html,application/xhtml+xml",
            }

            url = f"https://archives.nseindia.com/products/content/sec_bhavdata_full_{check_date.strftime('%d%m%Y')}.csv"
            resp = requests.get(url, headers=headers, timeout=30)

            if resp.status_code != 200:
                continue

            import io
            import csv
            reader = csv.DictReader(io.StringIO(resp.text))

            for row in reader:
                symbol = row.get("SYMBOL", "").strip()
                try:
                    deliv_qty = float(row.get("DELIV_QTY", 0) or 0)
                    total_qty = float(row.get("TTL_TRD_QNTY", 0) or 0)
                    if total_qty > 0:
                        delivery_data[symbol] = round(deliv_qty / total_qty * 100, 2)
                except (ValueError, ZeroDivisionError):
                    pass

            if delivery_data:
                logger.info("Delivery data loaded for %s: %d stocks", check_date, len(delivery_data))
                return delivery_data

        except Exception as e:
            logger.warning("Failed to fetch bhav data for %s: %s", check_date, e)

    logger.warning("Could not fetch delivery data for last 3 days")
    return delivery_data


def apply_delivery_filter(
    stocks: list[str],
    delivery_data: dict[str, float],
    min_delivery_pct: float = 60.0,
) -> dict[str, dict]:
    """
    Filter stocks by delivery percentage.
    Only applies to EQUITY asset class (NSE/BSE).
    Commodities, currencies, and F&O auto-pass.

    Returns dict with stocks and their delivery info:
        {symbol: {"delivery_pct": X, "passed": True/False}}
    """
    results: dict[str, dict] = {}

    for stock in stocks:
        # Skip delivery filter for non-equity assets
        if not filter_applies(stock, "delivery"):
            results[stock] = {
                "delivery_pct": 0.0,
                "passed": True,
                "skipped": True,
                "reason": "delivery filter N/A for this asset class",
            }
            continue

        # Remove exchange prefix if present
        symbol = stock.split(":")[-1] if ":" in stock else stock
        pct = delivery_data.get(symbol, 0.0)
        passed = pct >= min_delivery_pct

        results[stock] = {
            "delivery_pct": pct,
            "passed": passed,
        }

    passed_count = sum(1 for r in results.values() if r["passed"])
    logger.info(
        "Delivery filter: %d/%d stocks passed (>= %.0f%%)",
        passed_count, len(stocks), min_delivery_pct,
    )

    return results
