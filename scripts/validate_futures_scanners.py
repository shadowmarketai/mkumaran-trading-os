"""
validate_futures_scanners.py
Walk-forward backtest for all futures scanners in agents/skills/futures/.

Mirrors validate_intraday_scanners.py structure:
  - Same tier thresholds (TIER_1 / TIER_2 / OVERRIDE)
  - Same regime filter (Nifty Supertrend 10,3 daily)
  - Same cost model (brokerage + STT + slippage)

Exit logic (daily bars — not intraday):
  - Target hit: price touches entry + RRR × risk
  - SL hit:     price touches stop loss
  - Max hold:   20 trading days (1 calendar month)
  Entry is at next-day open after signal fires.

Usage:
  python scripts/validate_futures_scanners.py
  python scripts/validate_futures_scanners.py --days 180 --rrr 1.5 2.0 2.5
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

# ── Universe ──────────────────────────────────────────────────────────────────
INDEX_SYMBOLS = ["NIFTY", "BANKNIFTY"]
STOCK_SYMBOLS = [
    "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS",
    "SBIN", "BAJFINANCE", "TATAMOTORS", "LT", "AXISBANK",
    # Extended — top F&O liquidity
    "KOTAKBANK", "MARUTI", "BHARTIARTL", "TATASTEEL", "HINDUNILVR",
    "HAL", "ADANIENT", "WIPRO", "SUNPHARMA", "M&M",
]
ALL_SYMBOLS = INDEX_SYMBOLS + STOCK_SYMBOLS

YFINANCE_MAP = {
    "NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK",
    "M&M": "M%26M.NS",
    **{s: f"{s}.NS" for s in STOCK_SYMBOLS if s != "M&M"},
}

# ── Cost model ────────────────────────────────────────────────────────────────
POSITION_INR   = 100_000   # notional per trade
BROKERAGE_PCT  = 0.0003    # 0.03% each side
STT_PCT        = 0.0001    # 0.01% on sell side (futures)
SLIPPAGE_PCT   = 0.0005    # 0.05% total (entry + exit)
TOTAL_COST_PCT = BROKERAGE_PCT * 2 + STT_PCT + SLIPPAGE_PCT

# ── Tier thresholds (daily — lower trade count than intraday) ─────────────────
TIER1_WR     = 0.50   # ≥ 50% win rate
TIER1_TRADES = 15     # ≥ 15 trades
TIER1_SHARPE = 0.6
TIER2_WR     = 0.40
TIER2_TRADES = 8
TIER2_SHARPE = 0.3
MAX_HOLD_DAYS = 20    # max bars to hold a trade


# ── Indicators (pure numpy — no dependency on mcp_server) ────────────────────

def _ema(arr: np.ndarray, period: int) -> np.ndarray:
    result = np.empty_like(arr)
    result[:] = np.nan
    if len(arr) < period:
        return result
    result[period - 1] = arr[:period].mean()
    k = 2.0 / (period + 1)
    for i in range(period, len(arr)):
        result[i] = arr[i] * k + result[i - 1] * (1 - k)
    return result


def _adx(high: np.ndarray, low: np.ndarray, close: np.ndarray,
         period: int = 14) -> np.ndarray:
    """Wilder's ADX. Output index i corresponds to original bar i."""
    n = len(close)
    out = np.zeros(n)
    if n < 2 * period + 1:
        return out

    # TR / DM arrays — length n-1, element i corresponds to original bar i+1
    tr  = np.maximum(high[1:] - low[1:],
          np.maximum(np.abs(high[1:] - close[:-1]),
                     np.abs(low[1:] - close[:-1])))
    dmp = np.where((high[1:] - high[:-1]) > (low[:-1] - low[1:]),
                   np.maximum(high[1:] - high[:-1], 0.0), 0.0)
    dmm = np.where((low[:-1] - low[1:]) > (high[1:] - high[:-1]),
                   np.maximum(low[:-1] - low[1:], 0.0), 0.0)

    # Wilder smoothing (length = len(tr))
    m = len(tr)
    atr_s = np.zeros(m)
    dmp_s = np.zeros(m)
    dmm_s = np.zeros(m)
    atr_s[period - 1] = tr[:period].sum()
    dmp_s[period - 1] = dmp[:period].sum()
    dmm_s[period - 1] = dmm[:period].sum()
    for i in range(period, m):
        atr_s[i] = atr_s[i - 1] - atr_s[i - 1] / period + tr[i]
        dmp_s[i] = dmp_s[i - 1] - dmp_s[i - 1] / period + dmp[i]
        dmm_s[i] = dmm_s[i - 1] - dmm_s[i - 1] / period + dmm[i]

    di_p = np.where(atr_s > 0, 100 * dmp_s / atr_s, 0.0)
    di_m = np.where(atr_s > 0, 100 * dmm_s / atr_s, 0.0)
    dx   = np.where((di_p + di_m) > 0,
                    100 * np.abs(di_p - di_m) / (di_p + di_m), 0.0)

    # ADX = Wilder smooth of DX; first valid at index 2*period-2 of tr array
    # which maps to original bar 2*period-1
    start = 2 * period - 2   # first bar with full ADX in tr-indexed space
    if start >= m:
        return out
    adx_s = np.zeros(m)
    adx_s[start] = dx[period - 1: start + 1].mean()
    for i in range(start + 1, m):
        adx_s[i] = (adx_s[i - 1] * (period - 1) + dx[i]) / period

    # Map tr-indexed back to original bars (tr[i] → original bar i+1)
    for i in range(start, m):
        out[i + 1] = adx_s[i]
    return out


# ── Scanner signal functions ──────────────────────────────────────────────────

def _scan_ema_cross_adx(df: pd.DataFrame) -> dict | None:
    """Baseline: EMA 9/21 crossover + ADX > 25."""
    if len(df) < 30:
        return None
    c   = df["close"].values.astype(float)
    h   = df["high"].values.astype(float)
    low = df["low"].values.astype(float)
    e9  = _ema(c, 9)
    e21 = _ema(c, 21)
    adx_arr = _adx(h, low, c, 14)
    if np.isnan(e9[-1]) or np.isnan(e21[-1]) or adx_arr[-1] < 25:
        return None
    if e9[-1] > e21[-1] and e9[-2] <= e21[-2]:
        sl = float(low[-3:].min())
        return {"direction": "LONG",  "entry": float(c[-1]), "sl": sl}
    if e9[-1] < e21[-1] and e9[-2] >= e21[-2]:
        sl = float(h[-3:].max())
        return {"direction": "SHORT", "entry": float(c[-1]), "sl": sl}
    return None


def _atr14(h: np.ndarray, low: np.ndarray, c: np.ndarray) -> float:
    """Last ATR(14) value."""
    tr = np.maximum(h[1:] - low[1:],
         np.maximum(np.abs(h[1:] - c[:-1]),
                    np.abs(low[1:] - c[:-1])))
    if len(tr) < 14:
        return float(tr.mean()) if len(tr) > 0 else 0.0
    atr = np.zeros(len(tr))
    atr[13] = tr[:14].mean()
    for i in range(14, len(tr)):
        atr[i] = (atr[i - 1] * 13 + tr[i]) / 14
    return float(atr[-1])


def _scan_ema_21_55(df: pd.DataFrame) -> dict | None:
    """Variant A: EMA 21/55 cross + ADX > 25 — medium-term, less whipsaw."""
    if len(df) < 60:
        return None
    c   = df["close"].values.astype(float)
    h   = df["high"].values.astype(float)
    low = df["low"].values.astype(float)
    e21 = _ema(c, 21)
    e55 = _ema(c, 55)
    adx_arr = _adx(h, low, c, 14)
    if np.isnan(e21[-1]) or np.isnan(e55[-1]) or adx_arr[-1] < 25:
        return None
    if e21[-1] > e55[-1] and e21[-2] <= e55[-2]:
        cur_atr = _atr14(h, low, c)
        sl = float(c[-1]) - 1.5 * cur_atr
        return {"direction": "LONG",  "entry": float(c[-1]), "sl": sl}
    if e21[-1] < e55[-1] and e21[-2] >= e55[-2]:
        cur_atr = _atr14(h, low, c)
        sl = float(c[-1]) + 1.5 * cur_atr
        return {"direction": "SHORT", "entry": float(c[-1]), "sl": sl}
    return None


def _scan_volume_breakout(df: pd.DataFrame) -> dict | None:
    """Baseline: volume > 2x avg + new 20d high."""
    if len(df) < 21:
        return None
    c   = df["close"].values.astype(float)
    h   = df["high"].values.astype(float)
    low = df["low"].values.astype(float)
    v   = df["volume"].values.astype(float)
    avg_vol = float(np.mean(v[-21:-1]))
    if avg_vol <= 0 or v[-1] < 2 * avg_vol:
        return None
    high_20 = float(h[-21:-1].max())
    if c[-1] <= high_20:
        return None
    sl = float(low[-3:].min())
    return {"direction": "LONG", "entry": float(c[-1]), "sl": sl}


def _scan_volume_breakout_3x(df: pd.DataFrame) -> dict | None:
    """Variant B: volume > 3x avg + new 20d high — stricter volume filter."""
    if len(df) < 21:
        return None
    c   = df["close"].values.astype(float)
    h   = df["high"].values.astype(float)
    low = df["low"].values.astype(float)
    v   = df["volume"].values.astype(float)
    avg_vol = float(np.mean(v[-21:-1]))
    if avg_vol <= 0 or v[-1] < 3 * avg_vol:
        return None
    high_20 = float(h[-21:-1].max())
    if c[-1] <= high_20:
        return None
    cur_atr = _atr14(h, low, c)
    sl = float(c[-1]) - 1.5 * cur_atr  # ATR-based SL (wider than 3-bar low)
    return {"direction": "LONG", "entry": float(c[-1]), "sl": sl}


# max_hold override per scanner (default = MAX_HOLD_DAYS = 20)
SCANNER_MAX_HOLD: dict[str, int] = {
    "volume_breakout_7d": 7,
}

SCANNERS = {
    "ema_cross_adx":        _scan_ema_cross_adx,
    "ema_21_55":            _scan_ema_21_55,
    "volume_breakout":      _scan_volume_breakout,
    "volume_breakout_3x":   _scan_volume_breakout_3x,
    "volume_breakout_7d":   _scan_volume_breakout,   # same fn, different max_hold
}


# ── Data fetch ────────────────────────────────────────────────────────────────

def _fetch(symbol: str, lookback_days: int) -> pd.DataFrame | None:
    try:
        import yfinance as yf
        ticker = YFINANCE_MAP.get(symbol, f"{symbol}.NS")
        period = f"{min(lookback_days + 60, 365)}d"
        df = yf.download(ticker, period=period, interval="1d",
                         progress=False, auto_adjust=True)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        df.columns = [c.lower() for c in df.columns]
        df = df.dropna(subset=["close", "high", "low", "open"])
        return df
    except Exception as exc:
        logger.warning("Fetch failed for %s: %s", symbol, exc)
        return None


# ── Regime map ────────────────────────────────────────────────────────────────

def _load_regime() -> dict[date, bool]:
    try:
        from mcp_server.market_direction import get_regime_map
        return get_regime_map(lookback_days=365)
    except Exception as exc:
        logger.warning("Regime map unavailable: %s — no filter applied", exc)
        return {}


# ── Trade simulation ──────────────────────────────────────────────────────────

def _simulate_trades(
    df: pd.DataFrame,
    scanner_fn,
    symbol: str,
    regime: dict[date, bool],
    lookback_days: int,
    rrr: float,
    max_hold: int = MAX_HOLD_DAYS,
) -> list[dict]:
    cutoff = date.today() - timedelta(days=lookback_days)
    trades = []

    for i in range(30, len(df) - 1):
        signal_date = df.index[i].date() if hasattr(df.index[i], "date") else df.index[i]
        if signal_date < cutoff:
            continue

        sig = scanner_fn(df.iloc[:i + 1])
        if sig is None:
            continue

        direction = sig["direction"]
        entry_ref = sig["entry"]
        sl        = sig["sl"]

        # Regime filter — skip LONG on bearish days, skip SHORT on bullish days
        if regime:
            is_bullish = regime.get(signal_date, True)
            if direction == "LONG"  and not is_bullish:
                continue
            if direction == "SHORT" and is_bullish:
                continue

        risk = abs(entry_ref - sl)
        if risk <= 0:
            continue

        # Entry at next-day open
        if i + 1 >= len(df):
            continue
        entry_price = float(df["open"].iloc[i + 1])
        entry_date  = df.index[i + 1].date() if hasattr(df.index[i + 1], "date") else df.index[i + 1]

        # Recalculate target/SL from actual entry
        actual_risk   = abs(entry_price - sl)
        actual_target = (entry_price + rrr * actual_risk if direction == "LONG"
                         else entry_price - rrr * actual_risk)

        exit_price = None
        exit_why   = "max_hold"

        for j in range(i + 2, min(i + 2 + max_hold, len(df))):
            bar_high = float(df["high"].iloc[j])
            bar_low  = float(df["low"].iloc[j])

            if direction == "LONG":
                if bar_low <= sl:
                    exit_price = sl
                    exit_why = "sl"
                    break
                if bar_high >= actual_target:
                    exit_price = actual_target
                    exit_why = "target"
                    break
            else:
                if bar_high >= sl:
                    exit_price = sl
                    exit_why = "sl"
                    break
                if bar_low <= actual_target:
                    exit_price = actual_target
                    exit_why = "target"
                    break

        if exit_price is None:
            exit_price = float(df["close"].iloc[min(i + 2 + max_hold - 1, len(df) - 1)])

        if direction == "LONG":
            ret_pct = (exit_price - entry_price) / entry_price * 100
        else:
            ret_pct = (entry_price - exit_price) / entry_price * 100

        ret_pct -= TOTAL_COST_PCT * 100
        win = ret_pct > 0

        trades.append({
            "scanner":    scanner_fn.__name__.replace("_scan_", ""),
            "symbol":     symbol,
            "date":       signal_date,
            "entry_date": entry_date,
            "direction":  direction,
            "entry":      entry_price,
            "sl":         sl,
            "target":     actual_target,
            "exit":       exit_price,
            "exit_why":   exit_why,
            "ret_pct":    round(ret_pct, 3),
            "win":        win,
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

    n      = len(rets)
    wr     = len(wins) / n
    pnl    = sum(POSITION_INR * r / 100 for r in rets)
    mean_r = np.mean(rets)
    std_r  = np.std(rets, ddof=1) if n > 1 else 1.0
    sharpe = mean_r / std_r * (252 ** 0.5) if std_r > 0 else 0.0

    if wr >= TIER1_WR and n >= TIER1_TRADES and sharpe >= TIER1_SHARPE:
        verdict = "TIER_1"
    elif wr >= TIER2_WR and n >= TIER2_TRADES and sharpe >= TIER2_SHARPE:
        verdict = "TIER_2"
    else:
        verdict = "OVERRIDE"

    exit_reasons = {}
    for t in trades:
        exit_reasons[t["exit_why"]] = exit_reasons.get(t["exit_why"], 0) + 1

    return {
        "trades":    n,
        "wr":        round(wr * 100, 1),
        "pnl":       round(pnl, 0),
        "sharpe":    round(sharpe, 3),
        "avg_win":   round(np.mean(wins), 2) if wins else 0,
        "avg_loss":  round(np.mean(loses), 2) if loses else 0,
        "exit_why":  exit_reasons,
        "verdict":   verdict,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days",      type=int,   default=90,
                        help="Lookback trading days (default 90)")
    parser.add_argument("--rrr",       type=float, nargs="+", default=[1.5, 2.0, 2.5],
                        help="RRR values to sweep (default 1.5 2.0 2.5)")
    parser.add_argument("--no-regime", action="store_true",
                        help="Disable regime filter (control test — lets SHORT trades fire)")
    args = parser.parse_args()

    logger.info("Loading regime map...")
    if args.no_regime:
        regime: dict = {}
        logger.info("Regime: DISABLED (control test — both LONG and SHORT allowed)")
    else:
        regime = _load_regime()
        bullish_days = sum(1 for v in regime.values() if v)
        logger.info("Regime: %d days | %d bullish / %d bearish",
                    len(regime), bullish_days, len(regime) - bullish_days)

    logger.info("Fetching daily data for %d symbols...", len(ALL_SYMBOLS))
    data: dict[str, pd.DataFrame] = {}
    for sym in ALL_SYMBOLS:
        df = _fetch(sym, args.days)
        if df is not None and len(df) >= 30:
            data[sym] = df
            logger.info("  %-15s %d bars", sym, len(df))
        else:
            logger.warning("  %-15s NO DATA", sym)

    logger.info("\n%s", "=" * 60)
    logger.info("FUTURES SCANNER BACKTEST — %d symbols, %dd lookback",
                len(data), args.days)
    logger.info("=" * 60)

    all_results: dict[str, dict] = {}

    for scanner_name, scanner_fn in SCANNERS.items():
        mh = SCANNER_MAX_HOLD.get(scanner_name, MAX_HOLD_DAYS)
        logger.info("\n── %s (max_hold=%d) ──", scanner_name.upper(), mh)
        best_verdict = "OVERRIDE"
        best_rrr     = args.rrr[0]
        best_metrics: dict = {}

        for rrr in args.rrr:
            all_trades: list[dict] = []
            for sym, df in data.items():
                trades = _simulate_trades(df, scanner_fn, sym, regime, args.days, rrr, max_hold=mh)
                all_trades.extend(trades)

            m = _metrics(all_trades)
            logger.info(
                "  RRR %.1f | trades=%d WR=%.1f%% Sharpe=%.3f P&L=₹%.0f → %s",
                rrr, m["trades"], m["wr"], m["sharpe"], m["pnl"], m["verdict"],
            )
            if m["trades"] > 0 and (
                best_verdict == "OVERRIDE"
                or (m["verdict"] != "OVERRIDE" and m["sharpe"] > best_metrics.get("sharpe", -99))
            ):
                best_verdict = m["verdict"]
                best_rrr     = rrr
                best_metrics = m

        all_results[scanner_name] = {
            "best_rrr":  best_rrr,
            "verdict":   best_verdict,
            **best_metrics,
        }

        # Long vs Short breakdown for ema_cross_adx; exit distribution for all
        for rrr in [best_rrr]:
            all_trades_best: list[dict] = []
            for sym, df in data.items():
                all_trades_best.extend(_simulate_trades(df, scanner_fn, sym, regime, args.days, rrr, max_hold=mh))
            exit_dist = {}
            for t in all_trades_best:
                exit_dist[t["exit_why"]] = exit_dist.get(t["exit_why"], 0) + 1
            logger.info("    Exit distribution (RRR %.1f): %s", rrr, exit_dist)
            if scanner_name == "ema_cross_adx":
                for direction in ("LONG", "SHORT"):
                    dir_trades = [t for t in all_trades_best if t["direction"] == direction]
                    dm = _metrics(dir_trades)
                    logger.info(
                        "    %s only → trades=%d WR=%.1f%% P&L=₹%.0f",
                        direction, dm["trades"], dm["wr"], dm["pnl"],
                    )

    # ── Final summary ──────────────────────────────────────────────────────────
    logger.info("\n%s", "=" * 60)
    logger.info("FINAL VERDICTS")
    logger.info("=" * 60)

    tier1, tier2, override = [], [], []
    for name, res in all_results.items():
        v = res["verdict"]
        line = (f"  {name:<22} {v:<10} "
                f"WR={res.get('wr', 0):.1f}% "
                f"Sharpe={res.get('sharpe', 0):.3f} "
                f"trades={res.get('trades', 0)} "
                f"best_RRR={res.get('best_rrr', '?')}")
        logger.info(line)
        if v == "TIER_1":
            tier1.append(name)
        elif v == "TIER_2":
            tier2.append(name)
        else:
            override.append(name)

    logger.info("\nTIER_1  (enable immediately): %s", tier1 or "none")
    logger.info("TIER_2  (paper trade first):  %s", tier2 or "none")
    logger.info("OVERRIDE (disable):           %s", override or "none")

    if tier1:
        logger.info("\nSet env var to enable TIER_1 scanners:")
        logger.info("  FUTURES_VALIDATED_SCANNERS=%s", ",".join(tier1))
    if tier2:
        logger.info("\nPaper trade TIER_2 for 30 days then re-evaluate:")
        logger.info("  Candidates: %s", ", ".join(tier2))


if __name__ == "__main__":
    main()
