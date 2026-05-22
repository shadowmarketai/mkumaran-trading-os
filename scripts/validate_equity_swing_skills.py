"""
validate_equity_swing_skills.py
Backtest three equity swing skills on Nifty 100 universe (daily bars).

Skills:
  breakout_200dma:   close crosses above 200-day SMA
  swing_low_bounce:  close within 1.5% of 20d low + green candle
  volume_spike:      volume > 2x 10d avg + green candle

Exit: SL from skill logic, target at RRR 1.5 / 2.0 / 2.5, max_hold=15d
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

SYMBOLS = [
    "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "BHARTIARTL",
    "SBIN", "KOTAKBANK", "LT", "AXISBANK", "WIPRO", "HCLTECH",
    "MARUTI", "SUNPHARMA", "TITAN", "BAJFINANCE", "ULTRACEMCO",
    "NTPC", "POWERGRID", "ONGC", "BPCL", "COALINDIA", "GRASIM",
    "JSWSTEEL", "TATASTEEL", "TATAMOTORS", "NESTLEIND", "ADANIENT",
    "APOLLOHOSP", "ASIANPAINT", "BRITANNIA", "CIPLA", "DRREDDY",
    "EICHERMOT", "HEROMOTOCO", "HINDUNILVR", "ITC", "TECHM", "TRENT",
    "ZOMATO", "BEL", "HAVELLS", "SIEMENS", "PERSISTENT", "MPHASIS",
]

POSITION_INR = 100_000
BROKERAGE    = 0.0008   # round-trip cost

TIER1_WR, TIER1_TRADES, TIER1_SHARPE = 0.50, 15, 0.6
TIER2_WR, TIER2_TRADES, TIER2_SHARPE = 0.40, 8,  0.3


def _fetch(sym: str, days: int) -> pd.DataFrame | None:
    try:
        import yfinance as yf
        df = yf.download(f"{sym}.NS", period=f"{min(days+90,730)}d",
                         interval="1d", progress=False, auto_adjust=True)
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
        df.columns = [c.lower() for c in df.columns]
        return df.dropna(subset=["close","high","low","open","volume"])
    except Exception: return None


def _scan_200dma(df: pd.DataFrame, i: int) -> dict | None:
    if i < 201: return None
    c   = df["close"].values.astype(float)
    low = df["low"].values.astype(float)
    sma = c[i-200:i].mean()
    sma_prev = c[i-201:i-1].mean()
    if c[i] > sma and c[i-1] <= sma_prev:
        sl = low[max(0,i-4):i+1].min()
        return {"entry": c[i], "sl": sl}
    return None


def _scan_swing_low(df: pd.DataFrame, i: int) -> dict | None:
    if i < 21: return None
    c   = df["close"].values.astype(float)
    o   = df["open"].values.astype(float)
    low = df["low"].values.astype(float)
    low_20 = low[i-21:i].min()
    if low[i] <= low_20 * 1.015 and c[i] > o[i]:
        sl = low_20 * 0.99
        return {"entry": c[i], "sl": sl}
    return None


def _scan_volume_spike(df: pd.DataFrame, i: int) -> dict | None:
    if i < 12: return None
    c   = df["close"].values.astype(float)
    o   = df["open"].values.astype(float)
    low = df["low"].values.astype(float)
    v   = df["volume"].values.astype(float)
    avg_vol = v[i-11:i].mean()
    if avg_vol <= 0 or v[i] < 2 * avg_vol: return None
    if c[i] <= o[i]: return None
    sl = low[max(0,i-2):i+1].min()
    return {"entry": c[i], "sl": sl}


def _simulate(df: pd.DataFrame, scanner, lookback: int, rrr: float,
              max_hold: int = 15) -> list[dict]:
    cutoff = date.today() - timedelta(days=lookback)
    c   = df["close"].values.astype(float)
    h   = df["high"].values.astype(float)
    low = df["low"].values.astype(float)
    trades = []
    last_i = -4

    for i in range(201, len(df) - max_hold - 1):
        if df.index[i].date() < cutoff: continue
        if i - last_i < 3: continue
        sig = scanner(df, i)
        if not sig: continue
        last_i = i
        entry, sl = sig["entry"], sig["sl"]
        risk = abs(entry - sl)
        if risk <= 0: continue
        target = entry + rrr * risk

        exit_price, exit_why = None, "max_hold"
        for j in range(i+1, min(i+1+max_hold, len(df))):
            if low[j] <= sl:
                exit_price, exit_why = sl, "sl"; break
            if h[j] >= target:
                exit_price, exit_why = target, "target"; break
        if exit_price is None:
            exit_price = c[min(i+max_hold, len(df)-1)]

        ret = (exit_price - entry)/entry*100 - BROKERAGE*100
        trades.append({"date": df.index[i].date(), "ret": round(ret,3),
                       "win": ret > 0, "exit_why": exit_why})
    return trades


def _metrics(trades: list[dict]) -> dict:
    if not trades:
        return {"n":0,"wr":0,"sharpe":0,"pnl":0,"verdict":"OVERRIDE","exits":{}}
    rets  = [t["ret"] for t in trades]
    wins  = [r for r in rets if r > 0]
    n, wr = len(rets), len(wins)/len(rets)
    pnl   = sum(POSITION_INR*r/100 for r in rets)
    std   = np.std(rets, ddof=1) if n > 1 else 1.0
    sharpe = np.mean(rets)/std*(252**0.5) if std > 0 else 0
    exits = {}
    for t in trades: exits[t["exit_why"]] = exits.get(t["exit_why"],0)+1
    if wr>=TIER1_WR and n>=TIER1_TRADES and sharpe>=TIER1_SHARPE: verdict="TIER_1"
    elif wr>=TIER2_WR and n>=TIER2_TRADES and sharpe>=TIER2_SHARPE: verdict="TIER_2"
    else: verdict="OVERRIDE"
    return {"n":n,"wr":round(wr*100,1),"sharpe":round(sharpe,3),
            "pnl":round(pnl,0),"verdict":verdict,"exits":exits}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=730)
    parser.add_argument("--rrr",  type=float, nargs="+", default=[1.5, 2.0, 2.5])
    args = parser.parse_args()

    logger.info("Fetching %d symbols (%dd lookback)...", len(SYMBOLS), args.days)
    data = {}
    for sym in SYMBOLS:
        df = _fetch(sym, args.days)
        if df is not None and len(df) >= 210:
            data[sym] = df
    logger.info("Loaded %d symbols", len(data))

    scanners = {
        "breakout_200dma":  _scan_200dma,
        "swing_low_bounce": _scan_swing_low,
        "volume_spike":     _scan_volume_spike,
    }

    all_results = {}
    for skill_name, scanner_fn in scanners.items():
        logger.info("\n══ %s ══", skill_name.upper())
        for rrr in args.rrr:
            all_trades = []
            for df in data.values():
                all_trades.extend(_simulate(df, scanner_fn, args.days, rrr))
            m = _metrics(all_trades)
            key = f"{skill_name}_rrr{rrr}"
            all_results[key] = m
            logger.info("  RRR %.1f | n=%4d | WR=%-5.1f%% | Sharpe=%-6.3f | "
                        "P&L=₹%+.0f | Exit:%s → %s",
                        rrr, m["n"], m["wr"], m["sharpe"], m["pnl"],
                        m["exits"], m["verdict"])

    logger.info("\n── SUMMARY ──")
    tier1 = [(k,v) for k,v in all_results.items() if v["verdict"]=="TIER_1"]
    tier2 = [(k,v) for k,v in all_results.items() if v["verdict"]=="TIER_2"]
    over  = [(k,v) for k,v in all_results.items() if v["verdict"]=="OVERRIDE"]
    logger.info("TIER_1: %d | TIER_2: %d | OVERRIDE: %d", len(tier1), len(tier2), len(over))
    for k,v in tier1+tier2:
        logger.info("  ✓ %s: WR=%.1f%% n=%d Sharpe=%.3f", k, v["wr"], v["n"], v["sharpe"])
    if not tier1 and not tier2:
        logger.info("All 3 skills OVERRIDE — recommend disabling all equity swing skills")

if __name__ == "__main__":
    main()
