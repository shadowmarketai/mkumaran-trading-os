"""
NSE Raw Data Preprocessor

Converts raw NSE CSV downloads to the formats expected by
validate_strangle_earnings_fii.py.

── File 1: Earnings (NSE Corporate Actions) ────────────────────────────────
Download from:
  https://www.nseindia.com/companies-listing/corporate-filings-actions
  → Select: Equities | Financial Results | From: 01-01-2023 | To: 30-04-2026
  → Click Download / Export

Save raw NSE file as: data/nse_corporate_actions_raw.csv
This script produces: data/nifty50_earnings_manual.csv

── File 2: FII F&O (NSE Participant-wise derivatives data) ─────────────────
Download from:
  https://www.nseindia.com/reports/fiiTradeOnExchNse
  OR
  https://www.nseindia.com/market-data/fii-dii-activity
  → Select Derivatives/F&O tab | Date range 01-01-2023 to 30-04-2026
  → Download CSV

Save raw NSE file as: data/nse_fii_raw.csv
This script produces: data/fii_fno_historical.csv

Usage:
    python scripts/preprocess_nse_data.py
    python scripts/preprocess_nse_data.py --earnings-only
    python scripts/preprocess_nse_data.py --fii-only
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("nse_preprocessor")

DATA_DIR = Path("data")

NIFTY_50 = frozenset({
    "HDFCBANK", "RELIANCE", "ICICIBANK", "INFY", "TCS",
    "BHARTIARTL", "SBIN", "KOTAKBANK", "BAJFINANCE", "LT",
    "AXISBANK", "WIPRO", "ASIANPAINT", "MARUTI", "TITAN",
    "SUNPHARMA", "ULTRACEMCO", "NTPC", "POWERGRID", "ONGC",
    "TECHM", "HCLTECH", "BAJAJFINSV", "TATAMOTORS", "NESTLEIND",
    "M&M", "JSWSTEEL", "TATASTEEL", "INDUSINDBK", "HINDALCO",
    "CIPLA", "ADANIPORTS", "GRASIM", "BPCL", "COALINDIA",
    "EICHERMOT", "DRREDDY", "DIVISLAB", "SBILIFE", "BRITANNIA",
    "HEROMOTOCO", "APOLLOHOSP", "BAJAJ-AUTO", "TATACONSUM",
    "SHRIRAMFIN", "ADANIENT", "HDFCLIFE", "ICICIGI", "PIDILITIND",
    "HAVELLS",
})

EARNINGS_KEYWORDS = [
    "financial result", "quarterly result", "annual result",
    "q1", "q2", "q3", "q4", "half year", "half-year",
]


def _parse_nse_date(raw: str) -> str | None:
    """Parse NSE date strings to YYYY-MM-DD. Handles DD-Mon-YYYY and DD-MM-YYYY."""
    raw = raw.strip()
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


# ── Earnings preprocessor ─────────────────────────────────────────────────

def process_earnings(raw_path: Path, out_path: Path) -> int:
    """
    Parse NSE corporate actions CSV → {date, ticker}.
    NSE column names vary by export; tries multiple layouts.
    """
    if not raw_path.exists():
        logger.error("Raw earnings file not found: %s", raw_path)
        logger.error(
            "Download from: https://www.nseindia.com/companies-listing/"
            "corporate-filings-actions"
        )
        logger.error("  Filter: Equities | Financial Results | 01-01-2023 to 30-04-2026")
        logger.error("  Save as: %s", raw_path)
        return 0

    rows = []
    with raw_path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = [h.strip().lower() for h in (reader.fieldnames or [])]
        logger.info("Earnings raw headers: %s", headers)

        # Find the relevant columns — NSE uses different names
        sym_col   = _find_col(headers, ["symbol", "sym", "scrip"])
        date_col  = _find_col(headers, ["ex-date", "ex date", "exdate", "record date",
                                         "record-date", "date"])
        purp_col  = _find_col(headers, ["purpose", "subject", "description", "remarks"])

        if sym_col is None or date_col is None:
            logger.error("Cannot find symbol/date columns. Headers: %s", headers)
            logger.error("Expected columns like: Symbol, Ex-Date, Purpose")
            return 0

        logger.info("Using columns: symbol=%s, date=%s, purpose=%s",
                    sym_col, date_col, purp_col)

        for raw_row in reader:
            row = {k.strip().lower(): v.strip() for k, v in raw_row.items()}
            ticker = row.get(sym_col, "").strip().upper()
            if ticker not in NIFTY_50:
                continue

            raw_date = row.get(date_col, "")
            parsed_date = _parse_nse_date(raw_date)
            if not parsed_date:
                continue

            # Filter to financial results only if purpose column exists
            if purp_col:
                purpose = row.get(purp_col, "").lower()
                if not any(kw in purpose for kw in EARNINGS_KEYWORDS):
                    continue

            rows.append({"date": parsed_date, "ticker": ticker})

    # Deduplicate
    seen = set()
    unique_rows = []
    for r in sorted(rows, key=lambda x: x["date"]):
        key = (r["date"], r["ticker"])
        if key not in seen:
            seen.add(key)
            unique_rows.append(r)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "ticker"])
        writer.writeheader()
        writer.writerows(unique_rows)

    # Summary
    dates = {r["date"] for r in unique_rows}
    tickers = {r["ticker"] for r in unique_rows}
    logger.info("Earnings output: %d rows | %d unique dates | %d Nifty 50 tickers",
                len(unique_rows), len(dates), len(tickers))
    logger.info("Date range: %s → %s",
                min(dates) if dates else "—", max(dates) if dates else "—")
    logger.info("Saved: %s", out_path)

    if len(unique_rows) < 50:
        logger.warning(
            "Only %d rows — expected ~300+ for 3 years of Nifty 50 earnings. "
            "Check that the download covered the full date range and included "
            "Financial Results (not just dividends/splits).", len(unique_rows)
        )

    return len(unique_rows)


# ── FII preprocessor ──────────────────────────────────────────────────────

def process_fii(raw_path: Path, out_path: Path) -> int:
    """
    Parse NSE FII F&O participant-wise CSV → {date, fii_net_fo}.
    NSE provides buy/sell separately; net = buy - sell.
    """
    if not raw_path.exists():
        logger.error("Raw FII file not found: %s", raw_path)
        logger.error(
            "Download from: https://www.nseindia.com/reports/fiiTradeOnExchNse"
        )
        logger.error("  Or: Market Data → FII/DII Activity → Derivatives tab")
        logger.error("  Date range: 01-01-2023 to 30-04-2026, Download CSV")
        logger.error("  Save as: %s", raw_path)
        return 0

    rows = []
    with raw_path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = [h.strip().lower() for h in (reader.fieldnames or [])]
        logger.info("FII raw headers: %s", headers)

        date_col = _find_col(headers, ["date", "trade date", "trading date"])
        buy_col  = _find_col(headers, ["buy value", "purchase value", "buy amt",
                                        "purchase", "gross purchase", "net purchase"])
        sell_col = _find_col(headers, ["sell value", "sales value", "sell amt",
                                        "sales", "gross sales"])
        net_col  = _find_col(headers, ["net value", "net purchase", "net",
                                        "net investment"])

        if date_col is None:
            logger.error("Cannot find date column. Headers: %s", headers)
            return 0

        if net_col is None and (buy_col is None or sell_col is None):
            logger.error(
                "Cannot find net or buy/sell columns. Headers: %s", headers
            )
            return 0

        logger.info("Using columns: date=%s, buy=%s, sell=%s, net=%s",
                    date_col, buy_col, sell_col, net_col)

        for raw_row in reader:
            row = {k.strip().lower(): v.strip() for k, v in raw_row.items()}
            raw_date = row.get(date_col, "")
            parsed_date = _parse_nse_date(raw_date)
            if not parsed_date:
                continue

            try:
                if net_col and row.get(net_col, "").replace(",", "").replace("-", "").strip():
                    net = float(re.sub(r"[^\d.\-]", "", row[net_col]) or "0")
                elif buy_col and sell_col:
                    buy  = float(re.sub(r"[^\d.]", "", row.get(buy_col, "0")) or "0")
                    sell = float(re.sub(r"[^\d.]", "", row.get(sell_col, "0")) or "0")
                    net  = buy - sell
                else:
                    continue
            except (ValueError, TypeError):
                continue

            rows.append({"date": parsed_date, "fii_net_fo": net})

    # Deduplicate by date (keep last)
    by_date: dict[str, float] = {}
    for r in rows:
        by_date[r["date"]] = r["fii_net_fo"]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "fii_net_fo"])
        writer.writeheader()
        for d in sorted(by_date.keys()):
            writer.writerow({"date": d, "fii_net_fo": by_date[d]})

    logger.info("FII output: %d sessions", len(by_date))
    if by_date:
        logger.info("Date range: %s → %s", min(by_date), max(by_date))
    logger.info("Saved: %s", out_path)

    if len(by_date) < 200:
        logger.warning(
            "Only %d sessions — expected ~750+ trading days for 3 years. "
            "Check that the download covered the full date range.", len(by_date)
        )

    return len(by_date)


# ── Helpers ───────────────────────────────────────────────────────────────

def _find_col(headers: list[str], candidates: list[str]) -> str | None:
    for c in candidates:
        for h in headers:
            if c in h:
                return h
    return None


# ── Main ──────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert raw NSE CSV downloads to gate backtest format"
    )
    parser.add_argument("--earnings-only", action="store_true")
    parser.add_argument("--fii-only",      action="store_true")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("NSE Raw Data Preprocessor")
    print("=" * 60)

    earnings_ok = fii_ok = False

    if not args.fii_only:
        raw = DATA_DIR / "nse_corporate_actions_raw.csv"
        out = DATA_DIR / "nifty50_earnings_manual.csv"
        n = process_earnings(raw, out)
        earnings_ok = n > 0
        print(f"\nEarnings: {'OK (%d rows)' % n if earnings_ok else 'FAILED — see instructions above'}")

    if not args.earnings_only:
        raw = DATA_DIR / "nse_fii_raw.csv"
        out = DATA_DIR / "fii_fno_historical.csv"
        n = process_fii(raw, out)
        fii_ok = n > 0
        print(f"FII F&O:  {'OK (%d sessions)' % n if fii_ok else 'FAILED — see instructions above'}")

    print()
    if earnings_ok or fii_ok:
        print("Files ready. Run the gate test:")
        print("  python scripts/validate_strangle_earnings_fii.py")
    else:
        print("Download the raw files first (see instructions above),")
        print("then re-run this script.")
    print()


if __name__ == "__main__":
    main()
