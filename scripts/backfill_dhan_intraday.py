"""
Dhan Intraday OHLCV Backfill — 5 years of 15-min data for Nifty 100

Run once on the prod server to populate ohlcv_cache with historical
15-minute bars that yfinance cannot provide beyond 60 days.

Usage:
    cd /app
    python scripts/backfill_dhan_intraday.py
    python scripts/backfill_dhan_intraday.py --resume        # skip completed tickers
    python scripts/backfill_dhan_intraday.py --ticker SBIN   # single ticker
    python scripts/backfill_dhan_intraday.py --years 3       # shorter window

After backfill completes, re-run backtest validation:
    curl -X POST http://localhost:8001/tools/backtest_validate \
      -d '{"ticker":"HDFCBANK","strategy":"pos_5ema","days":1095,...}'
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta

# ── Ensure mcp_server is importable from /app ────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill")


# ── Nifty 100 universe (symbol → Dhan exchange_segment) ──────
# Covers the stocks most likely to generate POS 5 EMA setups.
# Source: NSE Nifty 100 constituents (Apr 2026).
# Extend by running: python scripts/backfill_dhan_intraday.py --dump-universe
NIFTY_100 = [
    "HDFCBANK", "RELIANCE", "ICICIBANK", "INFY", "TCS",
    "BHARTIARTL", "SBIN", "HDFC", "KOTAKBANK", "BAJFINANCE",
    "LT", "AXISBANK", "WIPRO", "ASIANPAINT", "MARUTI",
    "TITAN", "SUNPHARMA", "ULTRACEMCO", "NTPC", "POWERGRID",
    "ONGC", "TECHM", "HCLTECH", "BAJAJFINSV", "TATAMOTORS",
    "NESTLEIND", "M&M", "JSWSTEEL", "TATASTEEL", "INDUSINDBK",
    "HINDALCO", "CIPLA", "ADANIPORTS", "GRASIM", "BPCL",
    "COALINDIA", "EICHERMOT", "DRREDDY", "DIVISLAB", "SBILIFE",
    "BRITANNIA", "HEROMOTOCO", "APOLLOHOSP", "BAJAJ-AUTO", "TATACONSUM",
    "SHRIRAMFIN", "ADANIENT", "HDFCLIFE", "ICICIGI", "PIDILITIND",
    "HAVELLS", "DMART", "SIEMENS", "BOSCHLTD", "ABB",
    "MUTHOOTFIN", "CHOLAFIN", "GODREJCP", "MARICO", "TORNTPHARM",
    "DABUR", "PGHH", "COLPAL", "BERGEPAINT", "AMBUJACEM",
    "ACC", "MOTHERSON", "TVSMOTOR", "MCDOWELL-N", "IDEA",
    "BANKBARODA", "CANBK", "PNB", "IDFCFIRSTB", "FEDERALBNK",
    "AUBANK", "RBLBANK", "BANDHANBNK", "LUPIN", "BIOCON",
    "AUROPHARMA", "CADILAHC", "ALKEM", "IPCALAB", "NATCOPHARM",
    "PETRONET", "IGL", "MGL", "GUJGASLTD", "CONCOR",
    "IRCTC", "DELHIVERY", "ZOMATO", "PAYTM", "NYKAA",
    "ADANIGREEN", "ADANITRANS", "ATGL", "CESC", "TORNTPOWER",
]

INTERVAL = "15minute"
INTERVAL_LABEL = "15m"      # stored in ohlcv_cache.interval
DHAN_INTERVAL = 15          # Dhan API integer
CHUNK_DAYS = 90             # Dhan's max per request
SLEEP_BETWEEN_CALLS = 0.3   # seconds — gentle pacing


# ── Date range chunker ────────────────────────────────────────

def _chunks(end_date: date, total_days: int, chunk: int):
    """Yield (from_date, to_date) pairs, newest-first."""
    current_end = end_date
    remaining = total_days
    while remaining > 0:
        days_this = min(chunk, remaining)
        current_start = current_end - timedelta(days=days_this - 1)
        yield current_start, current_end
        current_end = current_start - timedelta(days=1)
        remaining -= days_this


# ── Dhan response → DataFrame ─────────────────────────────────

def _parse_response(resp: dict, ticker: str) -> list[dict]:
    """Convert Dhan intraday_minute_data response to list of bar dicts."""
    import pandas as pd

    if not resp or resp.get("status") != "success":
        return []
    raw = resp.get("data", {})
    if not raw:
        return []

    try:
        if isinstance(raw, dict):
            first_val = next(iter(raw.values()), None)
            if isinstance(first_val, (list, tuple)):
                df = pd.DataFrame(raw)
            else:
                df = pd.DataFrame([raw])
        elif isinstance(raw, list):
            df = pd.DataFrame(raw)
        else:
            return []

        if df.empty:
            return []

        # Normalise column names
        rename = {
            "timestamp": "bar_date", "start_Time": "bar_date",
            "open": "open", "high": "high",
            "low": "low", "close": "close", "volume": "volume",
        }
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

        if "bar_date" not in df.columns:
            time_cols = [c for c in df.columns if "time" in c.lower() or "date" in c.lower()]
            if time_cols:
                df = df.rename(columns={time_cols[0]: "bar_date"})
            else:
                return []

        # Parse timestamps
        if df["bar_date"].dtype in ("float64", "int64"):
            df["bar_date"] = pd.to_datetime(df["bar_date"], unit="s")
        else:
            df["bar_date"] = pd.to_datetime(df["bar_date"], errors="coerce")

        df = df.dropna(subset=["bar_date", "open", "close"])

        bars = []
        for _, row in df.iterrows():
            bars.append({
                "ticker":    ticker,
                "exchange":  "NSE",
                "interval":  INTERVAL_LABEL,
                "bar_date":  row["bar_date"].to_pydatetime(),
                "open":      float(row["open"]),
                "high":      float(row["high"]),
                "low":       float(row["low"]),
                "close":     float(row["close"]),
                "volume":    int(float(row.get("volume", 0))),
                "source":    "dhan",
            })
        return bars
    except Exception as e:
        logger.debug("Parse error for %s: %s", ticker, e)
        return []


# ── Idempotent DB upsert ──────────────────────────────────────

def _upsert_bars(bars: list[dict], session) -> int:
    """INSERT ON CONFLICT DO NOTHING — safe to call on duplicate chunks."""
    if not bars:
        return 0
    from sqlalchemy import text
    sql = text("""
        INSERT INTO ohlcv_cache
          (ticker, exchange, interval, bar_date, open, high, low, close, volume, source, fetched_at)
        VALUES
          (:ticker, :exchange, :interval, :bar_date, :open, :high, :low, :close, :volume, :source, NOW())
        ON CONFLICT (ticker, interval, bar_date) DO NOTHING
    """)
    session.execute(sql, bars)
    session.commit()
    return len(bars)


# ── Progress tracking ─────────────────────────────────────────

def _mark_done(session, ticker: str, chunk_end: date) -> None:
    from sqlalchemy import text
    session.execute(text("""
        INSERT INTO backfill_progress (ticker, interval, chunk_end, completed_at)
        VALUES (:ticker, :interval, :chunk_end, NOW())
        ON CONFLICT (ticker, interval, chunk_end) DO NOTHING
    """), {"ticker": ticker, "interval": INTERVAL_LABEL, "chunk_end": chunk_end.isoformat()})
    session.commit()


def _is_done(session, ticker: str, chunk_end: date) -> bool:
    from sqlalchemy import text
    row = session.execute(text("""
        SELECT 1 FROM backfill_progress
        WHERE ticker = :ticker AND interval = :interval AND chunk_end = :chunk_end
    """), {"ticker": ticker, "interval": INTERVAL_LABEL, "chunk_end": chunk_end.isoformat()}).fetchone()
    return row is not None


def _ensure_progress_table(session) -> None:
    from sqlalchemy import text
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS backfill_progress (
            ticker      VARCHAR(30) NOT NULL,
            interval    VARCHAR(10) NOT NULL,
            chunk_end   DATE NOT NULL,
            completed_at TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY (ticker, interval, chunk_end)
        )
    """))
    session.commit()


# ── Corporate action skip ─────────────────────────────────────

def _build_ca_skip_dates() -> set[date]:
    """
    Cheap corporate action protection: skip ±5 trading days around
    known NSE split/bonus events. Returns a set of dates to skip.

    This prevents phantom 5 EMA signals from price discontinuities.
    Update quarterly from: https://www.nseindia.com/corporates/content/ca_equity.htm

    Format: (ticker, ex_date) — skip ex_date ± 5 calendar days.
    """
    KNOWN_CA_EVENTS = [
        # (ticker, ex_date)
        ("RELIANCE",   date(2024, 7, 18)),   # Rights issue
        ("TATASTEEL",  date(2024, 7, 1)),    # Merger
        ("HDFCBANK",   date(2023, 7, 1)),    # HDFC merger
        ("BAJFINANCE",  date(2024, 9, 13)),  # Stock split 1:2
        ("WIPRO",      date(2024, 3, 13)),   # Bonus 1:1
        # Add more from NSE CA page quarterly
    ]
    skip: set[date] = set()
    for _ticker, ex_date in KNOWN_CA_EVENTS:
        for d in range(-5, 6):
            skip.add(ex_date + timedelta(days=d))
    return skip


# ── Single ticker backfill ────────────────────────────────────

def backfill_ticker(
    dhan_source,
    ticker: str,
    total_days: int,
    session,
    resume: bool,
    ca_skip_dates: set[date],
) -> int:
    """Backfill one ticker. Returns total bars written."""
    end = date.today()
    total_bars = 0
    skipped_chunks = 0

    # Resolve security_id
    sec_id = dhan_source._resolve_security_id(ticker)
    if not sec_id:
        logger.warning("%s: no security_id found — skipping", ticker)
        return 0

    for from_date, to_date in _chunks(end, total_days, CHUNK_DAYS):
        if resume and _is_done(session, ticker, to_date):
            skipped_chunks += 1
            continue

        # Skip chunks that overlap corporate action dates
        chunk_dates = {from_date + timedelta(days=d) for d in range((to_date - from_date).days + 1)}
        if chunk_dates & ca_skip_dates:
            logger.info("%s: skipping chunk %s–%s (corporate action window)", ticker, from_date, to_date)
            _mark_done(session, ticker, to_date)
            continue

        try:
            resp = dhan_source.client.intraday_minute_data(
                security_id=sec_id,
                exchange_segment="NSE_EQ",
                instrument_type="EQUITY",
                from_date=from_date.strftime("%Y-%m-%d 09:15:00"),
                to_date=to_date.strftime("%Y-%m-%d 15:30:00"),
                interval=DHAN_INTERVAL,
            )
            bars = _parse_response(resp, ticker)
            if bars:
                written = _upsert_bars(bars, session)
                total_bars += written
            _mark_done(session, ticker, to_date)
            logger.info(
                "%s %s→%s: %d bars (total=%d)",
                ticker, from_date, to_date, len(bars), total_bars,
            )
        except Exception as e:
            logger.error("%s %s→%s: %s", ticker, from_date, to_date, e)
            # Continue — don't let one bad chunk kill the run

        time.sleep(SLEEP_BETWEEN_CALLS)

    if skipped_chunks:
        logger.info("%s: skipped %d already-complete chunks (--resume)", ticker, skipped_chunks)
    return total_bars


# ── Main ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Dhan intraday OHLCV backfill")
    parser.add_argument("--years",  type=int, default=5,  help="Years of history (default 5)")
    parser.add_argument("--ticker", type=str, default=None, help="Single ticker (default: all Nifty 100)")
    parser.add_argument("--resume", action="store_true", help="Skip chunks already in backfill_progress")
    parser.add_argument("--dump-universe", action="store_true", help="Print universe and exit")
    args = parser.parse_args()

    if args.dump_universe:
        for t in NIFTY_100:
            print(t)
        return

    total_days = args.years * 365
    universe = [args.ticker.upper()] if args.ticker else NIFTY_100

    logger.info(
        "Backfill start: %d tickers × %d years × 15-min bars",
        len(universe), args.years,
    )

    # Setup DB
    from mcp_server.db import SessionLocal
    from mcp_server.data_provider import get_provider

    session = SessionLocal()
    _ensure_progress_table(session)

    # Get Dhan source
    provider = get_provider()
    dhan_source = provider.dhan
    if not dhan_source.logged_in:
        ok = dhan_source.login()
        if not ok:
            logger.error("Dhan login failed — check DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in .env")
            sys.exit(1)

    ca_skip_dates = _build_ca_skip_dates()
    grand_total = 0
    start_time = datetime.now()

    for i, ticker in enumerate(universe, 1):
        logger.info("[%d/%d] %s", i, len(universe), ticker)
        bars = backfill_ticker(
            dhan_source, ticker, total_days, session,
            resume=args.resume, ca_skip_dates=ca_skip_dates,
        )
        grand_total += bars
        elapsed = (datetime.now() - start_time).total_seconds()
        eta_s = (elapsed / i) * (len(universe) - i) if i > 0 else 0
        logger.info(
            "Progress: %d/%d tickers | %d total bars | ETA %.0f min",
            i, len(universe), grand_total, eta_s / 60,
        )

    session.close()
    elapsed_min = (datetime.now() - start_time).total_seconds() / 60
    logger.info(
        "DONE: %d tickers, %d bars in %.1f min",
        len(universe), grand_total, elapsed_min,
    )
    logger.info(
        "Next: run backtest validation on pos_5ema with timeframe=15m"
    )


if __name__ == "__main__":
    main()
