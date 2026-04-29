"""
BankNifty Weekly Options Backfill — NSE F&O Bhavcopy (free, public)

NSE publishes daily F&O bhavcopy files at:
  https://archives.nseindia.com/content/historical/DERIVATIVES/<YEAR>/<MON>/fo<DD><MON><YEAR>bhav.csv.zip

Each file contains OHLCV + OI for every option contract that traded that day.
This script downloads 3 years of bhavcopy files, extracts BankNifty weekly
option rows, and stores them in options_chain_cache.

Data model change vs 15-min plan
──────────────────────────────────
Instead of 15-min bars, each row is ONE TRADING DAY's OHLCV for a contract.
The strangle validation script will check exit conditions at each day's close
(50% profit target, 2x stop-loss, time exit on expiry day).
This is how most retail options sellers actually operate — no intraday HFT.

Usage
─────
    # Check what NSE has (quick)
    python scripts/backfill_nse_banknifty_options.py --check-coverage

    # Smoke test — one month
    python scripts/backfill_nse_banknifty_options.py --month 2024-01

    # Full backfill (2023-01 → today)
    python scripts/backfill_nse_banknifty_options.py --resume

    # Specific date range
    python scripts/backfill_nse_banknifty_options.py --from-date 2024-01-01 --resume

Data quality: after full run, verify with SQL in banknifty_strangle_test_plan.md.
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import sys
import time
import zipfile
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("nse_bhav_backfill")


# ── Constants ───────────────────────────────────────────────────────

UNDERLYING = "BANKNIFTY"

# NSE changed their bhavcopy URL format in mid-2024.
# The script tries all known formats in order — first match wins.
NSE_BHAV_URLS = [
    # Format 1: archives.nseindia.com historical path (works for ~2020–Jun 2024)
    "https://archives.nseindia.com/content/historical/DERIVATIVES/{year}/{mon}/fo{dd}{mon}{year}bhav.csv.zip",
    # Format 2: older archives path (fallback for Format 1)
    "https://archives.nseindia.com/archives/fo/bhav/fo{dd}{mon}{year}bhav.csv.zip",
    # Format 3: nsearchives.nseindia.com — new domain, new naming (Jul 2024+)
    "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{ymd}_F_0000.csv.zip",
    # Format 4: nsearchives alternate path
    "https://nsearchives.nseindia.com/archives/fo/bhav/fo{dd}{mon}{year}bhav.csv.zip",
]

SLEEP_BETWEEN_DAYS = 0.3    # seconds — be gentle with NSE servers
MAX_RETRIES = 3

# NSE month abbreviations (their URL format)
NSE_MONTHS = {
    1: "JAN", 2: "FEB", 3: "MAR", 4: "APR",
    5: "MAY", 6: "JUN", 7: "JUL", 8: "AUG",
    9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC",
}


# ── DB schema ───────────────────────────────────────────────────────

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS options_chain_cache (
    id          BIGSERIAL PRIMARY KEY,
    underlying  VARCHAR(20)   NOT NULL,
    expiry_date DATE          NOT NULL,
    strike      NUMERIC(10,2) NOT NULL,
    option_type VARCHAR(2)    NOT NULL,
    bar_time    TIMESTAMP     NOT NULL,
    open        NUMERIC(12,2),
    high        NUMERIC(12,2),
    low         NUMERIC(12,2),
    close       NUMERIC(12,2),
    volume      BIGINT        DEFAULT 0,
    oi          BIGINT        DEFAULT 0,
    source      VARCHAR(20)   DEFAULT 'nse_bhav',
    fetched_at  TIMESTAMP     DEFAULT NOW(),
    UNIQUE (underlying, expiry_date, strike, option_type, bar_time)
);

CREATE INDEX IF NOT EXISTS idx_occ_lookup
    ON options_chain_cache (underlying, expiry_date, strike, option_type);
CREATE INDEX IF NOT EXISTS idx_occ_time
    ON options_chain_cache (underlying, bar_time);
"""

CREATE_PROGRESS_SQL = """
CREATE TABLE IF NOT EXISTS backfill_progress_options (
    underlying   VARCHAR(20) NOT NULL,
    trade_date   DATE        NOT NULL,
    completed_at TIMESTAMP   DEFAULT NOW(),
    bars_written INTEGER     DEFAULT 0,
    PRIMARY KEY (underlying, trade_date)
);
"""


# ── NSE bhavcopy fetch ──────────────────────────────────────────────

def _fetch_bhav(trade_date: date):
    """Download and parse NSE F&O bhavcopy for one trading day.

    Returns DataFrame with BankNifty option rows, or None if unavailable.
    """
    import pandas as pd
    import urllib.request
    import urllib.error

    dd  = trade_date.strftime("%d")
    mon = NSE_MONTHS[trade_date.month]
    yr  = trade_date.strftime("%Y")
    ymd = trade_date.strftime("%Y%m%d")   # for new-format URLs

    urls = [u.format(year=yr, mon=mon, dd=dd, ymd=ymd) for u in NSE_BHAV_URLS]

    for url in urls:
        for attempt in range(MAX_RETRIES):
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; mkumaran-backfill/1.0)"},
                )
                raw = urllib.request.urlopen(req, timeout=20).read()
                with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                    csv_name = zf.namelist()[0]
                    with zf.open(csv_name) as f:
                        df = pd.read_csv(f)

                df.columns = [c.strip() for c in df.columns]

                # Handle two known bhavcopy column schemas:
                # Old (pre-2024): INSTRUMENT, SYMBOL, EXPIRY_DT, STRIKE_PR, OPTION_TYP
                # New (2024+):    FinInstrmTp / varies — detect by presence of SYMBOL
                if "SYMBOL" in df.columns and "INSTRUMENT" in df.columns:
                    bn = df[df["SYMBOL"].astype(str).str.strip().str.upper() == "BANKNIFTY"]
                    bn = bn[bn["INSTRUMENT"].astype(str).str.strip().str.upper() == "OPTIDX"]
                else:
                    # New schema: look for BANKNIFTY in any string column
                    str_cols = df.select_dtypes(include="object").columns
                    mask = df[str_cols].apply(
                        lambda col: col.astype(str).str.strip().str.upper() == "BANKNIFTY"
                    ).any(axis=1)
                    bn = df[mask]

                if bn.empty:
                    logger.debug("%s: URL worked but no BANKNIFTY rows — wrong schema?", trade_date)
                    break  # Try next URL

                logger.debug("%s: fetched %d rows via %s", trade_date, len(bn), url.split("/")[-1])
                return bn

            except urllib.error.HTTPError as e:
                if e.code == 404:
                    break   # This URL format is wrong for this date — try next
                logger.debug("HTTP %d for %s attempt %d", e.code, trade_date, attempt + 1)
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1.0 * (attempt + 1))
            except Exception as e:
                logger.debug("Fetch error %s attempt %d: %s", trade_date, attempt + 1, e)
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1.0 * (attempt + 1))

    return None   # All URLs exhausted — likely a holiday


def _parse_bhav_rows(bn_df, trade_date: date) -> list[dict]:
    """Convert bhavcopy DataFrame to list of bar dicts for DB insert."""
    bars = []
    for _, row in bn_df.iterrows():
        try:
            expiry_raw = str(row.get("EXPIRY_DT", "") or "").strip()
            # NSE bhavcopy expiry format: "25-JAN-2024" or "2024-01-25"
            try:
                if "-" in expiry_raw and len(expiry_raw) == 11:
                    expiry = datetime.strptime(expiry_raw, "%d-%b-%Y").date()
                else:
                    expiry = date.fromisoformat(expiry_raw[:10])
            except ValueError:
                continue

            strike = float(str(row.get("STRIKE_PR", "0") or "0").strip())
            option_type = str(row.get("OPTION_TYP", "") or "").strip().upper()
            if option_type not in ("CE", "PE"):
                continue
            if strike <= 0:
                continue

            bars.append({
                "underlying":   UNDERLYING,
                "expiry_date":  expiry.isoformat(),
                "strike":       strike,
                "option_type":  option_type,
                "bar_time":     datetime.combine(trade_date, datetime.min.time()),
                "open":         float(str(row.get("OPEN", "0") or "0").strip() or "0"),
                "high":         float(str(row.get("HIGH", "0") or "0").strip() or "0"),
                "low":          float(str(row.get("LOW", "0") or "0").strip() or "0"),
                "close":        float(str(row.get("CLOSE", "0") or "0").strip() or "0"),
                "volume":       int(float(str(row.get("CONTRACTS", "0") or "0").strip() or "0")),
                "oi":           int(float(str(row.get("OPEN_INT", "0") or "0").strip() or "0")),
                "source":       "nse_bhav",
            })
        except (ValueError, TypeError):
            continue
    return bars


# ── DB helpers ──────────────────────────────────────────────────────

def _upsert_bars(bars: list[dict], session) -> int:
    if not bars:
        return 0
    from sqlalchemy import text
    sql = text("""
        INSERT INTO options_chain_cache
          (underlying, expiry_date, strike, option_type, bar_time,
           open, high, low, close, volume, oi, source, fetched_at)
        VALUES
          (:underlying, :expiry_date, :strike, :option_type, :bar_time,
           :open, :high, :low, :close, :volume, :oi, :source, NOW())
        ON CONFLICT (underlying, expiry_date, strike, option_type, bar_time) DO NOTHING
    """)
    session.execute(sql, bars)
    session.commit()
    return len(bars)


def _mark_done(session, trade_date: date, bars_written: int) -> None:
    from sqlalchemy import text
    session.execute(text("""
        INSERT INTO backfill_progress_options (underlying, trade_date, completed_at, bars_written)
        VALUES (:u, :d, NOW(), :b)
        ON CONFLICT (underlying, trade_date) DO UPDATE SET completed_at=NOW(), bars_written=:b
    """), {"u": UNDERLYING, "d": trade_date.isoformat(), "b": bars_written})
    session.commit()


def _is_done(session, trade_date: date) -> bool:
    from sqlalchemy import text
    row = session.execute(text("""
        SELECT 1 FROM backfill_progress_options
        WHERE underlying=:u AND trade_date=:d
    """), {"u": UNDERLYING, "d": trade_date.isoformat()}).fetchone()
    return row is not None


# ── Trading days generator ──────────────────────────────────────────

def _trading_days(from_date: date, to_date: date):
    """Yield weekdays (Mon–Fri) in range. NSE holidays are handled by 404."""
    current = from_date
    while current <= to_date:
        if current.weekday() < 5:   # Monday–Friday
            yield current
        current += timedelta(days=1)


# ── Coverage check ──────────────────────────────────────────────────

def check_coverage(from_date: date, to_date: date) -> None:
    """Try a sample of dates to see what NSE has."""
    import random
    sample_dates = list(_trading_days(from_date, to_date))
    sample = random.sample(sample_dates, min(10, len(sample_dates)))
    sample.sort()

    print(f"\nNSE bhavcopy coverage check ({len(sample_dates)} trading days in range)")
    print(f"Testing {len(sample)} random dates...\n")

    available = 0
    for d in sample:
        df = _fetch_bhav(d)
        if df is not None and not df.empty:
            strikes = df["STRIKE_PR"].nunique() if "STRIKE_PR" in df.columns else 0
            print(f"  {d}: ✓  {len(df)} rows, {strikes} strikes")
            available += 1
        else:
            print(f"  {d}: ✗  no data (holiday or 404)")
        time.sleep(SLEEP_BETWEEN_DAYS)

    print(f"\nResult: {available}/{len(sample)} sample dates have BankNifty option data.")
    print(f"Estimated available trading days: {int(available/len(sample)*len(sample_dates))}/{len(sample_dates)}")
    if available >= 6:
        print("✓ NSE bhavcopy has good coverage. Proceed with full backfill.")
    else:
        print("✗ Low coverage. Check network access to archives.nseindia.com.")


# ── Main ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="NSE bhavcopy BankNifty options backfill")
    parser.add_argument("--from-date", default="2023-01-01")
    parser.add_argument("--to-date", default=date.today().isoformat())
    parser.add_argument("--month", default=None,
                        help="Backfill one month only (YYYY-MM), e.g. 2024-01")
    parser.add_argument("--resume", action="store_true",
                        help="Skip already-completed dates")
    parser.add_argument("--check-coverage", action="store_true",
                        help="Test a sample of dates before committing to full run")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and parse but don't write to DB")
    args = parser.parse_args()

    if args.month:
        yr, mo = args.month.split("-")
        from_date = date(int(yr), int(mo), 1)
        if int(mo) == 12:
            to_date = date(int(yr) + 1, 1, 1) - timedelta(days=1)
        else:
            to_date = date(int(yr), int(mo) + 1, 1) - timedelta(days=1)
    else:
        from_date = date.fromisoformat(args.from_date)
        to_date   = date.fromisoformat(args.to_date)

    if args.check_coverage:
        check_coverage(from_date, to_date)
        return

    logger.info(
        "NSE bhavcopy backfill: %s → %s | resume=%s | dry_run=%s",
        from_date, to_date, args.resume, args.dry_run,
    )

    if not args.dry_run:
        from mcp_server.db import SessionLocal
        from sqlalchemy import text as _text
        session = SessionLocal()
        try:
            session.execute(_text(CREATE_TABLE_SQL))
            session.execute(_text(CREATE_PROGRESS_SQL))
            session.commit()
        except Exception as e:
            logger.error("DB setup failed: %s", e)
            session.close()
            sys.exit(1)
    else:
        session = None

    grand_total = 0
    trading_days = list(_trading_days(from_date, to_date))
    start_time = datetime.now()

    for i, trade_date in enumerate(trading_days, 1):
        if args.resume and not args.dry_run and _is_done(session, trade_date):
            continue

        bn_df = _fetch_bhav(trade_date)

        if bn_df is None or bn_df.empty:
            # Holiday or no data — mark done so resume skips it
            if not args.dry_run and session:
                _mark_done(session, trade_date, 0)
            continue

        bars = _parse_bhav_rows(bn_df, trade_date)

        if args.dry_run:
            logger.info("DRY-RUN %s: %d rows → %d bars parsed", trade_date, len(bn_df), len(bars))
        else:
            written = _upsert_bars(bars, session)
            grand_total += written
            _mark_done(session, trade_date, written)

        elapsed = (datetime.now() - start_time).total_seconds()
        eta = (elapsed / i) * (len(trading_days) - i) if i > 0 else 0
        if i % 20 == 0 or args.dry_run:
            logger.info(
                "[%d/%d] %s: %d bars | total=%d | ETA %.0f min",
                i, len(trading_days), trade_date, len(bars), grand_total, eta / 60,
            )

        time.sleep(SLEEP_BETWEEN_DAYS)

    if session:
        session.close()

    elapsed_min = (datetime.now() - start_time).total_seconds() / 60
    logger.info(
        "DONE: %d trading days, %d bars written in %.1f min",
        len(trading_days), grand_total, elapsed_min,
    )
    if not args.dry_run:
        logger.info("Next: run data quality SQL from banknifty_strangle_test_plan.md")


if __name__ == "__main__":
    main()
