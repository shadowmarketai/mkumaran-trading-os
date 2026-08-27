#!/usr/bin/env python3
"""
Measure the impact of the true-range ATR fix on real data.

WHY THIS EXISTS
---------------
`indicators.atr()` previously returned mean(H-L), omitting the gap terms of
true range. Four active skills size stops as `close - 1.5 * atr`, so every
one of those stops was too tight by whatever the understatement is.

The size of the understatement is an EMPIRICAL question — it depends on how
large gaps are relative to intraday range for each instrument. Synthetic
tests put it anywhere from 6% to 30%. This script measures it on the actual
instruments those skills trade, then simulates whether the wider stop would
have survived more trades.

Usage:
    python scripts/validate_atr_fix.py
    python scripts/validate_atr_fix.py --symbols NSE:RELIANCE,MCX:GOLD --days 365
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

# Instruments the four affected skills actually trade.
DEFAULT_SYMBOLS = [
    "MCX:GOLD", "MCX:SILVER", "MCX:CRUDEOIL", "MCX:NATURALGAS",  # atr_breakout
    "NSE:RELIANCE", "NSE:TCS", "NSE:HDFCBANK", "NSE:INFY",        # futures skills
]
AFFECTED_SKILLS = [
    "commodity/atr_breakout.py       (TIER_1 Gold/Silver/Crude/NG)",
    "commodity/mcx_intraday_breakout.py",
    "futures/ema_cross_adx.py",
    "futures/volume_breakout.py",
    "equity_intraday/supertrend_flip.py  (enabled=False)",
]


def _old_atr(h: np.ndarray, lo: np.ndarray, period: int = 14) -> float:
    """The buggy implementation: mean(H-L), no gap terms."""
    return float(np.mean(h[-period:] - lo[-period:]))


def _new_atr(h: np.ndarray, lo: np.ndarray, c: np.ndarray, period: int = 14) -> float:
    """True-range ATR."""
    prev = c[:-1]
    tr = np.maximum(
        h[1:] - lo[1:],
        np.maximum(np.abs(h[1:] - prev), np.abs(lo[1:] - prev)),
    )
    w = tr[-period:] if len(tr) >= period else tr
    return float(np.mean(w))


def _stop_survival(df, atr_val: float, mult: float = 1.5, horizon: int = 10) -> float:
    """Fraction of long entries that would NOT be stopped out within `horizon`.

    Entries are taken at every bar (a neutral sample, not a strategy), so this
    isolates the stop width from any entry edge.
    """
    close = df["close"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    n = len(close)
    survived = total = 0
    for i in range(20, n - horizon):
        stop = close[i] - mult * atr_val
        total += 1
        if low[i + 1 : i + 1 + horizon].min() > stop:
            survived += 1
    return survived / total * 100 if total else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--horizon", type=int, default=10, help="bars to survive")
    args = ap.parse_args()

    from mcp_server.nse_scanner import get_stock_data

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    period = "2y" if args.days > 365 else "1y"

    print("Skills whose stops depend on indicators.atr():")
    for s in AFFECTED_SKILLS:
        print(f"  - {s}")
    print()

    hdr = (f"{'symbol':<16}{'old ATR':>10}{'new ATR':>10}{'under%':>9}"
           f"{'oldSL%':>9}{'newSL%':>9}{'surv_old':>10}{'surv_new':>10}")
    print(hdr)
    print("-" * len(hdr))

    unders, deltas = [], []
    for sym in symbols:
        try:
            df = get_stock_data(sym, period=period, interval="1d")
        except Exception as e:  # noqa: BLE001 - report and continue the sweep
            print(f"{sym:<16} fetch failed: {type(e).__name__}")
            continue
        if df is None or df.empty or len(df) < 60:
            print(f"{sym:<16} insufficient data")
            continue

        df.columns = [c.lower() for c in df.columns]
        h = df["high"].to_numpy(dtype=float)
        lo = df["low"].to_numpy(dtype=float)
        c = df["close"].to_numpy(dtype=float)

        old = _old_atr(h, lo)
        new = _new_atr(h, lo, c)
        if new <= 0:
            continue
        under = (1 - old / new) * 100
        last = c[-1]
        old_sl_pct = 1.5 * old / last * 100
        new_sl_pct = 1.5 * new / last * 100
        s_old = _stop_survival(df, old, horizon=args.horizon)
        s_new = _stop_survival(df, new, horizon=args.horizon)

        unders.append(under)
        deltas.append(s_new - s_old)
        print(f"{sym:<16}{old:>10.2f}{new:>10.2f}{under:>8.1f}%"
              f"{old_sl_pct:>8.2f}%{new_sl_pct:>8.2f}%{s_old:>9.1f}%{s_new:>9.1f}%")

    if unders:
        print("\n" + "-" * 60)
        print(f"Mean ATR understatement : {np.mean(unders):.1f}% "
              f"(range {min(unders):.1f}%-{max(unders):.1f}%)")
        print(f"Mean stop-survival gain : {np.mean(deltas):+.1f} pp "
              f"over {args.horizon} bars")
        print()
        print("Interpretation:")
        print("  'under%' is how much the old ATR understated true volatility.")
        print("  'surv_*' is the share of arbitrary long entries NOT stopped out")
        print("  within the horizon — higher means fewer premature stop-outs.")
        print()
        print("  A survival gain does NOT by itself mean better P&L: wider stops")
        print("  also mean bigger losses when they do hit, and smaller position")
        print("  sizes if you size by risk. Re-run each skill's own backtest")
        print("  before trusting the tier labels in its file header.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
