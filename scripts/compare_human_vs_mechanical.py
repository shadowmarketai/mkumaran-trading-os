"""
Human vs Mechanical Signal Comparison

Reads signals from the DB and compares outcomes for:
  - Human-TAKEN signals (human_decision = 'TAKE')
  - Human-SKIPPED signals (human_decision = 'SKIP')
  - No-decision signals (human_decision IS NULL, pre-button or missed)

Uses yfinance for settlement prices (read-only, diagnostic).

Usage:
    python scripts/compare_human_vs_mechanical.py
    python scripts/compare_human_vs_mechanical.py --since 2026-05-12
    python scripts/compare_human_vs_mechanical.py --days 10
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
logger = logging.getLogger("human_vs_mech")

LOOK_FORWARD_DAYS = 5
INDEX_TICKERS = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
    "MIDCPNIFTY": "NIFTY_MIDCAP_SELECT.NS",
}


def _get_signals(session, since: date) -> list[dict]:
    from sqlalchemy import text
    rows = session.execute(text("""
        SELECT id, signal_date, ticker, direction, pattern,
               entry_price, stop_loss, target, status,
               source, human_decision, ai_confidence
        FROM signals
        WHERE signal_date >= :since
          AND source IN ('mwa_scan', 'tradingview', 'options_scan', 'telegram')
        ORDER BY signal_date DESC, id DESC
    """), {"since": since.isoformat()}).fetchall()
    return [dict(r._mapping) for r in rows]


def _fetch_closes(ticker: str, start: date, end: date) -> dict[date, float]:
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


def _determine_outcome(signal: dict, closes: dict[date, float], look_forward: int) -> str:
    sig_date = signal["signal_date"]
    if isinstance(sig_date, str):
        sig_date = date.fromisoformat(sig_date)

    entry = float(signal.get("entry_price") or 0)
    target = float(signal.get("target") or 0)
    sl = float(signal.get("stop_loss") or 0)
    direction = (signal.get("direction") or "NEUTRAL").upper()

    if entry <= 0:
        return "NO_DATA"

    check_end = sig_date + timedelta(days=look_forward)
    for d in sorted(k for k in closes if sig_date < k <= check_end):
        price = closes[d]
        if direction in ("LONG", "BUY"):
            if target > entry and price >= target:
                return "HIT_TARGET"
            if sl < entry and price <= sl:
                return "HIT_STOP"
        elif direction in ("SHORT", "SELL"):
            if target < entry and price <= target:
                return "HIT_TARGET"
            if sl > entry and price >= sl:
                return "HIT_STOP"

    today = date.today()
    if check_end < today:
        return "EXPIRED"
    return "OPEN"


def _summarize(outcomes: list[str]) -> dict:
    n = len(outcomes)
    hits = outcomes.count("HIT_TARGET")
    stops = outcomes.count("HIT_STOP")
    decided = hits + stops
    win_rate = f"{hits / decided * 100:.0f}%" if decided else "n/a"
    return {"n": n, "hits": hits, "stops": stops, "decided": decided, "win_rate": win_rate}


def main() -> None:
    parser = argparse.ArgumentParser(description="Human vs mechanical signal comparison")
    parser.add_argument("--days", type=int, default=LOOK_FORWARD_DAYS)
    parser.add_argument("--since", default=None)
    args = parser.parse_args()

    since = date.fromisoformat(args.since) if args.since else date.today() - timedelta(days=30)

    from mcp_server.db import SessionLocal
    session = SessionLocal()
    try:
        signals = _get_signals(session, since)
    finally:
        session.close()

    if not signals:
        print(f"No signals found since {since}.")
        return

    logger.info("Found %d signals since %s", len(signals), since)

    # Fetch closes per ticker
    ticker_closes: dict[str, dict[date, float]] = {}
    for sig in signals:
        t = sig["ticker"]
        if t not in ticker_closes:
            ticker_closes[t] = _fetch_closes(t, since - timedelta(days=5), date.today())

    # Score outcomes
    results: list[dict] = []
    for sig in signals:
        outcome = _determine_outcome(sig, ticker_closes.get(sig["ticker"], {}), args.days)
        results.append({**sig, "outcome": outcome})

    # Bucket by human_decision
    taken = [r for r in results if r["human_decision"] == "TAKE"]
    skipped = [r for r in results if r["human_decision"] == "SKIP"]
    no_decision = [r for r in results if not r["human_decision"]]

    taken_outcomes = [r["outcome"] for r in taken]
    skipped_outcomes = [r["outcome"] for r in skipped]
    all_outcomes = [r["outcome"] for r in results]

    s_taken = _summarize(taken_outcomes)
    s_skipped = _summarize(skipped_outcomes)
    s_all = _summarize(all_outcomes)

    print()
    print("=" * 70)
    print(f"HUMAN vs MECHANICAL  |  since {since}  |  {args.days}-day window")
    print("=" * 70)
    print(f"{'Bucket':<20} {'N':>4}  {'HIT':>4}  {'STOP':>5}  {'Decided':>8}  {'WinRate':>8}")
    print("-" * 70)
    print(f"{'HUMAN TAKEN':<20} {s_taken['n']:>4}  {s_taken['hits']:>4}  {s_taken['stops']:>5}  {s_taken['decided']:>8}  {s_taken['win_rate']:>8}")
    print(f"{'HUMAN SKIPPED':<20} {s_skipped['n']:>4}  {s_skipped['hits']:>4}  {s_skipped['stops']:>5}  {s_skipped['decided']:>8}  {s_skipped['win_rate']:>8}")
    print(f"{'NO DECISION':<20} {len(no_decision):>4}  {'-':>4}  {'-':>5}  {'-':>8}  {'n/a':>8}")
    print("-" * 70)
    print(f"{'ALL SIGNALS':<20} {s_all['n']:>4}  {s_all['hits']:>4}  {s_all['stops']:>5}  {s_all['decided']:>8}  {s_all['win_rate']:>8}")
    print("=" * 70)

    if s_taken["decided"] > 0 and s_all["decided"] > 0:
        human_wr = s_taken["hits"] / s_taken["decided"]
        all_wr = s_all["hits"] / s_all["decided"]
        edge = (human_wr - all_wr) * 100
        edge_sign = "+" if edge >= 0 else ""
        print(f"\nHuman edge vs mechanical: {edge_sign}{edge:.1f}pp")
        if s_taken["decided"] < 10:
            print("(sample too small — need 10+ decided trades for reliable comparison)")

    # Detail table for TAKE signals
    if taken:
        print(f"\nTAKEN signals detail ({len(taken)}):")
        print(f"{'Date':<12} {'Ticker':<12} {'Dir':<6} {'Conf':>5}  {'Outcome':<12}")
        print("-" * 55)
        for r in taken:
            d = str(r["signal_date"])[:10]
            conf = r.get("ai_confidence") or 0
            print(f"{d:<12} {r['ticker']:<12} {(r['direction'] or ''):<6} {conf:>5}  {r['outcome']:<12}")

    # Save report
    out = Path("reports") / f"human_vs_mech_{date.today()}.md"
    out.parent.mkdir(exist_ok=True)
    lines = [
        f"# Human vs Mechanical — {date.today()}",
        f"Period: {since} → {date.today()} | Look-forward: {args.days} days",
        "",
        "| Bucket | N | HIT | STOP | Decided | WinRate |",
        "|---|---|---|---|---|---|",
        f"| HUMAN TAKEN | {s_taken['n']} | {s_taken['hits']} | {s_taken['stops']} | {s_taken['decided']} | {s_taken['win_rate']} |",
        f"| HUMAN SKIPPED | {s_skipped['n']} | {s_skipped['hits']} | {s_skipped['stops']} | {s_skipped['decided']} | {s_skipped['win_rate']} |",
        f"| NO DECISION | {len(no_decision)} | - | - | - | n/a |",
        f"| ALL SIGNALS | {s_all['n']} | {s_all['hits']} | {s_all['stops']} | {s_all['decided']} | {s_all['win_rate']} |",
    ]
    out.write_text("\n".join(lines, encoding='utf-8'))
    logger.info("Report saved: %s", out)


if __name__ == "__main__":
    main()
