"""
validate_forex_remaining.py
Backtest forex_ema_cross and bb_squeeze on all forex pairs.

Strategies:
  forex_ema_cross: EMA9 crosses above/below EMA21 → LONG/SHORT
  bb_squeeze:      BB width < 1% then price breaks above upper / below lower → LONG/SHORT

Pairs: USDINR, EURUSD, GBPUSD, USDJPY
Interval: 1H bars, 365-day lookback
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


def _ema(arr: np.ndarray, p: int) -> np.ndarray:
    out = np.full(len(arr), np.nan)
    if len(arr) < p:
        return out
    out[p - 1] = arr[:p].mean()
    k = 2.0 / (p + 1)
    for i in range(p, len(arr)):
        out[i] = arr[i] * k + out[i - 1] * (1 - k)
    return out


def _bb(c: np.ndarray, p: int = 20, mult: float = 2.0):
    if len(c) < p:
        return np.nan, np.nan, np.nan
    w = c[-p:]
    sma = w.mean()
    std = w.std(ddof=0)
    return sma, sma + mult * std, sma - mult * std


def _fetch(yf_sym: str, days: int) -> pd.DataFrame | None:
    try:
        import yfinance as yf
        df = yf.download(yf_sym, period=f"{min(days+30,720)}d", interval="1h",
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


def _simulate(df: pd.DataFrame, scanner: str, rrr: float,
              lookback: int, max_hold: int = 20) -> list[dict]:
    cutoff = date.today() - timedelta(days=lookback)
    c  = df["close"].values.astype(float)
    h  = df["high"].values.astype(float)
    lo = df["low"].values.astype(float)

    e9  = _ema(c, 9)
    e21 = _ema(c, 21)

    trades = []
    last_i = -5

    for i in range(25, len(df) - max_hold - 1):
        bar_date = df.index[i].date() if hasattr(df.index[i], "date") else df.index[i]
        if bar_date < cutoff:
            continue
        if i - last_i < 5:
            continue

        direction = None
        sl = None

        if scanner == "ema_cross":
            if not (np.isnan(e9[i]) or np.isnan(e9[i-1]) or np.isnan(e21[i]) or np.isnan(e21[i-1])):
                if e9[i] > e21[i] and e9[i-1] <= e21[i-1]:
                    direction, sl = "LONG", float(lo[max(0,i-2):i+1].min())
                elif e9[i] < e21[i] and e9[i-1] >= e21[i-1]:
                    direction, sl = "SHORT", float(h[max(0,i-2):i+1].max())

        elif scanner == "bb_squeeze":
            sma, upper, lower = _bb(c[:i], 20, 2.0)
            if np.isnan(sma) or sma <= 0:
                continue
            width_pct = (upper - lower) / sma * 100
            if width_pct >= 1.0:
                continue
            if c[i] > upper:
                direction, sl = "LONG", float(lo[max(0,i-2):i+1].min())
            elif c[i] < lower:
                direction, sl = "SHORT", float(h[max(0,i-2):i+1].max())

        if direction is None or sl is None:
            continue

        last_i = i
        entry = float(c[i])
        risk  = abs(entry - sl)
        if risk <= 0:
            continue
        target = entry + rrr * risk if direction == "LONG" else entry - rrr * risk

        exit_price, exit_why = None, "max_hold"
        for j in range(i+1, min(i+1+max_hold, len(df))):
            if direction == "LONG":
                if lo[j] <= sl:
                    exit_price, exit_why = sl, "sl"; break
                if h[j] >= target:
                    exit_price, exit_why = target, "target"; break
            else:
                if h[j] >= sl:
                    exit_price, exit_why = sl, "sl"; break
                if lo[j] <= target:
                    exit_price, exit_why = target, "target"; break
        if exit_price is None:
            exit_price = float(c[min(i+max_hold, len(df)-1)])

        ret = (exit_price - entry)/entry*100 if direction == "LONG" else (entry - exit_price)/entry*100
        trades.append({"date": bar_date, "direction": direction,
                       "ret": round(ret, 4), "win": ret > 0, "exit_why": exit_why})

    return trades


def _metrics(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "wr": 0, "sharpe": 0, "verdict": "OVERRIDE"}
    rets  = [t["ret"] for t in trades]
    wins  = [r for r in rets if r > 0]
    n, wr = len(rets), len(wins)/len(rets)
    std   = np.std(rets, ddof=1) if n > 1 else 1.0
    sharpe = np.mean(rets)/std*(252*6.5)**0.5 if std > 0 else 0
    exits = {}
    for t in trades:
        exits[t["exit_why"]] = exits.get(t["exit_why"], 0) + 1
    if wr >= TIER1_WR and n >= TIER1_TRADES and sharpe >= TIER1_SHARPE:
        verdict = "TIER_1"
    elif wr >= TIER2_WR and n >= TIER2_TRADES and sharpe >= TIER2_SHARPE:
        verdict = "TIER_2"
    else:
        verdict = "OVERRIDE"
    return {"n": n, "wr": round(wr*100,1), "sharpe": round(sharpe,3),
            "verdict": verdict, "exits": exits}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--rrr",  type=float, nargs="+", default=[1.5, 2.0])
    args = parser.parse_args()

    data = {}
    for name, sym in PAIRS.items():
        df = _fetch(sym, args.days)
        if df is not None and len(df) >= 50:
            data[name] = df
            logger.info("Loaded %s: %d bars", name, len(df))

    all_results: dict[str, dict] = {}

    for scanner in ("ema_cross", "bb_squeeze"):
        logger.info("\n══ %s ══", scanner.upper())
        for pair, df in data.items():
            for rrr in args.rrr:
                trades = _simulate(df, scanner, rrr, args.days)
                m = _metrics(trades)
                key = f"{scanner}_{pair}_rrr{rrr}"
                all_results[key] = m
                logger.info("  %-8s RRR %.1f | n=%3d | WR=%-5.1f%% | Sharpe=%-6.3f | %s → %s",
                            pair, rrr, m["n"], m["wr"], m["sharpe"],
                            m.get("exits", {}), m["verdict"])

    logger.info("\n── SUMMARY ──")
    tier1 = [(k,v) for k,v in all_results.items() if v["verdict"]=="TIER_1"]
    tier2 = [(k,v) for k,v in all_results.items() if v["verdict"]=="TIER_2"]
    over  = [(k,v) for k,v in all_results.items() if v["verdict"]=="OVERRIDE"]
    logger.info("TIER_1: %d | TIER_2: %d | OVERRIDE: %d", len(tier1), len(tier2), len(over))
    for k, v in tier1 + tier2:
        logger.info("  ✓ %s: WR=%.1f%% n=%d Sharpe=%.3f", k, v["wr"], v["n"], v["sharpe"])
    if not tier1 and not tier2:
        logger.info("Both skills OVERRIDE on all pairs — recommend disabling both")

if __name__ == "__main__":
    main()
