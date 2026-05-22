"""
validate_options_premium_sell.py
Proxy backtest for 3 premium-selling options skills using Nifty + India VIX.

Skills tested:
  expiry_theta_sell  — sell ATM straddle every Thursday (Nifty weekly expiry)
  vix_premium_sell   — sell straddle when VIX >= 20 and DTE <= 2
  iv_crush_strangle  — sell strangle when VIX >= 40 (proxy for ATM IV >= 40)

Methodology (proxy — no historical option chain data used):
  ATM straddle estimate = 0.8 × spot × (VIX/100) × sqrt(DTE/252)
    (standard Black-Scholes approximation for ATM straddle price)

  Win:  abs(Nifty_move_by_expiry) <= straddle_estimate  (premium decays to zero)
  Loss: abs(Nifty_move_by_expiry) >  straddle_estimate  (underlying exceeds breakeven)
  SL:   abs(intraday_move) > 1.30 × straddle_estimate   (30% above premium = cut)

  Simulated P&L: sell straddle for 'straddle_est', buy back at intrinsic value
  Win P&L ≈ +straddle_est (full premium kept if expires in range)
  Loss P&L ≈ -0.30 × straddle_est (SL hit at 130% of entry)

Limitation: Actual straddle prices differ from the Black-Scholes estimate
due to skew, liquidity, and supply/demand. Results are directionally correct
but not precise. Validate with 2-3 months of live outcomes in Sheets.

Data: ^NSEI (Nifty) + ^INDIAVIX daily bars via yfinance
"""
from __future__ import annotations

import logging
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

TIER1_WR, TIER1_TRADES, TIER1_SHARPE = 0.55, 20, 0.6
TIER2_WR, TIER2_TRADES, TIER2_SHARPE = 0.45, 10, 0.3


def _fetch(sym: str, days: int = 730) -> pd.DataFrame | None:
    try:
        import yfinance as yf
        df = yf.download(sym, period=f"{days}d", interval="1d",
                         progress=False, auto_adjust=True)
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
        df.columns = [c.lower() for c in df.columns]
        return df.dropna(subset=["close"])
    except Exception as e:
        logger.warning("Fetch %s: %s", sym, e)
        return None


def _straddle_estimate(spot: float, vix_pct: float, dte: float) -> float:
    """ATM straddle ≈ 0.8 × S × σ × √T (Black-Scholes approximation)."""
    if dte <= 0 or vix_pct <= 0:
        return 0.0
    return 0.8 * spot * (vix_pct / 100) * math.sqrt(dte / 252)


def _simulate_straddle_sell(
    nifty: pd.DataFrame,
    vix: pd.DataFrame,
    signal_filter_fn,          # returns (dte, True/False) for a given row
    sl_multiple: float = 1.30,
    days: int = 730,
) -> list[dict]:
    """
    Generic straddle-sell simulation.
    signal_filter_fn(date, vix_val, dte) → True if signal fires, False otherwise.
    """
    cutoff = date.today() - timedelta(days=days)

    # Merge Nifty and VIX on date
    merged = pd.merge(
        nifty[["close"]].rename(columns={"close": "nifty"}),
        vix[["close"]].rename(columns={"close": "vix"}),
        left_index=True, right_index=True,
        how="inner",
    ).dropna()
    merged.index = pd.to_datetime(merged.index)

    # Identify weekly expiry Thursdays (NSE Nifty weekly = Thursday)
    def next_thursday(d: date) -> date:
        days_ahead = 3 - d.weekday()  # Thursday = 3
        if days_ahead <= 0:
            days_ahead += 7
        return d + timedelta(days=days_ahead)

    trades = []
    used_dates: set = set()

    for i in range(2, len(merged) - 1):
        row_date = merged.index[i].date()
        if row_date < cutoff or row_date in used_dates:
            continue

        spot    = float(merged["nifty"].iloc[i])
        vix_val = float(merged["vix"].iloc[i])

        # DTE = days to next Thursday expiry
        exp_date = next_thursday(row_date)
        dte = (exp_date - row_date).days

        if not signal_filter_fn(row_date, vix_val, dte):
            continue

        used_dates.add(row_date)
        straddle = _straddle_estimate(spot, vix_val, dte)
        if straddle <= 0:
            continue

        breakeven_pct = straddle / spot * 100
        sl_pct = sl_multiple * straddle / spot * 100

        # Find expiry bar or SL hit — check each day until expiry
        exit_pnl_pct = None
        exit_why = "expiry"
        for j in range(i + 1, min(i + dte + 2, len(merged))):
            j_date  = merged.index[j].date()
            j_close = float(merged["nifty"].iloc[j])
            move_pct = abs(j_close - spot) / spot * 100
            if move_pct > sl_pct:
                exit_pnl_pct = -(sl_multiple - 1) * breakeven_pct
                exit_why = "sl"
                break
            if j_date >= exp_date:
                # Expiry: settle at intrinsic
                if move_pct <= breakeven_pct:
                    exit_pnl_pct = breakeven_pct   # full premium kept
                else:
                    exit_pnl_pct = breakeven_pct - move_pct  # partial loss
                exit_why = "expiry"
                break
        if exit_pnl_pct is None:
            # Reached end of data before expiry
            last_close = float(merged["nifty"].iloc[min(i+dte, len(merged)-1)])
            move_pct = abs(last_close - spot) / spot * 100
            exit_pnl_pct = breakeven_pct - move_pct
            exit_why = "expiry"

        trades.append({
            "date": row_date, "dte": dte, "vix": round(vix_val, 1),
            "straddle_est": round(straddle, 1),
            "breakeven_pct": round(breakeven_pct, 2),
            "ret": round(exit_pnl_pct, 3),
            "win": exit_pnl_pct > 0,
            "exit_why": exit_why,
        })

    return trades


def _metrics(trades: list[dict], label: str) -> dict:
    if not trades:
        logger.info("  %-30s | n=  0 → OVERRIDE", label)
        return {"n": 0, "wr": 0, "sharpe": 0, "verdict": "OVERRIDE", "exits": {}}
    rets  = [t["ret"] for t in trades]
    wins  = [r for r in rets if r > 0]
    n, wr = len(rets), len(wins) / len(rets)
    std   = np.std(rets, ddof=1) if n > 1 else 1.0
    sharpe = np.mean(rets) / std * (252 ** 0.5) if std > 0 else 0
    exits  = {}
    for t in trades: exits[t["exit_why"]] = exits.get(t["exit_why"], 0) + 1
    avg_vix = np.mean([t["vix"] for t in trades])
    avg_dte = np.mean([t["dte"] for t in trades])

    if wr >= TIER1_WR and n >= TIER1_TRADES and sharpe >= TIER1_SHARPE:
        verdict = "TIER_1"
    elif wr >= TIER2_WR and n >= TIER2_TRADES and sharpe >= TIER2_SHARPE:
        verdict = "TIER_2"
    else:
        verdict = "OVERRIDE"

    logger.info("  %-30s | n=%3d | WR=%-5.1f%% | Sharpe=%-6.3f | "
                "avgVIX=%.1f avgDTE=%.1f | Exit:%s → %s",
                label, n, wr*100, sharpe, avg_vix, avg_dte, exits, verdict)
    return {"n": n, "wr": round(wr*100,1), "sharpe": round(sharpe,3),
            "verdict": verdict, "exits": exits}


def main():
    logger.info("Fetching Nifty + India VIX (730d)...")
    nifty = _fetch("^NSEI", 730)
    vix   = _fetch("^INDIAVIX", 730)
    if nifty is None or vix is None:
        logger.error("Data fetch failed"); return
    logger.info("Nifty: %d bars | VIX: %d bars", len(nifty), len(vix))

    vix_merged = pd.merge(
        nifty[["close"]].rename(columns={"close": "nifty"}),
        vix[["close"]].rename(columns={"close": "vix"}),
        left_index=True, right_index=True, how="inner",
    ).dropna()
    vix_avg = float(vix_merged["vix"].mean())
    vix_pct_above20 = (vix_merged["vix"] >= 20).mean() * 100
    logger.info("VIX stats: avg=%.1f | days>=20: %.0f%%", vix_avg, vix_pct_above20)

    all_results = {}

    # ── 1. expiry_theta_sell ──────────────────────────────────────────────────
    logger.info("\n══ EXPIRY THETA SELL (every Thursday) ══")
    def expiry_filter(d, vix_val, dte):
        return d.weekday() == 3  # Thursday
    trades = _simulate_straddle_sell(nifty, vix, expiry_filter, sl_multiple=1.30)
    m = _metrics(trades, "expiry_theta_sell (all Thu)")
    all_results["expiry_theta_sell"] = m

    # Variant: only Thursdays where VIX < 20 (low vol = better for theta sell)
    def expiry_low_vix_filter(d, vix_val, dte):
        return d.weekday() == 3 and vix_val < 20
    trades2 = _simulate_straddle_sell(nifty, vix, expiry_low_vix_filter, sl_multiple=1.30)
    m2 = _metrics(trades2, "expiry_theta_sell (Thu, VIX<20)")
    all_results["expiry_theta_low_vix"] = m2

    # ── 2. vix_premium_sell ──────────────────────────────────────────────────
    logger.info("\n══ VIX PREMIUM SELL (VIX >= 20, DTE <= 2) ══")
    def vix_filter(d, vix_val, dte):
        return vix_val >= 20 and dte <= 2
    trades3 = _simulate_straddle_sell(nifty, vix, vix_filter, sl_multiple=1.35)
    m3 = _metrics(trades3, "vix_premium_sell (VIX>=20, DTE<=2)")
    all_results["vix_premium_sell"] = m3

    # Variant: VIX >= 18 (slightly lower threshold)
    def vix18_filter(d, vix_val, dte):
        return vix_val >= 18 and dte <= 2
    trades4 = _simulate_straddle_sell(nifty, vix, vix18_filter, sl_multiple=1.35)
    m4 = _metrics(trades4, "vix_premium_sell (VIX>=18, DTE<=2)")
    all_results["vix_premium_sell_18"] = m4

    # ── 3. iv_crush_strangle (proxy: VIX >= 40 as IV proxy) ─────────────────
    logger.info("\n══ IV CRUSH STRANGLE (VIX >= 40 proxy for IV>=40) ══")
    def iv_crush_filter(d, vix_val, dte):
        return vix_val >= 40 and dte >= 2

    trades5 = _simulate_straddle_sell(nifty, vix, iv_crush_filter, sl_multiple=1.35)
    if trades5:
        m5 = _metrics(trades5, "iv_crush_strangle (VIX>=40, DTE>=2)")
    else:
        logger.info("  iv_crush_strangle: VIX never reached 40 in test period")
        logger.info("  Checking VIX >= 25 as lower bound proxy...")
        def iv25_filter(d, vix_val, dte):
            return vix_val >= 25 and dte >= 2
        trades5 = _simulate_straddle_sell(nifty, vix, iv25_filter, sl_multiple=1.35)
        m5 = _metrics(trades5, "iv_crush_strangle (VIX>=25, DTE>=2)")
    all_results["iv_crush_strangle"] = m5

    # ── Summary ───────────────────────────────────────────────────────────────
    logger.info("\n── SUMMARY ──")
    tier1 = [(k,v) for k,v in all_results.items() if v["verdict"]=="TIER_1"]
    tier2 = [(k,v) for k,v in all_results.items() if v["verdict"]=="TIER_2"]
    over  = [(k,v) for k,v in all_results.items() if v["verdict"]=="OVERRIDE"]
    logger.info("TIER_1: %d | TIER_2: %d | OVERRIDE: %d",
                len(tier1), len(tier2), len(over))
    for k,v in tier1+tier2:
        logger.info("  ✓ %s: WR=%.1f%% n=%d Sharpe=%.3f", k, v["wr"], v["n"], v["sharpe"])

    logger.info("\n── NOT TESTABLE (no free historical OI/PCR data) ──")
    logger.info("  weekly_directional:  needs historical Nifty PCR time-series")
    logger.info("  max_pain_magnet:     needs historical OI-weighted max pain")
    logger.info("  pcr_iv_directional:  needs historical stock-level PCR + IV")
    logger.info("  → Keep disclaimer. Validate via live outcomes after 60 signals.")


if __name__ == "__main__":
    main()
