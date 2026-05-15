"""
validate_commodity_scanners.py
Walk-forward backtest for all commodity scanners in agents/skills/commodity/.

Scanners:
  gold_silver_ratio — mean reversion on GSR extremes (GSR>88 long silver, <76 long gold)
  atr_breakout      — 20d high breakout with ATR stop (LONG only)

Data: yfinance (GC=F gold, SI=F silver, CL=F crude — COMEX/NYMEX USD prices).
Ratio strategy is currency-agnostic. P&L reported in % terms.

Usage:
  python scripts/validate_commodity_scanners.py
  python scripts/validate_commodity_scanners.py --days 180 --rrr 1.5 2.0 2.5
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

# ── Commodity universe ────────────────────────────────────────────────────────
COMMODITIES = {
    "GOLD":       "GC=F",
    "SILVER":     "SI=F",
    "CRUDEOIL":   "CL=F",
    "NATURALGAS": "NG=F",
    "COPPER":     "HG=F",
}

# ── Cost model (MCX futures) ──────────────────────────────────────────────────
BROKERAGE_PCT  = 0.0003
STT_PCT        = 0.0001
SLIPPAGE_PCT   = 0.0005
TOTAL_COST_PCT = BROKERAGE_PCT * 2 + STT_PCT + SLIPPAGE_PCT

POSITION_INR  = 100_000
MAX_HOLD_DAYS = 20

# ── Tier thresholds ───────────────────────────────────────────────────────────
TIER1_WR = 0.50
TIER1_TRADES = 10
TIER1_SHARPE = 0.6
TIER2_WR = 0.40
TIER2_TRADES = 6
TIER2_SHARPE = 0.3

# GSR thresholds (mirrors gold_silver_ratio.py exactly)
GSR_SILVER_LONG = 88
GSR_GOLD_LONG   = 76


# ── Data fetch ────────────────────────────────────────────────────────────────

def _fetch(ticker_yf: str, lookback_days: int) -> pd.DataFrame | None:
    try:
        import yfinance as yf
        period = f"{min(lookback_days + 60, 365)}d"
        df = yf.download(ticker_yf, period=period, interval="1d",
                         progress=False, auto_adjust=True)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df.columns = [c.lower() for c in df.columns]
        return df.dropna(subset=["close", "high", "low", "open"])
    except Exception as exc:
        logger.warning("Fetch failed for %s: %s", ticker_yf, exc)
        return None


# ── ATR helper ────────────────────────────────────────────────────────────────

def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray,
         period: int = 14) -> float:
    n = len(close)
    if n < period + 1:
        return float(high[-1] - low[-1])
    tr = np.maximum(high[1:] - low[1:],
         np.maximum(np.abs(high[1:] - close[:-1]),
                    np.abs(low[1:] - close[:-1])))
    atr_val = float(tr[-period:].mean())
    return atr_val if atr_val > 0 else float(high[-1] - low[-1])


# ── Scanner signal functions ──────────────────────────────────────────────────

def _scan_gsr(gold_df: pd.DataFrame, silver_df: pd.DataFrame,
              i: int) -> dict | None:
    """gold_silver_ratio: mirrors GoldSilverRatioSkill.scan() exactly."""
    g_close = float(gold_df["close"].iloc[i])
    s_close = float(silver_df["close"].iloc[i])
    if s_close <= 0:
        return None
    ratio = g_close / s_close
    if ratio > GSR_SILVER_LONG:
        sl = round(s_close * 0.97, 4)
        return {"ticker": "SILVER", "direction": "LONG",
                "entry": s_close, "sl": sl, "ratio": ratio}
    if ratio < GSR_GOLD_LONG:
        sl = round(g_close * 0.97, 4)
        return {"ticker": "GOLD", "direction": "LONG",
                "entry": g_close, "sl": sl, "ratio": ratio}
    return None


def _scan_atr_breakout(df: pd.DataFrame, i: int) -> dict | None:
    """atr_breakout: mirrors ATRBreakoutSkill.scan() exactly."""
    if i < 21:
        return None
    c   = df["close"].values.astype(float)
    h   = df["high"].values.astype(float)
    low = df["low"].values.astype(float)
    high_20 = float(h[i - 20:i].max())
    if c[i] <= high_20:
        return None
    cur_atr = _atr(h[:i + 1], low[:i + 1], c[:i + 1], 14)
    sl = round(float(c[i]) - 1.5 * cur_atr, 4)
    return {"ticker": "COMMODITY", "direction": "LONG",
            "entry": float(c[i]), "sl": sl}


# ── Trade simulation ──────────────────────────────────────────────────────────

def _simulate(entry_df: pd.DataFrame, signals: list[dict],
              rrr: float) -> list[dict]:
    """Given pre-computed signals, simulate entries/exits on entry_df."""
    trades = []
    c   = entry_df["close"].values.astype(float)
    h   = entry_df["high"].values.astype(float)
    low = entry_df["low"].values.astype(float)
    n   = len(entry_df)

    for sig in signals:
        i          = sig["bar_idx"]
        direction  = sig["direction"]
        sl         = sig["sl"]
        signal_date = sig["date"]

        if i + 1 >= n:
            continue

        # Entry at next-day open
        entry_price = float(entry_df["open"].iloc[i + 1])
        actual_risk = abs(entry_price - sl)
        if actual_risk <= 0:
            continue

        actual_target = (entry_price + rrr * actual_risk if direction == "LONG"
                         else entry_price - rrr * actual_risk)

        exit_price = None
        exit_why   = "max_hold"

        for j in range(i + 2, min(i + 2 + MAX_HOLD_DAYS, n)):
            if direction == "LONG":
                if low[j] <= sl:
                    exit_price = sl
                    exit_why = "sl"
                    break
                if h[j] >= actual_target:
                    exit_price = actual_target
                    exit_why = "target"
                    break
            else:
                if h[j] >= sl:
                    exit_price = sl
                    exit_why = "sl"
                    break
                if low[j] <= actual_target:
                    exit_price = actual_target
                    exit_why = "target"
                    break

        if exit_price is None:
            idx = min(i + 2 + MAX_HOLD_DAYS - 1, n - 1)
            exit_price = float(c[idx])

        ret_pct = ((exit_price - entry_price) / entry_price * 100
                   if direction == "LONG"
                   else (entry_price - exit_price) / entry_price * 100)
        ret_pct -= TOTAL_COST_PCT * 100

        trades.append({
            "scanner":    sig["scanner"],
            "ticker":     sig["ticker"],
            "date":       signal_date,
            "direction":  direction,
            "entry":      entry_price,
            "sl":         sl,
            "target":     actual_target,
            "exit":       exit_price,
            "exit_why":   exit_why,
            "ret_pct":    round(ret_pct, 3),
            "win":        ret_pct > 0,
        })
    return trades


# ── Metrics ───────────────────────────────────────────────────────────────────

def _metrics(trades: list[dict]) -> dict:
    if not trades:
        return {"trades": 0, "wr": 0, "pnl": 0, "sharpe": 0,
                "avg_win": 0, "avg_loss": 0, "verdict": "OVERRIDE"}
    rets  = [t["ret_pct"] for t in trades]
    wins  = [r for r in rets if r > 0]
    loses = [r for r in rets if r <= 0]
    n     = len(rets)
    wr    = len(wins) / n
    pnl   = sum(POSITION_INR * r / 100 for r in rets)
    mean_r = np.mean(rets)
    std_r  = np.std(rets, ddof=1) if n > 1 else 1.0
    sharpe = mean_r / std_r * (252 ** 0.5) if std_r > 0 else 0.0

    exit_why: dict[str, int] = {}
    for t in trades:
        exit_why[t["exit_why"]] = exit_why.get(t["exit_why"], 0) + 1

    if wr >= TIER1_WR and n >= TIER1_TRADES and sharpe >= TIER1_SHARPE:
        verdict = "TIER_1"
    elif wr >= TIER2_WR and n >= TIER2_TRADES and sharpe >= TIER2_SHARPE:
        verdict = "TIER_2"
    else:
        verdict = "OVERRIDE"

    return {
        "trades":   n,
        "wr":       round(wr * 100, 1),
        "pnl":      round(pnl, 0),
        "sharpe":   round(sharpe, 3),
        "avg_win":  round(np.mean(wins), 2) if wins else 0,
        "avg_loss": round(np.mean(loses), 2) if loses else 0,
        "exit_why": exit_why,
        "verdict":  verdict,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days",  type=int,   default=90)
    parser.add_argument("--rrr",   type=float, nargs="+", default=[1.5, 2.0, 2.5])
    args = parser.parse_args()

    cutoff = date.today() - timedelta(days=args.days)

    logger.info("Fetching commodity data...")
    data: dict[str, pd.DataFrame] = {}
    for name, ticker in COMMODITIES.items():
        df = _fetch(ticker, args.days)
        if df is not None and len(df) >= 30:
            data[name] = df
            logger.info("  %-15s %d bars  last=%.4f", name, len(df),
                        float(df["close"].iloc[-1]))
        else:
            logger.warning("  %-15s NO DATA", name)

    # ── 1. Gold/Silver Ratio scanner ──────────────────────────────────────────
    logger.info("\n%s\nGOLD/SILVER RATIO SCANNER\n%s", "=" * 50, "=" * 50)
    gsr_signals: list[dict] = []

    gold_df   = data.get("GOLD")
    silver_df = data.get("SILVER")

    if gold_df is not None and silver_df is not None:
        # Align on common dates
        merged = gold_df[["close", "open", "high", "low"]].join(
            silver_df[["close"]].rename(columns={"close": "silver_close"}),
            how="inner",
        )
        ratio_series = merged["close"] / merged["silver_close"]
        logger.info("GSR today: %.2f  (long gold if <76, long silver if >88)",
                    float(ratio_series.iloc[-1]))
        logger.info("GSR range 90d: min=%.2f  max=%.2f",
                    float(ratio_series.min()), float(ratio_series.max()))

        for i in range(5, len(merged)):
            sig_date = merged.index[i].date() if hasattr(merged.index[i], "date") else merged.index[i]
            if sig_date < cutoff:
                continue
            g_close = float(merged["close"].iloc[i])
            s_close = float(merged["silver_close"].iloc[i])
            ratio   = g_close / s_close
            if ratio > GSR_SILVER_LONG:
                gsr_signals.append({
                    "scanner": "gold_silver_ratio", "ticker": "SILVER",
                    "direction": "LONG", "entry": s_close,
                    "sl": round(s_close * 0.97, 4),
                    "bar_idx": i, "date": sig_date,
                })
            elif ratio < GSR_GOLD_LONG:
                gsr_signals.append({
                    "scanner": "gold_silver_ratio", "ticker": "GOLD",
                    "direction": "LONG", "entry": g_close,
                    "sl": round(g_close * 0.97, 4),
                    "bar_idx": i, "date": sig_date,
                })

        logger.info("GSR signals found: %d", len(gsr_signals))

        gsr_results: dict[str, dict] = {}
        for rrr in args.rrr:
            # Split signals by ticker and simulate on the correct df
            gold_sigs   = [s for s in gsr_signals if s["ticker"] == "GOLD"]
            silver_sigs = [s for s in gsr_signals if s["ticker"] == "SILVER"]
            all_trades  = (_simulate(gold_df, gold_sigs, rrr) +
                           _simulate(silver_df, silver_sigs, rrr))
            m = _metrics(all_trades)
            logger.info(
                "  RRR %.1f | trades=%d WR=%.1f%% Sharpe=%.3f P&L=₹%.0f → %s",
                rrr, m["trades"], m["wr"], m["sharpe"], m["pnl"], m["verdict"],
            )
            if not gsr_results or m["sharpe"] > gsr_results.get("best", {}).get("sharpe", -99):
                gsr_results["best"] = {**m, "rrr": rrr}

        logger.info("  Gold signals:   %d", len([s for s in gsr_signals if s["ticker"] == "GOLD"]))
        logger.info("  Silver signals: %d", len([s for s in gsr_signals if s["ticker"] == "SILVER"]))
    else:
        logger.warning("Gold or Silver data unavailable — skipping GSR scanner")
        gsr_results = {"best": {"verdict": "OVERRIDE", "trades": 0, "wr": 0,
                                "sharpe": 0, "pnl": 0, "rrr": 2.0}}

    # ── 2. ATR Breakout scanner ───────────────────────────────────────────────
    logger.info("\n%s\nATR BREAKOUT SCANNER (all commodities)\n%s", "=" * 50, "=" * 50)
    atr_all_results: dict[str, dict] = {}

    for name, df in data.items():
        atr_signals: list[dict] = []
        for i in range(21, len(df)):
            sig_date = df.index[i].date() if hasattr(df.index[i], "date") else df.index[i]
            if sig_date < cutoff:
                continue
            sig = _scan_atr_breakout(df, i)
            if sig:
                atr_signals.append({**sig, "scanner": "atr_breakout",
                                    "bar_idx": i, "date": sig_date})

        best_m: dict = {}
        best_rrr = args.rrr[0]
        for rrr in args.rrr:
            trades = _simulate(df, atr_signals, rrr)
            m = _metrics(trades)
            if not best_m or (m["verdict"] != "OVERRIDE" and m["sharpe"] > best_m.get("sharpe", -99)):
                best_m = m
                best_rrr = rrr
        if not best_m:
            all_trades_default = _simulate(df, atr_signals, args.rrr[0])
            best_m = _metrics(all_trades_default)
        atr_all_results[name] = {**best_m, "rrr": best_rrr}
        logger.info(
            "  %-12s signals=%2d WR=%.1f%% Sharpe=%.3f P&L=₹%.0f → %s (RRR %.1f)",
            name, len(atr_signals), best_m.get("wr", 0), best_m.get("sharpe", 0),
            best_m.get("pnl", 0), best_m.get("verdict", "OVERRIDE"), best_rrr,
        )

    # ── Final summary ──────────────────────────────────────────────────────────
    logger.info("\n%s\nFINAL VERDICTS\n%s", "=" * 60, "=" * 60)

    gsr_best  = gsr_results.get("best", {})
    gsr_v     = gsr_best.get("verdict", "OVERRIDE")

    # ATR breakout: aggregate across all commodities
    atr_trades_agg: list[dict] = []
    for rrr in [2.0]:
        for name, df in data.items():
            sigs = []
            for i in range(21, len(df)):
                sig_date = df.index[i].date() if hasattr(df.index[i], "date") else df.index[i]
                if sig_date < cutoff:
                    continue
                sig = _scan_atr_breakout(df, i)
                if sig:
                    sigs.append({**sig, "scanner": "atr_breakout",
                                 "bar_idx": i, "date": sig_date})
            atr_trades_agg.extend(_simulate(df, sigs, rrr))
    atr_agg_m = _metrics(atr_trades_agg)
    atr_v     = atr_agg_m.get("verdict", "OVERRIDE")

    logger.info("  %-25s %-10s WR=%.1f%% Sharpe=%.3f trades=%d best_RRR=%.1f",
                "gold_silver_ratio", gsr_v,
                gsr_best.get("wr", 0), gsr_best.get("sharpe", 0),
                gsr_best.get("trades", 0), gsr_best.get("rrr", 2.0))
    logger.info("  %-25s %-10s WR=%.1f%% Sharpe=%.3f trades=%d",
                "atr_breakout (aggregate)", atr_v,
                atr_agg_m.get("wr", 0), atr_agg_m.get("sharpe", 0),
                atr_agg_m.get("trades", 0))

    tier1 = [n for n, v in [("gold_silver_ratio", gsr_v), ("atr_breakout", atr_v)] if v == "TIER_1"]
    tier2 = [n for n, v in [("gold_silver_ratio", gsr_v), ("atr_breakout", atr_v)] if v == "TIER_2"]
    ovrd  = [n for n, v in [("gold_silver_ratio", gsr_v), ("atr_breakout", atr_v)] if v == "OVERRIDE"]

    logger.info("\nTIER_1  (enable):      %s", tier1 or "none")
    logger.info("TIER_2  (paper trade): %s", tier2 or "none")
    logger.info("OVERRIDE (disable):    %s", ovrd or "none")


if __name__ == "__main__":
    main()
