"""
validate_gold_silver_ratio.py
Walk-forward backtest of the gold_silver_ratio skill.

Strategy (mirrors live skill exactly):
  ratio = GOLD_close / SILVER_close
  ratio > 88  → LONG SILVER (silver cheap vs gold, mean-revert up)
  ratio < 76  → LONG GOLD   (gold cheap vs silver, mean-revert up)
  else        → no signal

Data: GC=F (COMEX Gold), SI=F (COMEX Silver) via yfinance.
Note: ratio is globally comparable regardless of currency denomination.

Exit variants tested:
  - hold_5d / hold_10d / hold_15d: fixed-day exit
  - sl3_rr2: 3% SL + 2× RRR target (mirrors live skill's 3% SL)
  - sl5_rr2: 5% SL + 2× RRR target

Usage:
    python scripts/validate_gold_silver_ratio.py
    python scripts/validate_gold_silver_ratio.py --days 730
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

RATIO_HIGH = 88   # ratio > this → long silver
RATIO_LOW  = 76   # ratio < this → long gold

TIER1_WR, TIER1_TRADES, TIER1_SHARPE = 0.50, 15, 0.6
TIER2_WR, TIER2_TRADES, TIER2_SHARPE = 0.40, 8,  0.3

POSITION_USD = 10_000   # notional per trade


# ── Data ─────────────────────────────────────────────────────────────────────

def _fetch(yf_sym: str, days: int) -> pd.DataFrame | None:
    try:
        import yfinance as yf
        lookback = min(days + 90, 1000)
        df = yf.download(yf_sym, period=f"{lookback}d", interval="1d",
                         progress=False, auto_adjust=True)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df.columns = [c.lower() for c in df.columns]
        return df.dropna(subset=["close"])
    except Exception as e:
        logger.warning("Fetch %s failed: %s", yf_sym, e)
        return None


# ── Simulation ────────────────────────────────────────────────────────────────

def _simulate_fixed_hold(
    gold: pd.DataFrame, silver: pd.DataFrame,
    lookback: int, hold_days: int,
) -> list[dict]:
    cutoff = date.today() - timedelta(days=lookback)
    # Align on common dates
    merged = pd.merge(
        gold[["close"]].rename(columns={"close": "gold"}),
        silver[["close"]].rename(columns={"close": "silver"}),
        left_index=True, right_index=True,
    ).dropna()

    trades = []
    last_signal_i = -5

    for i in range(5, len(merged) - hold_days):
        sig_date = merged.index[i].date()
        if sig_date < cutoff:
            continue
        if i - last_signal_i < 3:
            continue  # cooldown

        g = float(merged["gold"].iloc[i])
        s = float(merged["silver"].iloc[i])
        if s <= 0:
            continue
        ratio = g / s

        if ratio > RATIO_HIGH:
            direction, asset = "LONG_SILVER", "silver"
            entry = s
        elif ratio < RATIO_LOW:
            direction, asset = "LONG_GOLD", "gold"
            entry = g
        else:
            continue

        last_signal_i = i
        exit_price = float(merged[asset].iloc[i + hold_days])
        ret_pct = (exit_price - entry) / entry * 100
        win = ret_pct > 0

        trades.append({
            "date": sig_date, "direction": direction,
            "ratio": round(ratio, 1), "ret": round(ret_pct, 3), "win": win,
        })

    return trades


def _simulate_sl_target(
    gold: pd.DataFrame, silver: pd.DataFrame,
    lookback: int, sl_pct: float, rrr: float, max_hold: int = 20,
) -> list[dict]:
    cutoff = date.today() - timedelta(days=lookback)
    merged = pd.merge(
        gold[["close", "high", "low"]].rename(columns={"close": "gold", "high": "gold_h", "low": "gold_l"}),
        silver[["close", "high", "low"]].rename(columns={"close": "silver", "high": "silver_h", "low": "silver_l"}),
        left_index=True, right_index=True,
    ).dropna()

    trades = []
    last_signal_i = -5

    for i in range(5, len(merged) - max_hold - 1):
        sig_date = merged.index[i].date()
        if sig_date < cutoff:
            continue
        if i - last_signal_i < 3:
            continue

        g = float(merged["gold"].iloc[i])
        s = float(merged["silver"].iloc[i])
        if s <= 0:
            continue
        ratio = g / s

        if ratio > RATIO_HIGH:
            direction, asset, hi_col, lo_col = "LONG_SILVER", "silver", "silver_h", "silver_l"
            entry = s
        elif ratio < RATIO_LOW:
            direction, asset, hi_col, lo_col = "LONG_GOLD", "gold", "gold_h", "gold_l"
            entry = g
        else:
            continue

        last_signal_i = i
        sl     = entry * (1 - sl_pct / 100)
        target = entry * (1 + sl_pct / 100 * rrr)

        exit_price, exit_why = None, "max_hold"
        for j in range(i + 1, min(i + 1 + max_hold, len(merged))):
            lo = float(merged[lo_col].iloc[j])
            hi = float(merged[hi_col].iloc[j])
            if lo <= sl:
                exit_price, exit_why = sl, "sl"
                break
            if hi >= target:
                exit_price, exit_why = target, "target"
                break
        if exit_price is None:
            exit_price = float(merged[asset].iloc[min(i + max_hold, len(merged) - 1)])

        ret = (exit_price - entry) / entry * 100
        trades.append({
            "date": sig_date, "direction": direction,
            "ratio": round(ratio, 1), "ret": round(ret, 3), "win": ret > 0,
            "exit_why": exit_why,
        })

    return trades


def _metrics(trades: list[dict], label: str) -> dict:
    if not trades:
        return {"n": 0, "wr": 0, "sharpe": 0, "pnl_usd": 0, "verdict": "OVERRIDE"}
    rets  = [t["ret"] for t in trades]
    wins  = [r for r in rets if r > 0]
    n, wr = len(rets), len(wins) / len(rets)
    pnl   = sum(POSITION_USD * r / 100 for r in rets)
    std   = np.std(rets, ddof=1) if n > 1 else 1.0
    sharpe = np.mean(rets) / std * (252 ** 0.5) if std > 0 else 0

    long_gold   = [t for t in trades if "GOLD"   in t["direction"]]
    long_silver = [t for t in trades if "SILVER" in t["direction"]]

    if wr >= TIER1_WR and n >= TIER1_TRADES and sharpe >= TIER1_SHARPE:
        verdict = "TIER_1"
    elif wr >= TIER2_WR and n >= TIER2_TRADES and sharpe >= TIER2_SHARPE:
        verdict = "TIER_2"
    else:
        verdict = "OVERRIDE"

    logger.info(
        "  %-18s | n=%3d (G:%d/S:%d) | WR=%-5.1f%% | Sharpe=%-6.3f | "
        "P&L=$%+.0f → %s",
        label, n, len(long_gold), len(long_silver),
        wr * 100, sharpe, pnl, verdict,
    )
    return {"n": n, "wr": round(wr * 100, 1), "sharpe": round(sharpe, 3),
            "pnl_usd": round(pnl, 0), "verdict": verdict}


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=730)
    args = parser.parse_args()

    logger.info("Fetching Gold (GC=F) and Silver (SI=F) — %dd lookback...", args.days)
    gold   = _fetch("GC=F", args.days)
    silver = _fetch("SI=F", args.days)

    if gold is None or silver is None:
        logger.error("Data fetch failed — aborting")
        return

    logger.info("Gold: %d bars | Silver: %d bars", len(gold), len(silver))

    # Show ratio statistics over period
    merged_check = pd.merge(
        gold[["close"]].rename(columns={"close": "gold"}),
        silver[["close"]].rename(columns={"close": "silver"}),
        left_index=True, right_index=True,
    ).dropna()
    merged_check["ratio"] = merged_check["gold"] / merged_check["silver"]
    cutoff = date.today() - timedelta(days=args.days)
    recent = merged_check[merged_check.index.date >= cutoff] if len(merged_check) > 0 else merged_check
    if len(recent) > 0:
        logger.info("Ratio stats (%dd): min=%.1f max=%.1f mean=%.1f current=%.1f",
                    args.days, recent["ratio"].min(), recent["ratio"].max(),
                    recent["ratio"].mean(), float(recent["ratio"].iloc[-1]))
        above_88 = (recent["ratio"] > RATIO_HIGH).sum()
        below_76 = (recent["ratio"] < RATIO_LOW).sum()
        logger.info("Days ratio>88 (long silver): %d | Days ratio<76 (long gold): %d",
                    above_88, below_76)

    logger.info("\n── FIXED HOLD EXITS ──")
    results = {}
    for hold in (5, 10, 15):
        trades = _simulate_fixed_hold(gold, silver, args.days, hold)
        m = _metrics(trades, f"hold_{hold}d")
        results[f"hold_{hold}d"] = m

    logger.info("\n── SL + TARGET EXITS ──")
    for sl_pct, rrr in ((3.0, 2.0), (5.0, 2.0), (3.0, 3.0)):
        label = f"sl{sl_pct:.0f}_rrr{rrr:.0f}"
        trades = _simulate_sl_target(gold, silver, args.days, sl_pct, rrr)
        exits = {}
        for t in trades:
            exits[t.get("exit_why", "?")] = exits.get(t.get("exit_why", "?"), 0) + 1
        m = _metrics(trades, label)
        if trades:
            logger.info("    Exit dist: %s", exits)
        results[label] = m

    # Summary
    logger.info("\n── SUMMARY ──")
    tier1 = [(k, v) for k, v in results.items() if v["verdict"] == "TIER_1"]
    tier2 = [(k, v) for k, v in results.items() if v["verdict"] == "TIER_2"]
    logger.info("TIER_1: %d | TIER_2: %d | OVERRIDE: %d",
                len(tier1), len(tier2),
                len([v for v in results.values() if v["verdict"] == "OVERRIDE"]))
    for k, v in tier1 + tier2:
        logger.info("  ✓ %s: WR=%.1f%% n=%d Sharpe=%.3f", k, v["wr"], v["n"], v["sharpe"])

    best = max(results.values(), key=lambda x: x["sharpe"])
    if best["verdict"] == "OVERRIDE":
        logger.info("\nVerdict: OVERRIDE — disable skill (set enabled=False)")
        logger.info("The ratio thresholds (>88 / <76) have no standalone edge.")
        logger.info("Consider: adjust thresholds, add RSI/trend filter, or remove.")
    else:
        logger.info("\nVerdict: %s — skill validated, remove 'backtest pending' disclaimer",
                    best["verdict"])


if __name__ == "__main__":
    main()
