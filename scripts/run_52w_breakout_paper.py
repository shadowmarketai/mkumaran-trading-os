#!/usr/bin/env python
"""
52-Week Breakout — daily paper-trade manager.

Run this script each evening after market close (any time after 15:30 IST).
It will:
  1. Check all open 52w paper positions for exit triggers (trail / hard stop / time).
  2. Scan today's closes for fresh 52-week breakouts.
  3. Add new positions (up to MAX_CONCURRENT total open).
  4. Print a summary to stdout.

Usage:
    python scripts/run_52w_breakout_paper.py             # live mode
    python scripts/run_52w_breakout_paper.py --dry-run   # no Sheets writes
    python scripts/run_52w_breakout_paper.py --date 2026-06-02  # back-date

The strategy matches the validated backtest in scripts/validate_52w_breakout.py:
  - Entry   : first close above the 252-day high; no breakout in prior 10 days
  - Exit 1  : close < min(close[-20:])  — trailing stop
  - Exit 2  : close < entry * 0.90      — hard stop
  - Exit 3  : trading days held >= 63   — time limit
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("52w_paper")

# ── Constants (must match validate_52w_breakout.py) ───────────────────────────
LOOKBACK_HIGH  = 252
TRAIL_DAYS     = 20
HARD_STOP_PCT  = 0.10
MAX_HOLD_DAYS  = 63   # trading days
FRESH_DAYS     = 10
MAX_CONCURRENT = 10
POSITION_INR   = 100_000.0
FETCH_DAYS     = 600  # calendar days of history to fetch
SCANNER_NAME   = "52w_breakout"


# ── Data ─────────────────────────────────────────────────────────────────────

def _load_symbols() -> list[str]:
    p = Path("data/nifty500.json")
    if not p.exists():
        p = Path(__file__).resolve().parents[1] / "data" / "nifty500.json"
    with open(p) as f:
        syms = json.load(f)["symbols"]
    return [s for s in syms if "DUMMY" not in s.upper()]


def _fetch_prices(symbols: list[str], start_str: str, end_str: str) -> dict[str, dict[date, float]]:
    """Load close prices from DB first, yfinance for gaps."""
    prices: dict[str, dict[date, float]] = {}

    try:
        from sqlalchemy import text

        from mcp_server.db import engine
        with engine.connect() as conn:
            for sym in symbols:
                rows = conn.execute(
                    text(
                        "SELECT bar_date, close FROM ohlcv_cache "
                        "WHERE ticker=:s AND interval='1d' "
                        "AND bar_date BETWEEN :s0 AND :e "
                        "AND close IS NOT NULL AND close > 0 ORDER BY bar_date"
                    ),
                    {"s": sym, "s0": start_str, "e": end_str},
                ).fetchall()
                if rows:
                    prices[sym] = {
                        (r.bar_date.date() if hasattr(r.bar_date, "date") else r.bar_date): float(r.close)
                        for r in rows
                    }
        logger.info("DB: loaded %d symbols", len(prices))
    except Exception as db_err:
        logger.warning("DB unavailable (%s) — falling back to yfinance", db_err.__class__.__name__)

    missing = [s for s in symbols if s not in prices]
    if missing:
        import pandas as pd
        import yfinance as yf
        logger.info("yfinance fetch: %d symbols", len(missing))
        for i in range(0, len(missing), 50):
            chunk = missing[i : i + 50]
            try:
                raw = yf.download(
                    [s + ".NS" for s in chunk], start=start_str, end=end_str,
                    auto_adjust=True, progress=False, threads=True,
                )
                if raw.empty:
                    continue
                for sym in chunk:
                    try:
                        col = sym + ".NS"
                        closes = (
                            raw["Close"][col].dropna()
                            if isinstance(raw.columns, pd.MultiIndex)
                            else raw["Close"].dropna()
                        )
                        if len(closes) >= LOOKBACK_HIGH:
                            prices[sym] = {d.date(): float(c) for d, c in closes.items()}
                    except Exception:
                        pass
            except Exception as exc:
                logger.warning("yfinance batch %d failed: %s", i, exc)

    return prices


# ── Core logic ────────────────────────────────────────────────────────────────

def _is_fresh_breakout(sym_dates: list[date], sym_closes: list[float], today_idx: int) -> bool:
    """True if today's close is a new 252-day high and no breakout in prior FRESH_DAYS."""
    if today_idx < LOOKBACK_HIGH:
        return False
    today_close = sym_closes[today_idx]
    window = sym_closes[today_idx - LOOKBACK_HIGH : today_idx]
    if today_close <= max(window):
        return False
    # No breakout in last FRESH_DAYS bars
    for j in range(max(LOOKBACK_HIGH, today_idx - FRESH_DAYS), today_idx):
        past_window = sym_closes[j - LOOKBACK_HIGH : j]
        if past_window and sym_closes[j] > max(past_window):
            return False
    return True


def scan_entries(
    prices: dict[str, dict[date, float]],
    today: date,
    open_syms: set[str],
) -> list[tuple[str, float, float]]:
    """Return (symbol, close_px, hard_stop) for fresh breakouts today."""
    candidates: list[tuple[float, str, float]] = []  # (pct_above_hi, sym, close)
    for sym, pd_data in prices.items():
        if sym in open_syms:
            continue
        if today not in pd_data:
            continue
        sym_dates  = sorted(pd_data.keys())
        sym_closes = [pd_data[d] for d in sym_dates]
        idx = sym_dates.index(today)
        if not _is_fresh_breakout(sym_dates, sym_closes, idx):
            continue
        close_px = sym_closes[idx]
        hi_252   = max(sym_closes[idx - LOOKBACK_HIGH : idx])
        pct_above = (close_px - hi_252) / hi_252
        candidates.append((pct_above, sym, close_px))

    candidates.sort(key=lambda x: x[0])  # tightest breakout first
    return [(sym, close, close * (1 - HARD_STOP_PCT)) for _, sym, close in candidates]


def check_exits(
    open_trades: list[dict],
    prices: dict[str, dict[date, float]],
    today: date,
) -> list[tuple[str, float, str]]:
    """Check each open 52w position for exit. Returns (symbol, exit_px, reason)."""
    exits: list[tuple[str, float, str]] = []
    for trade in open_trades:
        if trade.get("scanner") != SCANNER_NAME:
            continue
        sym       = trade["symbol"]
        entry_px  = float(trade["entry"])
        hard_stop = entry_px * (1 - HARD_STOP_PCT)

        try:
            entry_date = date.fromisoformat(trade["date"])
        except ValueError:
            continue

        pd_data = prices.get(sym, {})
        if not pd_data:
            logger.warning("No price data for open position %s — skipping exit check", sym)
            continue

        sym_dates  = sorted(d for d in pd_data if d >= entry_date)
        sym_closes = [pd_data[d] for d in sym_dates]

        if not sym_closes:
            continue

        latest_close = sym_closes[-1] if sym_dates[-1] == today else pd_data.get(today)
        if latest_close is None:
            logger.warning("No today's price for %s", sym)
            continue

        days_held = sum(1 for d in pd_data if entry_date < d <= today)

        if latest_close <= hard_stop:
            exits.append((sym, hard_stop, "HARD_STOP"))
        elif days_held >= MAX_HOLD_DAYS:
            exits.append((sym, latest_close, "TIME"))
        elif len(sym_closes) >= TRAIL_DAYS:
            trail_low = min(sym_closes[-TRAIL_DAYS:])
            if latest_close < trail_low:
                exits.append((sym, trail_low, "TRAIL_STOP"))

    return exits


# ── Report ────────────────────────────────────────────────────────────────────

def _fmt_report(
    today: date,
    exits_done: list[tuple[str, str, str]],
    entries_done: list[tuple[str, float, float]],
    open_count_after: int,
    skipped: int,
    dry_run: bool,
) -> str:
    lines = [
        f"52-Week Breakout Paper {'(DRY RUN) ' if dry_run else ''}— {today}",
        "-" * 42,
    ]
    if exits_done:
        lines.append(f"Exits ({len(exits_done)}):")
        for sym, result, reason in exits_done:
            lines.append(f"  {sym}  {result}  [{reason}]")
    else:
        lines.append("Exits: none today")

    lines.append("")
    if entries_done:
        lines.append(f"Entries ({len(entries_done)}):")
        for sym, close, hard_stop in entries_done:
            lines.append(f"  {sym}  entry={close:.2f}  SL={hard_stop:.2f}")
    else:
        lines.append("Entries: no fresh breakouts today")

    if skipped:
        lines.append(f"  ({skipped} more breakouts skipped — slots full)")

    lines.append("")
    lines.append(f"Open positions: {open_count_after} / {MAX_CONCURRENT}")
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def run(today: date, dry_run: bool) -> str:
    symbols = _load_symbols()

    start = today - timedelta(days=FETCH_DAYS)
    prices = _fetch_prices(symbols, start.isoformat(), today.isoformat())
    logger.info("Prices loaded: %d symbols with data", len(prices))

    from mcp_server.sheets_sync import (
        close_paper_trade,
        get_open_paper_trades,
        log_paper_trade,
    )

    open_trades = get_open_paper_trades()
    open_52w    = [t for t in open_trades if t.get("scanner") == SCANNER_NAME]
    open_syms   = {t["symbol"] for t in open_52w}

    # ── Exit check ────────────────────────────────────────────────────────────
    exits = check_exits(open_52w, prices, today)
    exits_done: list[tuple[str, str, str]] = []
    for sym, exit_px, reason in exits:
        if dry_run:
            logger.info("DRY-RUN exit: %s @ %.2f [%s]", sym, exit_px, reason)
            exits_done.append((sym, "DRY-RUN", reason))
            open_syms.discard(sym)
        else:
            result_str = close_paper_trade(
                symbol=sym, exit_price=exit_px,
                reason=reason, scanner_filter=SCANNER_NAME,
            )
            exits_done.append((sym, result_str, reason))
            open_syms.discard(sym)
            logger.info("Exit: %s", result_str)

    # ── Entry scan ────────────────────────────────────────────────────────────
    current_open = len(open_syms)
    slots = MAX_CONCURRENT - current_open
    candidates = scan_entries(prices, today, open_syms)
    logger.info("Fresh breakouts today: %d | slots: %d", len(candidates), slots)

    entries_done: list[tuple[str, float, float]] = []
    skipped = max(0, len(candidates) - max(0, slots))

    for sym, close_px, hard_stop in candidates[:max(0, slots)]:
        if dry_run:
            logger.info("DRY-RUN entry: %s @ %.2f SL=%.2f", sym, close_px, hard_stop)
            entries_done.append((sym, close_px, hard_stop))
        else:
            ok = log_paper_trade(
                symbol=sym,
                scanner=SCANNER_NAME,
                entry=close_px,
                sl=hard_stop,
                rrr=2.0,          # nominal; real exit is trailing not fixed target
                max_hold_days=MAX_HOLD_DAYS,
                notes="52w fresh breakout",
            )
            if ok:
                entries_done.append((sym, close_px, hard_stop))
                logger.info("Entry logged: %s @ %.2f SL=%.2f", sym, close_px, hard_stop)

    open_count_after = current_open - len(exits_done) + len(entries_done)
    return _fmt_report(today, exits_done, entries_done, open_count_after, skipped, dry_run)


def main() -> None:
    parser = argparse.ArgumentParser(description="52-week breakout paper trade manager")
    parser.add_argument("--dry-run", action="store_true", help="Print plan, no Sheets writes")
    parser.add_argument("--date", default=None, help="Override today's date (YYYY-MM-DD)")
    args = parser.parse_args()

    today = date.fromisoformat(args.date) if args.date else date.today()
    report = run(today, dry_run=args.dry_run)
    print(report)


if __name__ == "__main__":
    main()
