"""
validate_bandwalk_highs.py
Walk-forward backtest of the bandwalk_highs Chartink scanner.

Chartink logic (daily bars):
  - latest high >= max(5, latest high)  ← 5-day high breakout
  - latest close > latest open           ← green candle
  - latest high >= upper BB(20, 2)       ← hugging upper band

Variant tested:
  - baseline: above 3 conditions
  - adx25:    baseline + ADX(14) > 25    ← strong trend only

Live Bayesian: 11W/47L = 21% WR (OVERRIDE).

Usage:
    python scripts/validate_bandwalk_highs.py
    python scripts/validate_bandwalk_highs.py --days 365 --rrr 1.5 2.0
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

# ── Universe: Nifty 100 via yfinance ─────────────────────────────────────────
SYMBOLS = [
    "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "BHARTIARTL",
    "SBIN", "KOTAKBANK", "LT", "AXISBANK", "WIPRO", "HCLTECH",
    "MARUTI", "SUNPHARMA", "TITAN", "BAJFINANCE", "BAJAJFINSV", "ULTRACEMCO",
    "NTPC", "POWERGRID", "ONGC", "BPCL", "COALINDIA", "GRASIM",
    "JSWSTEEL", "TATASTEEL", "TATAMOTORS", "TATACONSUM", "NESTLEIND",
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "BRITANNIA",
    "CIPLA", "DRREDDY", "EICHERMOT", "HEROMOTOCO", "HDFCLIFE", "HINDUNILVR",
    "INDUSINDBK", "ITC", "SHRIRAMFIN", "SBILIFE", "TECHM", "TRENT",
    "ZOMATO", "BEL", "DIXONS", "HAVELLS", "SIEMENS", "MOTHERSON",
    "PIIND", "TORNTPHARM", "PERSISTENT", "MPHASIS", "COFORGE",
    "VOLTAS", "CUMMINSIND", "AAVAS", "ABCAPITAL", "ALKEM",
]

POSITION_INR  = 100_000
BROKERAGE_PCT = 0.0003
STT_PCT       = 0.00025
SLIPPAGE_PCT  = 0.0005
TOTAL_COST    = BROKERAGE_PCT * 2 + STT_PCT + SLIPPAGE_PCT
MAX_HOLD      = 15  # trading days

TIER1_WR, TIER1_TRADES, TIER1_SHARPE = 0.50, 15, 0.6
TIER2_WR, TIER2_TRADES, TIER2_SHARPE = 0.40, 8,  0.3


# ── Indicators ────────────────────────────────────────────────────────────────

def _ema(arr: np.ndarray, p: int) -> np.ndarray:
    out = np.full(len(arr), np.nan)
    if len(arr) < p:
        return out
    out[p - 1] = arr[:p].mean()
    k = 2.0 / (p + 1)
    for i in range(p, len(arr)):
        out[i] = arr[i] * k + out[i - 1] * (1 - k)
    return out


def _bb_upper(c: np.ndarray, period: int = 20, mult: float = 2.0) -> np.ndarray:
    out = np.full(len(c), np.nan)
    for i in range(period - 1, len(c)):
        window = c[i - period + 1: i + 1]
        out[i] = window.mean() + mult * window.std(ddof=0)
    return out


def _adx(h: np.ndarray, low: np.ndarray, c: np.ndarray, p: int = 14) -> np.ndarray:
    n = len(c)
    out = np.zeros(n)
    if n < 2 * p + 1:
        return out
    tr  = np.maximum(h[1:] - low[1:],
          np.maximum(np.abs(h[1:] - c[:-1]),
                     np.abs(low[1:] - c[:-1])))
    dmp = np.where((h[1:] - h[:-1]) > (low[:-1] - low[1:]),
                   np.maximum(h[1:] - h[:-1], 0.0), 0.0)
    dmm = np.where((low[:-1] - low[1:]) > (h[1:] - h[:-1]),
                   np.maximum(low[:-1] - low[1:], 0.0), 0.0)
    m = len(tr)
    atr_s = np.zeros(m)
    dmp_s = np.zeros(m)
    dmm_s = np.zeros(m)
    atr_s[p - 1] = tr[:p].sum()
    dmp_s[p - 1] = dmp[:p].sum()
    dmm_s[p - 1] = dmm[:p].sum()
    for i in range(p, m):
        atr_s[i] = atr_s[i-1] - atr_s[i-1]/p + tr[i]
        dmp_s[i] = dmp_s[i-1] - dmp_s[i-1]/p + dmp[i]
        dmm_s[i] = dmm_s[i-1] - dmm_s[i-1]/p + dmm[i]
    di_p = np.where(atr_s > 0, 100 * dmp_s / atr_s, 0.0)
    di_m = np.where(atr_s > 0, 100 * dmm_s / atr_s, 0.0)
    dx   = np.where((di_p + di_m) > 0, 100 * np.abs(di_p - di_m) / (di_p + di_m), 0.0)
    start = 2 * p - 2
    if start >= m:
        return out
    adx_s = np.zeros(m)
    adx_s[start] = dx[p - 1: start + 1].mean()
    for i in range(start + 1, m):
        adx_s[i] = (adx_s[i-1] * (p-1) + dx[i]) / p
    for i in range(start, m):
        out[i + 1] = adx_s[i]
    return out


# ── Scanners ──────────────────────────────────────────────────────────────────

def _scan_bandwalk(df: pd.DataFrame, adx_filter: bool = False) -> dict | None:
    """bandwalk_highs logic on daily bars."""
    if len(df) < 22:
        return None
    c   = df["close"].values.astype(float)
    h   = df["high"].values.astype(float)
    low = df["low"].values.astype(float)
    opn = df["open"].values.astype(float)

    # 5-day high breakout
    if h[-1] < h[-6:-1].max():
        return None
    # Green candle
    if c[-1] <= opn[-1]:
        return None
    # Upper BB touch
    bb_up = _bb_upper(c, 20, 2.0)
    if np.isnan(bb_up[-1]) or h[-1] < bb_up[-1]:
        return None
    # ADX filter (variant)
    if adx_filter:
        adx_arr = _adx(h, low, c, 14)
        if adx_arr[-1] < 25:
            return None

    # SL = lower BB
    bb_lo = np.full(len(c), np.nan)
    for i in range(19, len(c)):
        w = c[i - 19: i + 1]
        bb_lo[i] = w.mean() - 2.0 * w.std(ddof=0)
    sl = float(bb_lo[-1]) if not np.isnan(bb_lo[-1]) else float(low[-3:].min())
    return {"direction": "LONG", "entry": float(c[-1]), "sl": sl}


# ── Data ─────────────────────────────────────────────────────────────────────

def _fetch(sym: str, days: int) -> pd.DataFrame | None:
    try:
        import yfinance as yf
        df = yf.download(f"{sym}.NS", period=f"{min(days + 60, 500)}d",
                         interval="1d", progress=False, auto_adjust=True)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df.columns = [c.lower() for c in df.columns]
        return df.dropna(subset=["close", "high", "low", "open"])
    except Exception as e:
        logger.warning("Fetch failed %s: %s", sym, e)
        return None


# ── Simulation ────────────────────────────────────────────────────────────────

def _simulate(df: pd.DataFrame, scanner_fn, lookback: int, rrr: float,
              max_hold: int = MAX_HOLD) -> list[dict]:
    cutoff = date.today() - timedelta(days=lookback)
    trades = []
    for i in range(22, len(df) - 1):
        sig_date = df.index[i].date()
        if sig_date < cutoff:
            continue
        sig = scanner_fn(df.iloc[:i + 1])
        if not sig:
            continue
        if i + 1 >= len(df):
            continue
        entry = float(df["open"].iloc[i + 1])
        sl    = sig["sl"]
        risk  = abs(entry - sl)
        if risk <= 0:
            continue
        target = entry + rrr * risk

        exit_price, exit_why = None, "max_hold"
        for j in range(i + 2, min(i + 2 + max_hold, len(df))):
            lo = float(df["low"].iloc[j])
            hi = float(df["high"].iloc[j])
            if lo <= sl:
                exit_price, exit_why = sl, "sl"
                break
            if hi >= target:
                exit_price, exit_why = target, "target"
                break
        if exit_price is None:
            exit_price = float(df["close"].iloc[min(i + 2 + max_hold - 1, len(df) - 1)])

        ret = (exit_price - entry) / entry * 100 - TOTAL_COST * 100
        trades.append({
            "date": sig_date, "exit_why": exit_why,
            "ret": round(ret, 3), "win": ret > 0,
        })
    return trades


def _metrics(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "wr": 0, "sharpe": 0, "pnl": 0, "verdict": "OVERRIDE", "exit": {}}
    rets  = [t["ret"] for t in trades]
    wins  = [r for r in rets if r > 0]
    n, wr = len(rets), len(wins) / len(rets)
    pnl   = sum(POSITION_INR * r / 100 for r in rets)
    std   = np.std(rets, ddof=1) if n > 1 else 1.0
    sharpe = np.mean(rets) / std * (252 ** 0.5) if std > 0 else 0
    exit_dist = {}
    for t in trades:
        exit_dist[t["exit_why"]] = exit_dist.get(t["exit_why"], 0) + 1
    if wr >= TIER1_WR and n >= TIER1_TRADES and sharpe >= TIER1_SHARPE:
        verdict = "TIER_1"
    elif wr >= TIER2_WR and n >= TIER2_TRADES and sharpe >= TIER2_SHARPE:
        verdict = "TIER_2"
    else:
        verdict = "OVERRIDE"
    return {"n": n, "wr": round(wr * 100, 1), "sharpe": round(sharpe, 3),
            "pnl": round(pnl, 0), "verdict": verdict, "exit": exit_dist}


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--rrr",  type=float, nargs="+", default=[1.5, 2.0, 2.5])
    args = parser.parse_args()

    logger.info("Fetching data for %d symbols (%dd lookback)...", len(SYMBOLS), args.days)
    data: dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS:
        df = _fetch(sym, args.days)
        if df is not None and len(df) >= 30:
            data[sym] = df

    logger.info("Loaded %d symbols", len(data))

    variants = [
        ("bandwalk_baseline",    lambda df: _scan_bandwalk(df, adx_filter=False), MAX_HOLD),
        ("bandwalk_adx25",       lambda df: _scan_bandwalk(df, adx_filter=True),  MAX_HOLD),
        ("bandwalk_adx25_5d",    lambda df: _scan_bandwalk(df, adx_filter=True),  5),
    ]

    for name, fn, mh in variants:
        logger.info("\n── %s (max_hold=%d) ──", name.upper(), mh)
        best_verdict, best_m, best_rrr = "OVERRIDE", {}, args.rrr[0]
        for rrr in args.rrr:
            all_trades: list[dict] = []
            for df in data.values():
                all_trades.extend(_simulate(df, fn, args.days, rrr, max_hold=mh))
            m = _metrics(all_trades)
            logger.info("  RRR %.1f | trades=%d WR=%.1f%% Sharpe=%.3f P&L=₹%.0f → %s",
                        rrr, m["n"], m["wr"], m["sharpe"], m["pnl"], m["verdict"])
            if m["n"] > 0 and (best_verdict == "OVERRIDE" or
                               m["sharpe"] > best_m.get("sharpe", -99)):
                best_verdict, best_m, best_rrr = m["verdict"], m, rrr
        logger.info("  Best RRR %.1f | Exit: %s", best_rrr, best_m.get("exit", {}))

    logger.info("\n── COMPARISON ──")
    logger.info("Live Bayesian: 11W/47L = 21%% WR (OVERRIDE)")
    logger.info("Backtest baseline vs adx25 above ↑")


if __name__ == "__main__":
    main()
