"""
Equity daily OHLCV backfill for pairs trading universe.

Downloads 5 years of daily close data from yfinance for all 18 tickers
in data/pairs_universe.csv and stores them in ohlcv_cache.

Usage:
    python scripts/backfill_pairs_equity.py
    python scripts/backfill_pairs_equity.py --from-date 2020-01-01
    python scripts/backfill_pairs_equity.py --stats
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pairs_backfill")

# All unique symbols from pairs_universe.csv
SYMBOLS = [
    "HDFCBANK", "ICICIBANK",
    "TCS", "INFY",
    "ONGC", "OIL",
    "RELIANCE", "IOC",
    "MARUTI", "M&M",
    "HEROMOTOCO", "BAJAJ-AUTO",
    "ASIANPAINT", "BERGEPAINT",
    "ULTRACEMCO", "ACC",
    "AXISBANK", "KOTAKBANK",
    "COALINDIA", "NTPC",
]

# Yahoo Finance adds .NS suffix for NSE tickers
def _yf_ticker(symbol: str) -> str:
    return symbol + ".NS"


def _fetch_symbol(symbol: str, start: date, end: date) -> list[dict]:
    """Fetch daily OHLCV from yfinance for one symbol."""
    import yfinance as yf

    ticker = _yf_ticker(symbol)
    df = yf.download(
        ticker,
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        interval="1d",
        auto_adjust=True,
        progress=False,
    )
    if df.empty:
        logger.warning("No data returned for %s", symbol)
        return []

    rows = []
    for ts, row in df.iterrows():
        d = ts.date() if hasattr(ts, "date") else ts
        close_val = row["Close"]
        if hasattr(close_val, "iloc"):
            close_val = float(close_val.iloc[0])
        else:
            close_val = float(close_val)
        open_val = row["Open"]
        if hasattr(open_val, "iloc"):
            open_val = float(open_val.iloc[0])
        else:
            open_val = float(open_val)
        high_val = row["High"]
        if hasattr(high_val, "iloc"):
            high_val = float(high_val.iloc[0])
        else:
            high_val = float(high_val)
        low_val = row["Low"]
        if hasattr(low_val, "iloc"):
            low_val = float(low_val.iloc[0])
        else:
            low_val = float(low_val)
        vol_val = row["Volume"]
        if hasattr(vol_val, "iloc"):
            vol_val = int(vol_val.iloc[0])
        else:
            vol_val = int(vol_val) if vol_val == vol_val else 0
        rows.append({
            "ticker":   symbol,
            "exchange": "NSE",
            "interval": "1d",
            "bar_date": d,
            "open":     open_val,
            "high":     high_val,
            "low":      low_val,
            "close":    close_val,
            "volume":   vol_val,
        })
    return rows


def _upsert_rows(session, rows: list[dict]) -> int:
    if not rows:
        return 0
    from sqlalchemy import text
    sql = text("""
        INSERT INTO ohlcv_cache
          (ticker, exchange, interval, bar_date, open, high, low, close, volume, source, fetched_at)
        VALUES
          (:ticker, :exchange, :interval, :bar_date, :open, :high, :low, :close, :volume, 'yfinance', NOW())
        ON CONFLICT (ticker, interval, bar_date) DO UPDATE
          SET close    = EXCLUDED.close,
              open     = EXCLUDED.open,
              high     = EXCLUDED.high,
              low      = EXCLUDED.low,
              volume   = EXCLUDED.volume,
              exchange = EXCLUDED.exchange,
              source   = EXCLUDED.source,
              fetched_at = NOW()
    """)
    session.execute(sql, rows)
    session.commit()
    return len(rows)


def _print_stats(session) -> None:
    from sqlalchemy import text
    rows = session.execute(text("""
        SELECT ticker, COUNT(*) AS bars,
               MIN(bar_date) AS from_date, MAX(bar_date) AS to_date
        FROM ohlcv_cache
        WHERE interval = '1d'
          AND ticker = ANY(:syms)
        GROUP BY ticker
        ORDER BY ticker
    """), {"syms": SYMBOLS}).fetchall()

    if not rows:
        print("No pairs data in ohlcv_cache yet.")
        return

    print(f"\n{'Symbol':<15} {'Bars':>5}  {'From':<12} {'To':<12}")
    print("-" * 48)
    for r in rows:
        print(f"{r.ticker:<15} {r.bars:>5}  {r.from_date!s:<12} {r.to_date!s:<12}")
    missing = set(SYMBOLS) - {r.ticker for r in rows}
    if missing:
        print(f"\nMissing: {sorted(missing)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill equity daily OHLCV for pairs universe")
    parser.add_argument("--from-date", default="2021-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--to-date",   default=None,          help="End date (default: today)")
    parser.add_argument("--stats",     action="store_true",   help="Show DB coverage and exit")
    args = parser.parse_args()

    from_date = date.fromisoformat(args.from_date)
    to_date   = date.fromisoformat(args.to_date) if args.to_date else date.today()

    from mcp_server.db import SessionLocal
    session = SessionLocal()

    try:
        if args.stats:
            _print_stats(session)
            return

        logger.info("Backfilling %d symbols from %s to %s", len(SYMBOLS), from_date, to_date)
        total = 0
        for symbol in SYMBOLS:
            try:
                rows = _fetch_symbol(symbol, from_date, to_date)
                n = _upsert_rows(session, rows)
                total += n
                logger.info("%-15s  %d bars", symbol, n)
            except Exception as e:
                logger.error("Failed %s: %s", symbol, e)
                session.rollback()  # clear aborted transaction before next symbol
            time.sleep(0.3)  # be gentle with yfinance

        logger.info("Done. Total rows written/updated: %d", total)
        _print_stats(session)

    finally:
        session.close()


if __name__ == "__main__":
    main()
