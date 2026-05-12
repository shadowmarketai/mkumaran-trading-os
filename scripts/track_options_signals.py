"""
Options Signal Forward Tracker

Reads options signals from the DB (source='options_scan') and checks
whether each open signal hit its target or stop-loss within the next
N trading days.

Uses yfinance for settlement prices (not broker — read-only diagnostic).

Usage:
    python scripts/track_options_signals.py
    python scripts/track_options_signals.py --days 5  # look-forward window
    python scripts/track_options_signals.py --since 2026-05-12

Output:
  - Per-signal outcome table (HIT_TARGET / HIT_STOP / OPEN / EXPIRED)
  - Per-strategy summary (win rate, avg P&L pct)
  - Overall options scan performance since launch
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("options_tracker")

LOOK_FORWARD_DAYS = 5   # calendar days to check for outcome
INDEX_TICKERS = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
    "MIDCPNIFTY": "NIFTY_MIDCAP_SELECT.NS",
}


def _get_signals(session, since: date) -> list[dict]:
    from sqlalchemy import text
    rows = session.execute(text("""
        SELECT id, signal_date, ticker, pattern, direction,
               entry_price, stop_loss, target, status, source
        FROM signals
        WHERE source = 'options_scan'
          AND signal_date >= :since
        ORDER BY signal_date DESC, id DESC
    """), {"since": since.isoformat()}).fetchall()
    return [dict(r._mapping) for r in rows]


def _fetch_closes(ticker: str, start: date, end: date) -> dict[date, float]:
    """Fetch daily closes from yfinance for the settlement symbol."""
    import yfinance as yf
    yf_sym = INDEX_TICKERS.get(ticker, ticker + ".NS")
    try:
        df = yf.download(
            yf_sym,
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=True,
            progress=False,
        )
        if df.empty:
            return {}
        closes = df["Close"]
        if hasattr(closes.columns if hasattr(closes, "columns") else None, "__iter__"):
            closes = closes.iloc[:, 0]
        return {d.date(): float(c) for d, c in closes.items()}
    except Exception as e:
        logger.debug("yfinance %s: %s", yf_sym, e)
        return {}


def _determine_outcome(
    signal: dict,
    closes: dict[date, float],
    look_forward: int,
) -> str:
    """
    Returns: HIT_TARGET | HIT_STOP | OPEN | NO_DATA

    For options signals, entry_price = strike, target = target_premium,
    stop_loss = sl_premium. We use the underlying close as a proxy
    (premium outcome isn't tracked — we check directional correctness).
    """
    sig_date = signal["signal_date"]
    if isinstance(sig_date, str):
        sig_date = date.fromisoformat(sig_date)

    entry = signal.get("entry_price", 0) or 0
    target = signal.get("target", 0) or 0
    sl = signal.get("stop_loss", 0) or 0
    direction = (signal.get("direction") or "NEUTRAL").upper()

    if entry <= 0:
        return "NO_DATA"

    # Check each subsequent trading day
    check_end = sig_date + timedelta(days=look_forward)
    for d in sorted(k for k in closes if sig_date < k <= check_end):
        price = closes[d]
        if direction == "LONG":
            if target > entry and price >= target:
                return "HIT_TARGET"
            if sl < entry and price <= sl:
                return "HIT_STOP"
        elif direction == "SHORT":
            if target < entry and price <= target:
                return "HIT_TARGET"
            if sl > entry and price >= sl:
                return "HIT_STOP"
        elif direction == "NEUTRAL":
            # For neutral strategies (straddle sell), we use premium math
            # If entry_price is the strike and no direction, skip directional check
            return "OPEN"

    today = date.today()
    if check_end < today:
        return "EXPIRED"
    return "OPEN"


def main() -> None:
    parser = argparse.ArgumentParser(description="Options signal forward tracker")
    parser.add_argument("--days", type=int, default=LOOK_FORWARD_DAYS,
                        help=f"Look-forward window in calendar days (default {LOOK_FORWARD_DAYS})")
    parser.add_argument("--since", default=None,
                        help="Only check signals since this date (YYYY-MM-DD)")
    args = parser.parse_args()

    since = date.fromisoformat(args.since) if args.since else date.today() - timedelta(days=30)

    from mcp_server.db import SessionLocal
    session = SessionLocal()

    try:
        signals = _get_signals(session, since)
    finally:
        session.close()

    if not signals:
        print(f"No options_scan signals found since {since}.")
        print("Options scan has been live since 2026-05-12. Check back after market hours.")
        return

    logger.info("Found %d signals since %s", len(signals), since)

    # Fetch closes for each unique ticker
    ticker_closes: dict[str, dict[date, float]] = {}
    for sig in signals:
        t = sig["ticker"]
        if t not in ticker_closes:
            fetch_start = since - timedelta(days=5)
            fetch_end = date.today()
            ticker_closes[t] = _fetch_closes(t, fetch_start, fetch_end)

    # Determine outcomes
    results: list[dict] = []
    for sig in signals:
        outcome = _determine_outcome(sig, ticker_closes.get(sig["ticker"], {}), args.days)
        results.append({**sig, "outcome": outcome})

    # Print table
    print()
    print("=" * 80)
    print(f"OPTIONS SCAN SIGNAL TRACKER  |  since {since}  |  {args.days}-day window")
    print("=" * 80)
    print(f"{'Date':<12} {'Ticker':<12} {'Pattern':<30} {'Dir':<8} {'Outcome':<12}")
    print("-" * 80)
    for r in results:
        d = str(r["signal_date"])[:10]
        pat = (r["pattern"] or "")[:28]
        print(f"{d:<12} {r['ticker']:<12} {pat:<30} {(r['direction'] or ''):<8} {r['outcome']:<12}")
    print("=" * 80)

    # Per-strategy summary
    from collections import defaultdict
    by_pattern: dict[str, list[str]] = defaultdict(list)
    for r in results:
        by_pattern[r["pattern"] or "UNKNOWN"].append(r["outcome"])

    print("\nPER-STRATEGY SUMMARY")
    print(f"{'Pattern':<35} {'Signals':>7}  {'Target':>6}  {'Stop':>6}  {'WinRate':>8}")
    print("-" * 70)
    for pat, outcomes in sorted(by_pattern.items()):
        n = len(outcomes)
        hits = outcomes.count("HIT_TARGET")
        stops = outcomes.count("HIT_STOP")
        wr = f"{hits/n*100:.0f}%" if n > 0 else "n/a"
        print(f"{pat[:33]:<35} {n:>7}  {hits:>6}  {stops:>6}  {wr:>8}")

    total = len(results)
    hit = sum(1 for r in results if r["outcome"] == "HIT_TARGET")
    stop = sum(1 for r in results if r["outcome"] == "HIT_STOP")
    opn = sum(1 for r in results if r["outcome"] in ("OPEN", "EXPIRED"))
    print("-" * 70)
    print(f"{'TOTAL':<35} {total:>7}  {hit:>6}  {stop:>6}  {hit/total*100:.0f}%" if total else "No data")
    print()

    # Save report
    out = Path("reports") / f"options_signal_track_{date.today()}.md"
    out.parent.mkdir(exist_ok=True)
    lines = [
        f"# Options Signal Forward Track — {date.today()}",
        f"Period: {since} → {date.today()} | Look-forward: {args.days} days",
        "",
        f"| Date | Ticker | Pattern | Direction | Outcome |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {str(r['signal_date'])[:10]} | {r['ticker']} | {r['pattern']} "
            f"| {r['direction']} | {r['outcome']} |"
        )
    lines += ["", "## Per-Strategy", "", "| Pattern | Signals | HIT | STOP | WinRate |", "|---|---|---|---|---|"]
    for pat, outcomes in sorted(by_pattern.items()):
        n = len(outcomes)
        hits = outcomes.count("HIT_TARGET")
        stops = outcomes.count("HIT_STOP")
        wr = f"{hits/n*100:.0f}%" if n else "n/a"
        lines.append(f"| {pat} | {n} | {hits} | {stops} | {wr} |")
    out.write_text("\n".join(lines))
    logger.info("Report saved: %s", out)


if __name__ == "__main__":
    main()
