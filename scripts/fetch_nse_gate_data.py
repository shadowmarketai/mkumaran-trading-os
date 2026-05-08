"""
NSE Gate Data Fetcher — Playwright-based scraper

Downloads two files needed for the strangle gate backtest:
  1. data/nifty50_earnings_manual.csv  — NSE corporate actions (financial results)
  2. data/fii_fno_historical.csv       — NSE FII F&O participant-wise daily net

Uses a real Chromium browser (Playwright) to bypass NSE's JavaScript requirement
and Cloudflare session cookies that block plain requests.

Usage:
    python scripts/fetch_nse_gate_data.py
    python scripts/fetch_nse_gate_data.py --earnings-only
    python scripts/fetch_nse_gate_data.py --fii-only
    python scripts/fetch_nse_gate_data.py --from 2023-01-01 --to 2026-04-30

Install once on server if needed:
    pip install playwright
    playwright install chromium --with-deps
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("nse_scraper")

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


def _nse_date(d: date) -> str:
    return d.strftime("%d-%m-%Y")


# ── Earnings: NSE corporate actions ──────────────────────────────────────

def fetch_earnings(from_date: date, to_date: date) -> list[dict]:
    """
    Scrape NSE corporate actions API for Nifty 50 financial results.
    Uses Playwright to get a valid NSE session, then calls the API directly.
    Returns list of {date, ticker} dicts.
    """
    from playwright.sync_api import sync_playwright

    logger.info("Fetching NSE earnings data %s → %s via Playwright...", from_date, to_date)

    all_events: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-http2"],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            ignore_https_errors=True,
        )
        page = ctx.new_page()

        # Visit NSE homepage to establish session + cookies
        logger.info("Establishing NSE session...")
        try:
            page.goto("https://www.nseindia.com", wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            logger.warning("NSE homepage load partial (%s) — continuing anyway", e)
        time.sleep(3)

        # Batch in 90-day chunks to stay within API limits
        cur = from_date
        while cur <= to_date:
            batch_end = min(cur + timedelta(days=89), to_date)
            url = (
                "https://www.nseindia.com/api/corporates-corporateActions"
                f"?index=equities"
                f"&from_date={_nse_date(cur)}"
                f"&to_date={_nse_date(batch_end)}"
                f"&type=financial%20results"
            )
            try:
                resp = page.request.get(url, timeout=20000)
                if resp.ok:
                    data = resp.json()
                    if isinstance(data, list):
                        batch_events = []
                        for item in data:
                            purpose = item.get("purpose", "").lower()
                            if not any(kw in purpose for kw in [
                                "financial result", "quarterly result",
                                "annual result", "q1", "q2", "q3", "q4",
                            ]):
                                continue
                            ticker = item.get("symbol", "")
                            if ticker not in NIFTY_50:
                                continue
                            try:
                                from datetime import datetime
                                ex_date = datetime.strptime(
                                    item["exDate"], "%d-%b-%Y"
                                ).date()
                            except Exception:
                                continue
                            batch_events.append({
                                "date":   ex_date.isoformat(),
                                "ticker": ticker,
                            })
                        all_events.extend(batch_events)
                        logger.info("  %s → %s: %d Nifty 50 events",
                                    cur, batch_end, len(batch_events))
                else:
                    logger.warning("  %s → %s: HTTP %s", cur, batch_end, resp.status)
            except Exception as e:
                logger.warning("  %s → %s: %s", cur, batch_end, e)

            cur = batch_end + timedelta(days=1)
            time.sleep(1.0)

        browser.close()

    logger.info("Total Nifty 50 earnings events fetched: %d", len(all_events))
    return all_events


def save_earnings(events: list[dict], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    rows = []
    for ev in sorted(events, key=lambda x: x["date"]):
        key = (ev["date"], ev["ticker"])
        if key not in seen:
            seen.add(key)
            rows.append(ev)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "ticker"])
        writer.writeheader()
        writer.writerows(rows)
    logger.info("Earnings saved: %d rows → %s", len(rows), path)
    return len(rows)


# ── FII F&O: participant-wise daily data ──────────────────────────────────

def fetch_fii_fno(from_date: date, to_date: date) -> list[dict]:
    """
    Scrape NSE FII F&O participant-wise data via Playwright.
    Tries the historical API endpoint; falls back to scraping the
    FII/DII statistics page for downloadable CSV links.
    Returns list of {date, fii_net_fo} dicts (net in crore).
    """
    from playwright.sync_api import sync_playwright

    logger.info("Fetching NSE FII F&O data %s → %s via Playwright...", from_date, to_date)
    all_rows: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-http2"],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            ignore_https_errors=True,
        )
        page = ctx.new_page()

        logger.info("Establishing NSE session...")
        try:
            page.goto("https://www.nseindia.com", wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            logger.warning("NSE homepage load partial (%s) — continuing anyway", e)
        time.sleep(3)

        cur = from_date
        while cur <= to_date:
            batch_end = min(cur + timedelta(days=89), to_date)

            # Try historical FII derivatives API
            url = (
                "https://www.nseindia.com/api/historical/fiiDeriData"
                f"?from_date={_nse_date(cur)}&to_date={_nse_date(batch_end)}"
            )
            try:
                resp = page.request.get(url, timeout=20000)
                if resp.ok:
                    data = resp.json()
                    rows = data if isinstance(data, list) else data.get("data", [])
                    batch_rows = []
                    for row in rows:
                        try:
                            from datetime import datetime
                            # NSE returns dates in various formats
                            raw_date = row.get("date") or row.get("Date") or ""
                            for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d-%m-%Y"):
                                try:
                                    d = datetime.strptime(raw_date, fmt).date()
                                    break
                                except ValueError:
                                    continue
                            else:
                                continue
                            # Net purchase = buy - sell (in crore)
                            net = (
                                row.get("netPurchase")
                                or row.get("net_purchase")
                                or row.get("NetPurchase")
                                or 0
                            )
                            net_f = float(str(net).replace(",", ""))
                            batch_rows.append({
                                "date":       d.isoformat(),
                                "fii_net_fo": net_f,
                            })
                        except Exception:
                            continue
                    all_rows.extend(batch_rows)
                    if batch_rows:
                        logger.info("  %s → %s: %d FII sessions", cur, batch_end, len(batch_rows))
                    else:
                        logger.warning("  %s → %s: 0 rows (HTTP %s, trying alternate...)",
                                       cur, batch_end, resp.status)
                        all_rows.extend(_fetch_fii_batch_alternate(page, cur, batch_end))
                else:
                    logger.warning("  %s → %s: HTTP %s, trying alternate...",
                                   cur, batch_end, resp.status)
                    all_rows.extend(_fetch_fii_batch_alternate(page, cur, batch_end))
            except Exception as e:
                logger.warning("  %s → %s: %s, trying alternate...", cur, batch_end, e)
                all_rows.extend(_fetch_fii_batch_alternate(page, cur, batch_end))

            cur = batch_end + timedelta(days=1)
            time.sleep(1.0)

        browser.close()

    logger.info("Total FII F&O sessions fetched: %d", len(all_rows))
    return all_rows


def _fetch_fii_batch_alternate(page, from_date: date, to_date: date) -> list[dict]:
    """Try alternate NSE endpoint for FII data."""
    rows = []
    for url_tmpl in [
        "https://www.nseindia.com/api/fiidiiTradeReactHistory?type=fiiDerivatives"
        f"&from_date={_nse_date(from_date)}&to_date={_nse_date(to_date)}",
        "https://www.nseindia.com/api/historicalfiiDII"
        f"?type=fiiDerivatives&from_date={_nse_date(from_date)}&to_date={_nse_date(to_date)}",
    ]:
        try:
            resp = page.request.get(url_tmpl, timeout=15000)
            if resp.ok:
                data = resp.json()
                items = data if isinstance(data, list) else data.get("data", [])
                for item in items:
                    try:
                        from datetime import datetime
                        raw = item.get("date") or item.get("Date") or ""
                        for fmt in ("%d-%b-%Y", "%Y-%m-%d"):
                            try:
                                d = datetime.strptime(raw, fmt).date()
                                break
                            except ValueError:
                                continue
                        else:
                            continue
                        net = item.get("netPurchase") or item.get("net") or 0
                        rows.append({
                            "date":       d.isoformat(),
                            "fii_net_fo": float(str(net).replace(",", "")),
                        })
                    except Exception:
                        continue
                if rows:
                    return rows
        except Exception:
            continue
    return rows


def save_fii(rows: list[dict], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    seen: dict[str, float] = {}
    for row in rows:
        seen[row["date"]] = row["fii_net_fo"]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "fii_net_fo"])
        writer.writeheader()
        for d in sorted(seen.keys()):
            writer.writerow({"date": d, "fii_net_fo": seen[d]})
    logger.info("FII F&O saved: %d sessions → %s", len(seen), path)
    return len(seen)


# ── Coverage check ────────────────────────────────────────────────────────

def check_earnings_coverage(path: Path, from_date: date, to_date: date) -> None:
    if not path.exists():
        logger.error("Earnings file missing: %s", path)
        return
    rows = list(csv.DictReader(path.open()))
    dates = {r["date"] for r in rows}
    # Expect ~4 results seasons per year, ~8 Nifty 50 stocks per week of season
    years = (to_date - from_date).days / 365
    expected_min = int(years * 4 * 5)  # 4 seasons × ~5 event-days per season
    logger.info("Earnings: %d unique dates, %d rows (expected ≥ %d unique dates for %.1f years)",
                len(dates), len(rows), expected_min, years)
    if len(dates) < expected_min:
        logger.warning("Coverage may be low — check NSE data quality")


def check_fii_coverage(path: Path, from_date: date, to_date: date) -> None:
    if not path.exists():
        logger.error("FII file missing: %s", path)
        return
    rows = list(csv.DictReader(path.open()))
    trading_days_expected = int((to_date - from_date).days * 5 / 7 * 0.95)
    missing = trading_days_expected - len(rows)
    logger.info("FII F&O: %d sessions (expected ~%d, missing ~%d)",
                len(rows), trading_days_expected, max(missing, 0))
    if missing > 10:
        logger.warning("FII coverage: ~%d sessions missing — "
                       "override condition 3 may trigger in gate test", missing)


# ── Main ──────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download NSE earnings and FII data for strangle gate backtest"
    )
    parser.add_argument("--from", dest="from_date", default="2023-01-01")
    parser.add_argument("--to",   dest="to_date",   default="2026-04-30")
    parser.add_argument("--earnings-only", action="store_true")
    parser.add_argument("--fii-only",      action="store_true")
    args = parser.parse_args()

    from_date = date.fromisoformat(args.from_date)
    to_date   = date.fromisoformat(args.to_date)

    logger.info("NSE Gate Data Fetcher")
    logger.info("Period: %s → %s", from_date, to_date)
    logger.info("Output: %s/", DATA_DIR)

    if not args.fii_only:
        earnings_path = DATA_DIR / "nifty50_earnings_manual.csv"
        if earnings_path.exists():
            logger.info("Earnings file already exists — skipping (delete to re-fetch)")
        else:
            events = fetch_earnings(from_date, to_date)
            if events:
                save_earnings(events, earnings_path)
                check_earnings_coverage(earnings_path, from_date, to_date)
            else:
                logger.error("No earnings events fetched — NSE may still be blocking")

    if not args.earnings_only:
        fii_path = DATA_DIR / "fii_fno_historical.csv"
        if fii_path.exists():
            logger.info("FII file already exists — skipping (delete to re-fetch)")
        else:
            rows = fetch_fii_fno(from_date, to_date)
            if rows:
                save_fii(rows, fii_path)
                check_fii_coverage(fii_path, from_date, to_date)
            else:
                logger.error("No FII sessions fetched — check alternate endpoints or download manually")

    print("\nFiles:")
    for fname in ["nifty50_earnings_manual.csv", "fii_fno_historical.csv"]:
        p = DATA_DIR / fname
        status = "{} rows".format(sum(1 for _ in open(p)) - 1) if p.exists() else "MISSING"
        print(f"  {p}: {status}")

    print("\nIf both files have sufficient rows, run:")
    print("  python scripts/validate_strangle_earnings_fii.py")


if __name__ == "__main__":
    main()
