"""
validate_intraday_skills.py
Backtest three equity intraday skills on Nifty liquid stocks.

Skills:
  orb_breakout:     5m bars — first 15-min ORB + volume > 1.2× ORB avg
  supertrend_flip:  15m bars — Supertrend(10,3) direction change
  vwap_bounce:      5m bars — 3 bars below/above VWAP then cross

Constraints:
  - yfinance: max 60 days of 5m/15m data
  - Day-relative processing: ORB and VWAP reset each session
  - Exit: SL / target / EOD forced (never hold overnight)
  - IST session: 09:15-15:20 (last entry bar)
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SYMBOLS = [
    "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS",
    "SBIN", "KOTAKBANK", "LT", "AXISBANK", "WIPRO",
    "MARUTI", "SUNPHARMA", "BAJFINANCE", "NTPC", "ITC",
    "HCLTECH", "BHARTIARTL", "BPCL", "TITAN", "TATASTEEL",
]

BROKERAGE = 0.0008
TIER1_WR, TIER1_TRADES, TIER1_SHARPE = 0.50, 30, 0.6
TIER2_WR, TIER2_TRADES, TIER2_SHARPE = 0.40, 15, 0.3


# ── Data ─────────────────────────────────────────────────────────────────────

def _fetch_intraday(sym: str, interval: str) -> pd.DataFrame | None:
    try:
        import yfinance as yf
        df = yf.download(f"{sym}.NS", period="60d", interval=interval,
                         progress=False, auto_adjust=True)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df.columns = [c.lower() for c in df.columns]
        df = df.dropna(subset=["close", "high", "low", "volume"])
        # IST offset: yfinance returns UTC, NSE is UTC+5:30
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        df.index = df.index.tz_convert("Asia/Kolkata")
        # Market hours only: 09:15 – 15:30
        df = df.between_time("09:15", "15:30")
        return df
    except Exception as e:
        logger.debug("Fetch %s %s failed: %s", sym, interval, e)
        return None


# ── Indicator helpers ─────────────────────────────────────────────────────────

def _supertrend(h, low, c, period=10, mult=3.0):
    n = len(c)
    atr_vals = np.zeros(n)
    tr = np.maximum(h[1:] - low[1:],
                    np.maximum(np.abs(h[1:] - c[:-1]), np.abs(low[1:] - c[:-1])))
    atr_vals[period] = tr[:period].mean()
    for i in range(period + 1, n):
        atr_vals[i] = (atr_vals[i-1] * (period-1) + tr[i-1]) / period

    mid = (h + low) / 2.0
    up  = mid - mult * atr_vals
    dn  = mid + mult * atr_vals
    trend = np.ones(n)

    for i in range(1, n):
        up[i] = max(up[i], up[i-1]) if c[i-1] > up[i-1] else up[i]
        dn[i] = min(dn[i], dn[i-1]) if c[i-1] < dn[i-1] else dn[i]
        if c[i] > dn[i]:
            trend[i] = 1
        elif c[i] < up[i]:
            trend[i] = -1
        else:
            trend[i] = trend[i-1]
    return trend, up, dn


# ── Scanners ─────────────────────────────────────────────────────────────────

def _simulate_orb(df: pd.DataFrame, rrr: float) -> list[dict]:
    trades = []
    for day, grp in df.groupby(df.index.date):
        grp = grp.sort_index()
        if len(grp) < 6:
            continue
        c   = grp["close"].values.astype(float)
        h   = grp["high"].values.astype(float)
        low = grp["low"].values.astype(float)
        v   = grp["volume"].values.astype(float)

        orb_high = h[:3].max()
        orb_low  = low[:3].min()
        orb_risk = orb_high - orb_low
        if orb_risk <= 0:
            continue
        avg_vol = v[:3].mean()

        signal_fired = False
        for i in range(3, len(grp) - 1):
            if signal_fired:
                break
            if avg_vol <= 0 or v[i] < 1.2 * avg_vol:
                continue

            if c[i] > orb_high:
                direction, entry, sl = "LONG", c[i], orb_low
            elif c[i] < orb_low:
                direction, entry, sl = "SHORT", c[i], orb_high
            else:
                continue

            signal_fired = True
            risk = abs(entry - sl)
            if risk <= 0:
                continue
            target = entry + rrr * risk if direction == "LONG" else entry - rrr * risk

            exit_price, exit_why = c[-1], "eod"
            for j in range(i+1, len(grp)):
                lo_j, hi_j = low[j], h[j]
                if direction == "LONG":
                    if lo_j <= sl:
                        exit_price, exit_why = sl, "sl"; break
                    if hi_j >= target:
                        exit_price, exit_why = target, "target"; break
                else:
                    if hi_j >= sl:
                        exit_price, exit_why = sl, "sl"; break
                    if lo_j <= target:
                        exit_price, exit_why = target, "target"; break

            ret = (exit_price - entry)/entry*100 if direction == "LONG" else (entry - exit_price)/entry*100
            ret -= BROKERAGE * 100
            trades.append({"date": day, "direction": direction,
                           "ret": round(ret, 4), "win": ret > 0, "exit_why": exit_why})
    return trades


def _simulate_supertrend(df: pd.DataFrame, rrr: float) -> list[dict]:
    if len(df) < 25:
        return []
    c   = df["close"].values.astype(float)
    h   = df["high"].values.astype(float)
    low = df["low"].values.astype(float)
    trend, up, dn = _supertrend(h, low, c, period=10, mult=3.0)

    trades = []
    used_dates: set = set()

    for i in range(1, len(df) - 1):
        flip = None
        if trend[i] == 1 and trend[i-1] == -1:
            flip = "LONG"
        elif trend[i] == -1 and trend[i-1] == 1:
            flip = "SHORT"
        if flip is None:
            continue

        bar_date = df.index[i].date()
        # Only one signal per stock per day
        if bar_date in used_dates:
            continue
        used_dates.add(bar_date)

        entry = float(c[i])
        sl    = float(up[i]) if flip == "LONG" else float(dn[i])
        risk  = abs(entry - sl)
        if risk <= 0:
            continue
        target = entry + rrr * risk if flip == "LONG" else entry - rrr * risk

        # Exit within same day (EOD forced)
        day_bars = df[df.index.date == bar_date]
        day_idx  = list(day_bars.index).index(df.index[i]) if df.index[i] in day_bars.index else -1
        remaining = day_bars.iloc[day_idx+1:] if day_idx >= 0 else pd.DataFrame()

        exit_price, exit_why = float(c[min(i+1, len(df)-1)]), "eod"
        if not remaining.empty:
            exit_price = float(remaining["close"].iloc[-1])
            for _, row in remaining.iterrows():
                lo_j, hi_j = float(row["low"]), float(row["high"])
                if flip == "LONG":
                    if lo_j <= sl:
                        exit_price, exit_why = sl, "sl"; break
                    if hi_j >= target:
                        exit_price, exit_why = target, "target"; break
                else:
                    if hi_j >= sl:
                        exit_price, exit_why = sl, "sl"; break
                    if lo_j <= target:
                        exit_price, exit_why = target, "target"; break

        ret = (exit_price - entry)/entry*100 if flip == "LONG" else (entry - exit_price)/entry*100
        ret -= BROKERAGE * 100
        trades.append({"date": bar_date, "direction": flip,
                       "ret": round(ret, 4), "win": ret > 0, "exit_why": exit_why})
    return trades


def _simulate_vwap(df: pd.DataFrame, rrr: float) -> list[dict]:
    trades = []
    for day, grp in df.groupby(df.index.date):
        grp = grp.sort_index()
        if len(grp) < 6:
            continue
        c   = grp["close"].values.astype(float)
        h   = grp["high"].values.astype(float)
        low = grp["low"].values.astype(float)
        v   = grp["volume"].values.astype(float)

        tp      = (h + low + c) / 3.0
        cum_vol = np.cumsum(v)
        vwap    = np.cumsum(tp * v) / np.where(cum_vol > 0, cum_vol, 1.0)
        diff    = c - vwap

        signal_fired = False
        for i in range(4, len(grp) - 1):
            if signal_fired:
                break
            if diff[i-3] < 0 and diff[i-2] < 0 and diff[i-1] < 0 and diff[i] > 0:
                direction, entry = "LONG", c[i]
                sl = low[max(0,i-2):i+1].min()
            elif diff[i-3] > 0 and diff[i-2] > 0 and diff[i-1] > 0 and diff[i] < 0:
                direction, entry = "SHORT", c[i]
                sl = h[max(0,i-2):i+1].max()
            else:
                continue

            signal_fired = True
            risk = abs(entry - sl)
            if risk <= 0:
                continue
            target = entry + rrr * risk if direction == "LONG" else entry - rrr * risk

            exit_price, exit_why = c[-1], "eod"
            for j in range(i+1, len(grp)):
                lo_j, hi_j = low[j], h[j]
                if direction == "LONG":
                    if lo_j <= sl:
                        exit_price, exit_why = sl, "sl"; break
                    if hi_j >= target:
                        exit_price, exit_why = target, "target"; break
                else:
                    if hi_j >= sl:
                        exit_price, exit_why = sl, "sl"; break
                    if lo_j <= target:
                        exit_price, exit_why = target, "target"; break

            ret = (exit_price - entry)/entry*100 if direction == "LONG" else (entry - exit_price)/entry*100
            ret -= BROKERAGE * 100
            trades.append({"date": day, "direction": direction,
                           "ret": round(ret, 4), "win": ret > 0, "exit_why": exit_why})
    return trades


# ── Metrics ───────────────────────────────────────────────────────────────────

def _metrics(trades: list[dict], label: str) -> dict:
    if not trades:
        logger.info("  %-25s | n=  0 → OVERRIDE (no trades)", label)
        return {"n": 0, "wr": 0, "sharpe": 0, "verdict": "OVERRIDE", "exits": {}}
    rets  = [t["ret"] for t in trades]
    wins  = [r for r in rets if r > 0]
    n, wr = len(rets), len(wins) / len(rets)
    std   = np.std(rets, ddof=1) if n > 1 else 1.0
    # Intraday annualisation: ~252 days × ~15 trades/day per stock → use sqrt(252)
    sharpe = np.mean(rets) / std * (252 ** 0.5) if std > 0 else 0
    exits  = {}
    for t in trades:
        exits[t["exit_why"]] = exits.get(t["exit_why"], 0) + 1
    if wr >= TIER1_WR and n >= TIER1_TRADES and sharpe >= TIER1_SHARPE:
        verdict = "TIER_1"
    elif wr >= TIER2_WR and n >= TIER2_TRADES and sharpe >= TIER2_SHARPE:
        verdict = "TIER_2"
    else:
        verdict = "OVERRIDE"
    logger.info("  %-25s | n=%3d | WR=%-5.1f%% | Sharpe=%-6.3f | Exit:%s → %s",
                label, n, wr*100, sharpe, exits, verdict)
    return {"n": n, "wr": round(wr*100,1), "sharpe": round(sharpe,3),
            "verdict": verdict, "exits": exits}


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rrr", type=float, nargs="+", default=[1.5, 2.0, 2.5])
    args = parser.parse_args()

    logger.info("Fetching intraday data (60d max from yfinance)...")
    data_5m  = {}
    data_15m = {}
    for sym in SYMBOLS:
        df5 = _fetch_intraday(sym, "5m")
        if df5 is not None and len(df5) >= 50:
            data_5m[sym] = df5
        df15 = _fetch_intraday(sym, "15m")
        if df15 is not None and len(df15) >= 20:
            data_15m[sym] = df15

    logger.info("5m data: %d symbols | 15m data: %d symbols",
                len(data_5m), len(data_15m))

    all_results = {}

    logger.info("\n══ ORB BREAKOUT (5m) ══")
    for rrr in args.rrr:
        all_trades = []
        for df in data_5m.values():
            all_trades.extend(_simulate_orb(df, rrr))
        m = _metrics(all_trades, f"orb_breakout RRR {rrr}")
        all_results[f"orb_rrr{rrr}"] = m

    logger.info("\n══ SUPERTREND FLIP (15m) ══")
    for rrr in args.rrr:
        all_trades = []
        for df in data_15m.values():
            all_trades.extend(_simulate_supertrend(df, rrr))
        m = _metrics(all_trades, f"supertrend_flip RRR {rrr}")
        all_results[f"st_rrr{rrr}"] = m

    logger.info("\n══ VWAP BOUNCE (5m) ══")
    for rrr in args.rrr:
        all_trades = []
        for df in data_5m.values():
            all_trades.extend(_simulate_vwap(df, rrr))
        m = _metrics(all_trades, f"vwap_bounce RRR {rrr}")
        all_results[f"vwap_rrr{rrr}"] = m

    logger.info("\n── SUMMARY ──")
    tier1 = [(k,v) for k,v in all_results.items() if v["verdict"]=="TIER_1"]
    tier2 = [(k,v) for k,v in all_results.items() if v["verdict"]=="TIER_2"]
    over  = [(k,v) for k,v in all_results.items() if v["verdict"]=="OVERRIDE"]
    logger.info("TIER_1: %d | TIER_2: %d | OVERRIDE: %d",
                len(tier1), len(tier2), len(over))
    for k,v in tier1+tier2:
        logger.info("  ✓ %s: WR=%.1f%% n=%d Sharpe=%.3f", k, v["wr"], v["n"], v["sharpe"])
    if not tier1 and not tier2:
        logger.info("All 3 intraday skills OVERRIDE — recommend disabling all")

if __name__ == "__main__":
    main()
