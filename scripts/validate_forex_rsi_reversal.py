"""
validate_forex_rsi_reversal.py
Walk-forward backtest of the forex_rsi_reversal skill.

Strategy (mirrors live skill exactly):
  RSI(14) on 1H bars:
    r[-2] < 30 and r[-1] >= 30  → LONG  (oversold reversal)
    r[-2] > 70 and r[-1] <= 70  → SHORT (overbought reversal)
  SL: 5-bar low (LONG) or 5-bar high (SHORT)
  Target: RRR 2×

Pairs tested: USDINR, EURUSD, GBPUSD, USDJPY (main pairs with good yfinance data)

Usage:
    python scripts/validate_forex_rsi_reversal.py
    python scripts/validate_forex_rsi_reversal.py --days 365
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PAIRS = {
    "USDINR": "USDINR=X",
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
}

TIER1_WR, TIER1_TRADES, TIER1_SHARPE = 0.50, 20, 0.6
TIER2_WR, TIER2_TRADES, TIER2_SHARPE = 0.40, 10, 0.3


# ── Indicators ────────────────────────────────────────────────────────────────

def _rsi(c: np.ndarray, p: int = 14) -> np.ndarray:
    out = np.full(len(c), np.nan)
    if len(c) < p + 1:
        return out
    for i in range(p, len(c)):
        d = np.diff(c[i - p: i + 1])
        gain = d[d > 0].mean() if (d > 0).any() else 0.0
        loss = -d[d < 0].mean() if (d < 0).any() else 0.0
        out[i] = 100 - 100 / (1 + gain / loss) if loss > 0 else 100.0
    return out


# ── Data ─────────────────────────────────────────────────────────────────────

def _fetch(yf_sym: str, days: int, interval: str = "1h") -> pd.DataFrame | None:
    try:
        import yfinance as yf
        # yfinance limits 1h data to 730 days max
        lookback = min(days + 30, 720)
        df = yf.download(yf_sym, period=f"{lookback}d", interval=interval,
                         progress=False, auto_adjust=True)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df.columns = [c.lower() for c in df.columns]
        return df.dropna(subset=["close", "high", "low"])
    except Exception as e:
        logger.warning("Fetch %s failed: %s", yf_sym, e)
        return None


# ── Simulation ────────────────────────────────────────────────────────────────

def _simulate(df: pd.DataFrame, lookback: int, rrr: float, max_hold: int) -> list[dict]:
    cutoff = date.today() - timedelta(days=lookback)
    c   = df["close"].values.astype(float)
    h   = df["high"].values.astype(float)
    lo  = df["low"].values.astype(float)
    r   = _rsi(c, 14)

    trades = []
    last_signal_i = -10

    for i in range(20, len(df) - max_hold - 1):
        bar_date = df.index[i].date() if hasattr(df.index[i], "date") else df.index[i]
        if bar_date < cutoff:
            continue
        if i - last_signal_i < 5:
            continue  # cooldown: 5 bars

        if np.isnan(r[i]) or np.isnan(r[i - 1]):
            continue

        # Signal detection (mirrors live skill exactly)
        if r[i - 1] < 30 and r[i] >= 30:
            direction = "LONG"
            sl = float(lo[max(0, i - 4): i + 1].min())
        elif r[i - 1] > 70 and r[i] <= 70:
            direction = "SHORT"
            sl = float(h[max(0, i - 4): i + 1].max())
        else:
            continue

        last_signal_i = i
        entry = float(c[i])
        risk  = abs(entry - sl)
        if risk <= 0:
            continue
        target = entry + rrr * risk if direction == "LONG" else entry - rrr * risk

        exit_price, exit_why = None, "max_hold"
        for j in range(i + 1, min(i + 1 + max_hold, len(df))):
            bar_lo = float(lo[j])
            bar_hi = float(h[j])
            if direction == "LONG":
                if bar_lo <= sl:
                    exit_price, exit_why = sl, "sl"
                    break
                if bar_hi >= target:
                    exit_price, exit_why = target, "target"
                    break
            else:
                if bar_hi >= sl:
                    exit_price, exit_why = sl, "sl"
                    break
                if bar_lo <= target:
                    exit_price, exit_why = target, "target"
                    break
        if exit_price is None:
            exit_price = float(c[min(i + max_hold, len(df) - 1)])

        if direction == "LONG":
            ret = (exit_price - entry) / entry * 100
        else:
            ret = (entry - exit_price) / entry * 100

        trades.append({
            "date": bar_date, "direction": direction,
            "rsi_prev": round(float(r[i - 1]), 1),
            "ret": round(ret, 4), "win": ret > 0, "exit_why": exit_why,
        })

    return trades


def _metrics(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "wr": 0, "sharpe": 0, "verdict": "OVERRIDE"}
    rets  = [t["ret"] for t in trades]
    wins  = [r for r in rets if r > 0]
    n, wr = len(rets), len(wins) / len(rets)
    std   = np.std(rets, ddof=1) if n > 1 else 1.0
    # annualise using sqrt(252*6.5) for 1h bars (~252 trading days × 6.5h)
    sharpe = np.mean(rets) / std * (252 * 6.5) ** 0.5 if std > 0 else 0
    exits = {}
    for t in trades:
        exits[t["exit_why"]] = exits.get(t["exit_why"], 0) + 1
    long_n  = sum(1 for t in trades if t["direction"] == "LONG")
    short_n = sum(1 for t in trades if t["direction"] == "SHORT")

    if wr >= TIER1_WR and n >= TIER1_TRADES and sharpe >= TIER1_SHARPE:
        verdict = "TIER_1"
    elif wr >= TIER2_WR and n >= TIER2_TRADES and sharpe >= TIER2_SHARPE:
        verdict = "TIER_2"
    else:
        verdict = "OVERRIDE"
    return {"n": n, "wr": round(wr * 100, 1), "sharpe": round(sharpe, 3),
            "verdict": verdict, "exits": exits, "long": long_n, "short": short_n}


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--rrr",  type=float, nargs="+", default=[1.5, 2.0, 2.5])
    parser.add_argument("--hold", type=int, default=20)
    args = parser.parse_args()

    all_results: dict[str, dict] = {}

    for pair_name, yf_sym in PAIRS.items():
        logger.info("\n══ %s (%s) ══", pair_name, yf_sym)
        df = _fetch(yf_sym, args.days, interval="1h")
        if df is None or len(df) < 50:
            logger.warning("  Insufficient data — skip")
            continue
        logger.info("  %d 1h bars loaded", len(df))

        for rrr in args.rrr:
            trades = _simulate(df, args.days, rrr, args.hold)
            m = _metrics(trades)
            logger.info(
                "  RRR %.1f | n=%3d (L:%d/S:%d) | WR=%-5.1f%% | "
                "Sharpe=%-6.3f | Exit: %s → %s",
                rrr, m["n"], m.get("long", 0), m.get("short", 0),
                m["wr"], m["sharpe"], m.get("exits", {}), m["verdict"],
            )
            all_results[f"{pair_name}_rrr{rrr}"] = m

    # Summary
    logger.info("\n── SUMMARY ──")
    tier1 = [(k, v) for k, v in all_results.items() if v["verdict"] == "TIER_1"]
    tier2 = [(k, v) for k, v in all_results.items() if v["verdict"] == "TIER_2"]
    over  = [(k, v) for k, v in all_results.items() if v["verdict"] == "OVERRIDE"]
    logger.info("TIER_1: %d | TIER_2: %d | OVERRIDE: %d", len(tier1), len(tier2), len(over))
    for k, v in tier1 + tier2:
        logger.info("  ✓ %s: WR=%.1f%% n=%d Sharpe=%.3f", k, v["wr"], v["n"], v["sharpe"])

    if not tier1 and not tier2:
        logger.info("\nVerdict: OVERRIDE — disable forex_rsi_reversal (set enabled=False)")
        logger.info("RSI crossback alone has no edge on 1H FX bars in this period.")
    else:
        best = max(tier1 + tier2, key=lambda x: x[1]["sharpe"])
        logger.info("\nVerdict: %s — validated on %s (Sharpe %.3f)",
                    best[1]["verdict"], best[0], best[1]["sharpe"])


if __name__ == "__main__":
    main()
