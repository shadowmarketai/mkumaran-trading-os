"""
BankNifty Weekly Options Chain Backfill — Dhan v2

Pulls 15-min OHLCV for BankNifty weekly option contracts from Dhan's
intraday_minute_data API and stores in options_chain_cache.

Data availability caveat
─────────────────────────
Each option contract requires its security_id from the Dhan scrip master CSV.
The scrip master includes CURRENTLY ACTIVE and RECENTLY EXPIRED contracts
but may not include contracts that expired > 6-12 months ago. Run the
--check-coverage flag first to see how many historical expiries are available
before committing to the full backfill.

Usage
─────
    # Check what's available before running
    python scripts/backfill_dhan_banknifty_options.py --check-coverage

    # Smoke test — one expiry only
    python scripts/backfill_dhan_banknifty_options.py --expiry 2024-06-06 --dry-run

    # Full backfill from Jan 2023
    python scripts/backfill_dhan_banknifty_options.py --resume

    # Backfill from a specific start date
    python scripts/backfill_dhan_banknifty_options.py --from-date 2024-01-01 --resume

After completion, run the data quality checks in:
    docs/strategy_validation/banknifty_strangle_test_plan.md

Columns in options_chain_cache
───────────────────────────────
    underlying   VARCHAR(20)   — e.g. 'BANKNIFTY'
    expiry_date  DATE
    strike       NUMERIC(10,2)
    option_type  VARCHAR(2)    — 'CE' or 'PE'
    bar_time     TIMESTAMP     — 15-min bar open time (IST)
    open, high, low, close  NUMERIC(12,2)
    volume       BIGINT
    oi           BIGINT        — open interest (0 if unavailable)
    source       VARCHAR(20)   — 'dhan'
    fetched_at   TIMESTAMP
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("bn_options_backfill")


# ── Constants ───────────────────────────────────────────────────────

UNDERLYING = "BANKNIFTY"

# BankNifty weekly expiry changed from Thursday to Wednesday in Oct 2024.
# The script detects expiry day from the scrip master rather than hardcoding.
# Historical expiry days: Thursday (pre-Oct 2024), Wednesday (Oct 2024+)
EXCHANGE_SEGMENT = "NSE_FNO"
INSTRUMENT_TYPE  = "OPTIDX"

INTERVAL_MIN = 15           # 15-minute bars
CHUNK_DAYS   = 5            # max days per API call (options can be stricter)
SLEEP_BETWEEN_CALLS = 0.4   # seconds — Dhan rate limit buffer

# Strike range: pull ATM ± this many percent
STRIKE_RANGE_PCT = 0.15     # 15% around spot

# Strike step for BankNifty (₹100 increments)
STRIKE_STEP = 100.0

# Market hours
MARKET_OPEN  = "09:15:00"
MARKET_CLOSE = "15:30:00"


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
    source      VARCHAR(20)   DEFAULT 'dhan',
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
    expiry_date  DATE        NOT NULL,
    completed_at TIMESTAMP   DEFAULT NOW(),
    bars_written INTEGER     DEFAULT 0,
    PRIMARY KEY (underlying, expiry_date)
);
"""


# ── Scrip master helpers ────────────────────────────────────────────

def _load_scrip_master():
    """Download and cache Dhan scrip master CSV."""
    import pandas as pd
    import io
    import urllib.request

    url = "https://images.dhan.co/api-data/api-scrip-master.csv"
    try:
        raw = urllib.request.urlopen(url, timeout=30).read()
        df = pd.read_csv(io.BytesIO(raw), low_memory=False)
        logger.info("Scrip master loaded: %d rows", len(df))
        return df
    except Exception as e:
        logger.error("Could not load scrip master: %s", e)
        return pd.DataFrame()


def _find_option_security_id(
    scrip_df,
    symbol: str,
    expiry: date,
    strike: float,
    option_type: str,  # "CE" or "PE"
) -> str | None:
    """Return the Dhan security_id for a specific option contract."""
    if scrip_df.empty:
        return None

    expiry_str = expiry.strftime("%Y-%m-%d")

    # Filter: symbol, instrument OPTIDX, expiry, strike, CE/PE
    mask = (
        scrip_df["SEM_EXM_EXCH_ID"].astype(str).str.upper().isin(["NSE", "NFO"])
        & scrip_df["SEM_INSTRUMENT_NAME"].astype(str).str.upper().isin(["OPTIDX"])
        & scrip_df["SEM_TRADING_SYMBOL"].astype(str).str.upper().str.startswith(symbol.upper())
        & (scrip_df["SEM_EXPIRY_DATE"].astype(str) == expiry_str)
        & (scrip_df["SEM_STRIKE_PRICE"].astype(float) == float(strike))
        & scrip_df["SEM_TRADING_SYMBOL"].astype(str).str.upper().str.endswith(option_type.upper())
    )
    matches = scrip_df[mask]
    if matches.empty:
        return None
    return str(matches.iloc[0]["SEM_SMST_SECURITY_ID"])


def _get_banknifty_expiries(scrip_df, from_date: date, to_date: date) -> list[date]:
    """Get all BankNifty weekly expiry dates in the range from the scrip master."""
    if scrip_df.empty:
        return []

    mask = (
        scrip_df["SEM_INSTRUMENT_NAME"].astype(str).str.upper().isin(["OPTIDX"])
        & scrip_df["SEM_TRADING_SYMBOL"].astype(str).str.upper().str.startswith("BANKNIFTY")
        & (scrip_df["SEM_EXM_EXCH_ID"].astype(str).str.upper().isin(["NSE", "NFO"]))
    )
    rows = scrip_df[mask].copy()
    if rows.empty:
        return []

    expiries = set()
    for _, row in rows.iterrows():
        exp_str = str(row.get("SEM_EXPIRY_DATE", "")).strip()
        try:
            exp_date = date.fromisoformat(exp_str[:10])
            if from_date <= exp_date <= to_date:
                expiries.add(exp_date)
        except (ValueError, TypeError):
            pass

    return sorted(expiries)


# ── Data parsing ────────────────────────────────────────────────────

def _parse_ohlcv(resp: dict, underlying: str, expiry: date, strike: float, option_type: str) -> list[dict]:
    """Convert Dhan intraday response to list of bar dicts."""
    import pandas as pd

    if not resp or resp.get("status") != "success":
        return []
    raw = resp.get("data", {})
    if not raw:
        return []

    try:
        if isinstance(raw, dict):
            first = next(iter(raw.values()), None)
            df = pd.DataFrame(raw) if isinstance(first, (list, tuple)) else pd.DataFrame([raw])
        elif isinstance(raw, list):
            df = pd.DataFrame(raw)
        else:
            return []

        if df.empty:
            return []

        rename = {
            "timestamp": "bar_time", "start_Time": "bar_time",
            "open": "open", "high": "high", "low": "low",
            "close": "close", "volume": "volume", "oi": "oi",
        }
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

        if "bar_time" not in df.columns:
            time_cols = [c for c in df.columns if "time" in c.lower() or "date" in c.lower()]
            if time_cols:
                df = df.rename(columns={time_cols[0]: "bar_time"})
            else:
                return []

        if df["bar_time"].dtype in ("float64", "int64"):
            df["bar_time"] = pd.to_datetime(df["bar_time"], unit="s")
        else:
            df["bar_time"] = pd.to_datetime(df["bar_time"], errors="coerce")

        df = df.dropna(subset=["bar_time"])

        bars = []
        for _, row in df.iterrows():
            bars.append({
                "underlying":   underlying,
                "expiry_date":  expiry.isoformat(),
                "strike":       float(strike),
                "option_type":  option_type,
                "bar_time":     row["bar_time"].to_pydatetime(),
                "open":         float(row.get("open", 0) or 0),
                "high":         float(row.get("high", 0) or 0),
                "low":          float(row.get("low", 0) or 0),
                "close":        float(row.get("close", 0) or 0),
                "volume":       int(float(row.get("volume", 0) or 0)),
                "oi":           int(float(row.get("oi", 0) or 0)),
                "source":       "dhan",
            })
        return bars
    except Exception as e:
        logger.debug("Parse error: %s", e)
        return []


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


def _mark_done(session, underlying: str, expiry: date, bars_written: int) -> None:
    from sqlalchemy import text
    session.execute(text("""
        INSERT INTO backfill_progress_options (underlying, expiry_date, completed_at, bars_written)
        VALUES (:u, :e, NOW(), :b)
        ON CONFLICT (underlying, expiry_date) DO UPDATE SET completed_at=NOW(), bars_written=:b
    """), {"u": underlying, "e": expiry.isoformat(), "b": bars_written})
    session.commit()


def _is_done(session, underlying: str, expiry: date) -> bool:
    from sqlalchemy import text
    row = session.execute(text("""
        SELECT 1 FROM backfill_progress_options
        WHERE underlying=:u AND expiry_date=:e
    """), {"u": underlying, "e": expiry.isoformat()}).fetchone()
    return row is not None


# ── Spot-price lookup for strike range ─────────────────────────────

def _get_spot_at_expiry_start(expiry: date) -> float | None:
    """Get BankNifty spot at the Monday before expiry (entry day)."""
    try:
        import yfinance as yf
        mon = expiry - timedelta(days=expiry.weekday())  # Monday of that week
        tue = mon + timedelta(days=1)
        df = yf.download("^NSEBANK", start=mon, end=tue, interval="1d",
                         progress=False, auto_adjust=True)
        if df is not None and not df.empty:
            return float(df["Close"].iloc[0])
    except Exception:
        pass
    return None


# ── Per-expiry backfill ─────────────────────────────────────────────

def backfill_expiry(
    dhan_client,
    scrip_df,
    expiry: date,
    session,
    dry_run: bool,
) -> int:
    """Backfill all option contracts for one BankNifty weekly expiry.
    Returns total bars written.
    """
    # Determine entry week: Monday through Thursday (expiry day)
    expiry_weekday = expiry.weekday()   # 0=Mon … 3=Thu … 2=Wed
    monday = expiry - timedelta(days=expiry_weekday)
    entry_start = datetime.combine(monday, datetime.strptime(MARKET_OPEN, "%H:%M:%S").time())
    entry_end   = datetime.combine(expiry, datetime.strptime(MARKET_CLOSE, "%H:%M:%S").time())

    # Get spot to determine strike range
    spot = _get_spot_at_expiry_start(expiry)
    if not spot:
        logger.warning("%s: no spot price found — skipping", expiry)
        return 0

    atm = round(spot / STRIKE_STEP) * STRIKE_STEP
    range_pts = spot * STRIKE_RANGE_PCT
    low_strike  = atm - round(range_pts / STRIKE_STEP) * STRIKE_STEP
    high_strike = atm + round(range_pts / STRIKE_STEP) * STRIKE_STEP

    strikes = []
    s = low_strike
    while s <= high_strike:
        strikes.append(s)
        s += STRIKE_STEP

    logger.info(
        "%s: spot=%.0f  ATM=%.0f  strikes=%d  entry=%s→%s",
        expiry, spot, atm, len(strikes),
        entry_start.strftime("%Y-%m-%d"), entry_end.strftime("%Y-%m-%d"),
    )

    if dry_run:
        # Verify security_ids only, don't write
        found = 0
        for strike in strikes[:5]:   # sample 5 strikes
            for otype in ("CE", "PE"):
                sec_id = _find_option_security_id(scrip_df, UNDERLYING, expiry, strike, otype)
                status = "✓" if sec_id else "✗ MISSING"
                logger.info("  DRY-RUN %s %.0f %s  sec_id=%s  %s",
                             expiry, strike, otype, sec_id, status)
                if sec_id:
                    found += 1
        logger.info("DRY-RUN: found %d/%d security_ids in scrip master for %s",
                    found, 5 * 2, expiry)
        return 0

    total_bars = 0
    missing_contracts = 0

    for strike in strikes:
        for option_type in ("CE", "PE"):
            sec_id = _find_option_security_id(scrip_df, UNDERLYING, expiry, strike, option_type)
            if not sec_id:
                missing_contracts += 1
                logger.debug("  No sec_id: %s %.0f %s", expiry, strike, option_type)
                continue

            # Fetch in chunks (each call covers up to CHUNK_DAYS)
            current = entry_start
            while current < entry_end:
                chunk_end = min(current + timedelta(days=CHUNK_DAYS), entry_end)
                try:
                    resp = dhan_client.intraday_minute_data(
                        security_id=sec_id,
                        exchange_segment=EXCHANGE_SEGMENT,
                        instrument_type=INSTRUMENT_TYPE,
                        from_date=current.strftime("%Y-%m-%d %H:%M:%S"),
                        to_date=chunk_end.strftime("%Y-%m-%d %H:%M:%S"),
                        interval=INTERVAL_MIN,
                    )
                    bars = _parse_ohlcv(resp, UNDERLYING, expiry, strike, option_type)
                    if bars:
                        written = _upsert_bars(bars, session)
                        total_bars += written
                except Exception as e:
                    logger.debug("  API error %s %.0f %s: %s", expiry, strike, option_type, e)

                time.sleep(SLEEP_BETWEEN_CALLS)
                current = chunk_end + timedelta(seconds=1)

    if missing_contracts:
        logger.warning(
            "%s: %d/%d contracts missing from scrip master (expired too long ago?)",
            expiry, missing_contracts, len(strikes) * 2,
        )

    return total_bars


# ── Main ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="BankNifty weekly options chain backfill")
    parser.add_argument("--from-date", default="2023-01-01",
                        help="Backfill start date (YYYY-MM-DD)")
    parser.add_argument("--to-date", default=date.today().isoformat(),
                        help="Backfill end date (YYYY-MM-DD)")
    parser.add_argument("--expiry", default=None,
                        help="Single expiry only (YYYY-MM-DD) — for smoke test")
    parser.add_argument("--dry-run", action="store_true",
                        help="Check security_ids without writing data")
    parser.add_argument("--resume", action="store_true",
                        help="Skip already-completed expiries")
    parser.add_argument("--check-coverage", action="store_true",
                        help="Print available expiries from scrip master and exit")
    args = parser.parse_args()

    from_date = date.fromisoformat(args.from_date)
    to_date   = date.fromisoformat(args.to_date)

    # Load scrip master
    logger.info("Loading Dhan scrip master...")
    scrip_df = _load_scrip_master()
    if scrip_df.empty:
        logger.error("Scrip master unavailable — cannot resolve security_ids")
        sys.exit(1)

    # Get list of expiries
    if args.expiry:
        expiries = [date.fromisoformat(args.expiry)]
    else:
        expiries = _get_banknifty_expiries(scrip_df, from_date, to_date)

    if not expiries:
        logger.warning("No BankNifty expiries found in scrip master for %s → %s", from_date, to_date)
        logger.warning("This likely means historical contracts are not in the current scrip master.")
        logger.warning("Try --from-date with a more recent date, or check Dhan data coverage.")
        sys.exit(1)

    if args.check_coverage:
        print(f"\nBankNifty weekly expiries available in Dhan scrip master: {len(expiries)}")
        print(f"Date range: {expiries[0]} → {expiries[-1]}")
        print("\nFirst 10:")
        for e in expiries[:10]:
            print(f"  {e}")
        print("\nLast 10:")
        for e in expiries[-10:]:
            print(f"  {e}")
        print("\nNote: if count < 40, your Dhan subscription may lack historical F&O data.")
        print("Consider adjusting --from-date to match available coverage.")
        return

    logger.info(
        "Backfill: %d expiries from %s to %s | dry_run=%s | resume=%s",
        len(expiries), expiries[0], expiries[-1], args.dry_run, args.resume,
    )

    # Connect DB
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

    # Connect Dhan
    from mcp_server.data_provider import get_provider
    provider = get_provider()
    dhan = provider.dhan
    if not dhan.logged_in:
        ok = dhan.login()
        if not ok:
            logger.error("Dhan login failed — check DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN")
            session.close()
            sys.exit(1)

    dhan_client = dhan.client
    grand_total = 0
    start_time = datetime.now()

    for i, expiry in enumerate(expiries, 1):
        if args.resume and not args.dry_run and _is_done(session, UNDERLYING, expiry):
            logger.info("[%d/%d] %s — already done (skipping)", i, len(expiries), expiry)
            continue

        t0 = datetime.now()
        bars = backfill_expiry(dhan_client, scrip_df, expiry, session, dry_run=args.dry_run)
        elapsed = (datetime.now() - t0).total_seconds()
        grand_total += bars

        if not args.dry_run:
            _mark_done(session, UNDERLYING, expiry, bars)

        total_elapsed = (datetime.now() - start_time).total_seconds()
        eta = (total_elapsed / i) * (len(expiries) - i) if i > 0 else 0
        logger.info(
            "[%d/%d] %s: %d bars in %.0fs | total=%d bars | ETA %.0f min",
            i, len(expiries), expiry, bars, elapsed, grand_total, eta / 60,
        )

    session.close()
    total_min = (datetime.now() - start_time).total_seconds() / 60
    logger.info(
        "DONE: %d expiries, %d bars in %.1f min",
        len(expiries), grand_total, total_min,
    )
    if not args.dry_run:
        logger.info("Next: run data quality SQL from banknifty_strangle_test_plan.md")


if __name__ == "__main__":
    main()
