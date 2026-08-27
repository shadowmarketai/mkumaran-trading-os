#!/usr/bin/env python3
"""
Backtest the Quad Confluence (4-of-4) strategy across a universe.

Compares four gate variants so the strict-AND rule can be judged against
looser alternatives rather than in isolation:

  4of4_adx   — all four conditions + ADX >= 20   (proposed)
  4of4       — all four conditions, no ADX       (the source framework)
  3of4       — any three of four                 (the "3 of 4 is not a trade" claim)
  2of4       — any two of four                   (weak baseline)

Usage:
    python scripts/validate_quad_confluence.py --days 730 --limit 50
    python scripts/validate_quad_confluence.py --tickers NSE:RELIANCE,NSE:TCS

Accept criteria (all three must hold vs the 3of4 baseline):
  1. Win rate improvement >= +5 percentage points
  2. Trade count >= 30% of the looser variant (else it is a dead system)
  3. Expectancy per trade improves or holds flat
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from mcp_server import quad_confluence as qc

SLIPPAGE_PCT = 0.003   # 0.3% per side, matches backtester default
COST_PCT = 0.0005      # brokerage + taxes approximation, per side


def _net_pnl_pct(gross_pct: float) -> float:
    """Apply round-trip slippage and costs to a gross percentage return."""
    return gross_pct - (SLIPPAGE_PCT + COST_PCT) * 2 * 100


def _run_variant(df: pd.DataFrame, ticker: str, min_conditions: int, use_adx: bool) -> list[dict]:
    """Run one gate variant by temporarily overriding module-level knobs."""
    original_adx = qc.QUAD_ADX_MIN
    qc.QUAD_ADX_MIN = 20.0 if use_adx else 0.0
    try:
        cond = qc.compute_conditions(df)
        if min_conditions < 4:
            cond["entry"] = (cond["conditions_met"] >= min_conditions) & cond["c5_adx"]
        # Re-run the position walk against the adjusted entry column.
        return _walk(cond, ticker)
    finally:
        qc.QUAD_ADX_MIN = original_adx


def _walk(df: pd.DataFrame, ticker: str) -> list[dict]:
    trades: list[dict] = []
    in_pos = False
    entry_price = stop = 0.0
    entry_i = 0
    start = qc.BB_PERIOD + qc.ST_PERIOD

    for i in range(start, len(df) - 1):
        if not in_pos and bool(df["entry"].iloc[i]):
            entry_price = float(df["open"].iloc[i + 1])
            atr_val = float(df["atr"].iloc[i]) or entry_price * 0.01
            stop = entry_price - qc.STOP_ATR_MULT * atr_val
            entry_i = i + 1
            in_pos = True
            continue
        if in_pos:
            if float(df["low"].iloc[i]) <= stop:
                exit_px, reason = stop, "STOP"
            elif int(df["st_dir"].iloc[i]) == -1:
                exit_px, reason = float(df["close"].iloc[i]), "ST_FLIP"
            else:
                continue
            gross = (exit_px - entry_price) / entry_price * 100
            trades.append(
                {
                    "ticker": ticker,
                    "gross_pct": round(gross, 3),
                    "net_pct": round(_net_pnl_pct(gross), 3),
                    "exit_reason": reason,
                    "bars_held": i - entry_i,
                }
            )
            in_pos = False
    return trades


def _summarise(trades: list[dict], label: str) -> dict:
    if not trades:
        return {"variant": label, "trades": 0, "win_rate": 0.0, "expectancy": 0.0}
    nets = [t["net_pct"] for t in trades]
    wins = [n for n in nets if n > 0]
    losses = [n for n in nets if n <= 0]
    total = len(nets)
    wr = len(wins) / total * 100
    expectancy = sum(nets) / total
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "variant": label,
        "trades": total,
        "win_rate": round(wr, 1),
        "expectancy": round(expectancy, 3),
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else 0.0,
        "total_net_pct": round(sum(nets), 1),
        "avg_bars_held": round(sum(t["bars_held"] for t in trades) / total, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=730)
    ap.add_argument("--limit", type=int, default=50, help="max tickers from nifty500")
    ap.add_argument("--tickers", type=str, default="", help="comma-separated override")
    ap.add_argument("--interval", type=str, default="1d")
    ap.add_argument("--out", type=str, default="quad_confluence_results.json")
    args = ap.parse_args()

    from mcp_server.nse_scanner import get_stock_data

    if args.tickers:
        tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    else:
        universe_path = Path(__file__).resolve().parents[1] / "data" / "nifty500.json"
        universe = json.loads(universe_path.read_text(encoding="utf-8"))
        if isinstance(universe, dict):
            universe = universe.get("symbols", universe.get("stocks", []))
        tickers = [
            (s if isinstance(s, str) else s.get("symbol", "")) for s in universe
        ][: args.limit]
        tickers = [t if ":" in t else f"NSE:{t}" for t in tickers if t]

    period = "5y" if args.days > 1095 else "3y" if args.days > 730 else "2y"
    variants = {
        "4of4_adx": (4, True),
        "4of4": (4, False),
        "3of4": (3, False),
        "2of4": (2, False),
    }
    buckets: dict[str, list[dict]] = {k: [] for k in variants}

    ok = failed = 0
    for n, tk in enumerate(tickers, 1):
        try:
            df = get_stock_data(tk, period=period, interval=args.interval)
            if df is None or df.empty or len(df) < 100:
                failed += 1
                continue
            df.columns = [c.lower() for c in df.columns]
            for name, (minc, use_adx) in variants.items():
                buckets[name].extend(_run_variant(df, tk, minc, use_adx))
            ok += 1
        except Exception as e:  # noqa: BLE001 - report and continue the sweep
            failed += 1
            print(f"  [{n}/{len(tickers)}] {tk}: {e}")
        if n % 10 == 0:
            print(f"  ...{n}/{len(tickers)} processed ({ok} ok, {failed} failed)")

    print(f"\nUniverse: {ok} tickers with data, {failed} failed\n")
    rows = [_summarise(buckets[k], k) for k in variants]
    hdr = f"{'variant':<12}{'trades':>8}{'WR%':>8}{'expect':>9}{'PF':>7}{'avgWin':>9}{'avgLoss':>9}{'bars':>7}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(
            f"{r['variant']:<12}{r['trades']:>8}{r['win_rate']:>8}{r['expectancy']:>9}"
            f"{r.get('profit_factor', 0):>7}{r.get('avg_win', 0):>9}{r.get('avg_loss', 0):>9}"
            f"{r.get('avg_bars_held', 0):>7}"
        )

    base = next((r for r in rows if r["variant"] == "3of4"), None)
    strict = next((r for r in rows if r["variant"] == "4of4_adx"), None)
    if base and strict and base["trades"]:
        wr_delta = strict["win_rate"] - base["win_rate"]
        retention = strict["trades"] / base["trades"] * 100
        exp_delta = strict["expectancy"] - base["expectancy"]
        print("\nAccept criteria vs 3of4 baseline:")
        print(f"  1. WR delta        : {wr_delta:+.1f} pp   (need >= +5.0)  "
              f"{'PASS' if wr_delta >= 5 else 'FAIL'}")
        print(f"  2. Trade retention : {retention:.1f}%   (need >= 30%)   "
              f"{'PASS' if retention >= 30 else 'FAIL'}")
        print(f"  3. Expectancy delta: {exp_delta:+.3f}%  (need >= 0)     "
              f"{'PASS' if exp_delta >= 0 else 'FAIL'}")
        print("\nNote: small trade counts are not evidence. Treat anything under")
        print("~100 trades per variant as inconclusive regardless of win rate.")

    Path(args.out).write_text(
        json.dumps({"summary": rows, "trades": buckets}, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
