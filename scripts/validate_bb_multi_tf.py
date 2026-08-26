"""
BB Breakout Strategy — Multi-Timeframe Backtest (Dharanidharan PC Framework)

Validates the 5-layer confluence strategy across 6 timeframes:
  3m   — SKIP: yfinance does not support 3-minute interval (need Dhan intraday API)
  5m   — 55-day window, Nifty 50, EOD force-close
  15m  — 55-day window, Nifty 50, EOD force-close
  1h   — ~2-year window, Nifty 50
  1d   — 2021-2026, Nifty 500
  1wk  — 2021-2026, Nifty 500

4-condition bullish entry (all must fire simultaneously on bar close):
  1. SuperTrend(7,3) direction = +1
  2. RSI(14) > 70
  3. Close > R1 pivot (prev period's resistance broken)
  4. Close > Upper Bollinger Band(20,2)

Exit: ST direction flips | -5% hard stop | 20-bar time stop | EOD (intraday only)

Usage:
    python scripts/validate_bb_multi_tf.py                # all timeframes
    python scripts/validate_bb_multi_tf.py --tf 1d 1w     # specific TFs
    python scripts/validate_bb_multi_tf.py --tf 5m 15m 1h
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows cp1252 fix

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("bb_multi_tf")

# ── Strategy constants ────────────────────────────────────────────────────────
ST_PERIOD = 7
ST_MULT = 3.0
RSI_PERIOD = 14
BB_PERIOD = 20
BB_STD = 2.0
HARD_STOP = 0.05
MAX_HOLD_BARS = 20
MAX_CONC = 5
POSITION_INR = 100_000.0

# Delivery cost model (daily / weekly)
DELIVERY = {
    "brokerage": 20.0, "stt_sell": 0.001, "exchange": 0.0000345,
    "gst": 0.18, "stamp": 0.00015, "slippage": 0.0005,
}
# Intraday cost model (5m / 15m / 1h) — lower STT, higher slippage
INTRADAY = {
    "brokerage": 20.0, "stt_sell": 0.00025, "exchange": 0.0000345,
    "gst": 0.18, "stamp": 0.00003, "slippage": 0.001,
}

TIER1 = {"trades": 30, "cagr": 0.20, "sharpe": 0.8, "maxdd": 0.30, "winrate": 0.50}
TIER2 = {"trades": 15, "cagr": 0.10, "sharpe": 0.5, "maxdd": 0.40, "winrate": 0.40}

# ── Timeframe config ──────────────────────────────────────────────────────────
TF_CFG = {
    "3m":  None,  # not supported
    "5m":  {"yf_interval": "5m",  "yf_period": "55d",   "is_intraday": True,
             "eod_close": True,  "min_bars": 40, "costs": INTRADAY},
    "15m": {"yf_interval": "15m", "yf_period": "55d",   "is_intraday": True,
             "eod_close": True,  "min_bars": 40, "costs": INTRADAY},
    "1h":  {"yf_interval": "60m", "yf_period": "700d", "is_intraday": True,
             "eod_close": False, "min_bars": 50, "costs": INTRADAY},
    "1d":  {"yf_interval": "1d",  "yf_start": "2020-01-01", "is_intraday": False,
             "eod_close": False, "min_bars": 252, "costs": DELIVERY},
    "1w":  {"yf_interval": "1wk", "yf_start": "2020-01-01", "is_intraday": False,
             "eod_close": False, "min_bars": 52, "costs": DELIVERY},
}

# ── Universe ──────────────────────────────────────────────────────────────────
NIFTY50 = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJAJFINSV", "BAJFINANCE", "BEL", "BHARTIARTL",
    "BPCL", "BRITANNIA", "CIPLA", "COALINDIA", "DRREDDY",
    "EICHERMOT", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE",
    "HEROMOTOCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK", "INFY",
    "ITC", "JSWSTEEL", "KOTAKBANK", "LT", "M&M",
    "MARUTI", "NESTLEIND", "NTPC", "ONGC", "POWERGRID",
    "RELIANCE", "SBILIFE", "SBIN", "SHRIRAMFIN", "SUNPHARMA",
    "TATACONSUM", "TATAMOTORS", "TATASTEEL", "TCS", "TECHM",
    "TITAN", "TRENT", "ULTRACEMCO", "WIPRO", "ZOMATO",
]


def _load_symbols_n500() -> list[str]:
    p = Path("data/nifty500.json")
    if not p.exists():
        p = Path(__file__).parent.parent / "data" / "nifty500.json"
    with open(p) as f:
        syms = json.load(f)["symbols"]
    return [s for s in syms if "DUMMY" not in s.upper()]


# ── Data loading ─────────────────────────────────────────────────────────────

def _download_intraday(
    symbols: list[str], cfg: dict
) -> dict[str, list[dict]]:
    """
    Download intraday bars for a list of symbols.
    Returns {sym: [{"date": date, "bar_idx": int, "o": float, "h": float,
                     "l": float, "c": float, "is_last_of_day": bool}]}
    """
    import pandas as pd
    import yfinance as yf

    result: dict[str, list[dict]] = {}
    yf_kw = {"interval": cfg["yf_interval"], "auto_adjust": True,
              "progress": False, "threads": False}
    if "yf_period" in cfg:
        yf_kw["period"] = cfg["yf_period"]
    else:
        yf_kw["start"] = cfg["yf_start"]

    for sym in symbols:
        try:
            raw = yf.download(sym + ".NS", **yf_kw)
            if raw is None or raw.empty:
                continue
            # Handle MultiIndex columns (single ticker may still have MultiIndex)
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.droplevel(1)

            bars: list[dict] = []
            for ts, row in raw.iterrows():
                try:
                    # ts can be tz-aware; extract date
                    if hasattr(ts, "date"):
                        d = ts.date()
                    else:
                        d = pd.Timestamp(ts).date()
                    bars.append({
                        "date": d,
                        "ts": ts,
                        "o": float(row["Open"]),
                        "h": float(row["High"]),
                        "l": float(row["Low"]),
                        "c": float(row["Close"]),
                        "is_last_of_day": False,
                    })
                except Exception:
                    continue

            if len(bars) < cfg["min_bars"]:
                continue

            # Mark last bar of each day
            for i in range(len(bars) - 1):
                if bars[i]["date"] != bars[i + 1]["date"]:
                    bars[i]["is_last_of_day"] = True
            bars[-1]["is_last_of_day"] = True

            result[sym] = bars
        except Exception as e:
            logger.debug("Download failed for %s: %s", sym, e)

    logger.info("[%s] Loaded %d / %d symbols",
                cfg["yf_interval"], len(result), len(symbols))
    return result


def _download_daily(symbols: list[str], cfg: dict) -> dict[str, list[dict]]:
    """Download daily or weekly bars. Returns {sym: [{date, o, h, l, c}]}."""
    import pandas as pd
    import yfinance as yf

    result: dict[str, list[dict]] = {}
    interval = cfg["yf_interval"]
    start = cfg.get("yf_start", "2020-01-01")

    for i in range(0, len(symbols), 50):
        chunk = symbols[i : i + 50]
        yf_tickers = [s + ".NS" for s in chunk]
        try:
            raw = yf.download(
                yf_tickers, interval=interval, start=start,
                auto_adjust=True, progress=False, threads=True,
            )
            if raw is None or raw.empty:
                continue
            for sym, yf_sym in zip(chunk, yf_tickers):
                try:
                    if isinstance(raw.columns, pd.MultiIndex):
                        c = raw["Close"][yf_sym].dropna()
                        h = raw["High"][yf_sym].reindex(c.index).fillna(c)
                        lo = raw["Low"][yf_sym].reindex(c.index).fillna(c)
                        o = raw["Open"][yf_sym].reindex(c.index).fillna(c)
                    else:
                        c = raw["Close"].dropna()
                        h = raw["High"].reindex(c.index).fillna(c)
                        lo = raw["Low"].reindex(c.index).fillna(c)
                        o = raw["Open"].reindex(c.index).fillna(c)
                    if len(c) < cfg["min_bars"]:
                        continue
                    bars: list[dict] = []
                    for ts in c.index:
                        d = ts.date() if hasattr(ts, "date") else ts
                        bars.append({
                            "date": d,
                            "o": float(o.get(ts, c[ts])),
                            "h": float(h.get(ts, c[ts])),
                            "l": float(lo.get(ts, c[ts])),
                            "c": float(c[ts]),
                        })
                    result[sym] = bars
                except Exception:
                    pass
        except Exception as e:
            logger.warning("Batch download %d: %s", i, e)

    logger.info("[%s] Loaded %d / %d symbols",
                interval, len(result), len(symbols))
    return result


# ── Indicators ────────────────────────────────────────────────────────────────

def _add_pivots_intraday(bars: list[dict]) -> list[dict]:
    """
    For intraday bars: compute daily H/L/C from bars,
    then set R1/S1 on each bar based on PREVIOUS day.
    """
    # Build daily OHLC
    daily: dict[date, dict] = {}
    for b in bars:
        d = b["date"]
        if d not in daily:
            daily[d] = {"h": b["h"], "l": b["l"], "c": b["c"]}
        else:
            daily[d]["h"] = max(daily[d]["h"], b["h"])
            daily[d]["l"] = min(daily[d]["l"], b["l"])
            daily[d]["c"] = b["c"]

    sorted_days = sorted(daily.keys())
    day_r1: dict[date, float] = {}
    day_s1: dict[date, float] = {}
    for i, d in enumerate(sorted_days):
        if i == 0:
            day_r1[d] = float("nan")
            day_s1[d] = float("nan")
        else:
            prev = daily[sorted_days[i - 1]]
            pivot = (prev["h"] + prev["l"] + prev["c"]) / 3
            day_r1[d] = 2 * pivot - prev["l"]
            day_s1[d] = 2 * pivot - prev["h"]

    for b in bars:
        b["r1"] = day_r1.get(b["date"], float("nan"))
        b["s1"] = day_s1.get(b["date"], float("nan"))
    return bars


def _compute_indicators(bars: list[dict], is_intraday: bool) -> list[dict]:
    """Compute RSI, BB, SuperTrend, and Pivots for a list of OHLCV bars."""
    n = len(bars)
    closes = [b["c"] for b in bars]
    highs = [b["h"] for b in bars]
    lows = [b["l"] for b in bars]

    # RSI (Wilder's)
    rsi = [50.0] * n
    if n > RSI_PERIOD:
        gains = [max(closes[i] - closes[i - 1], 0) for i in range(1, n)]
        losses = [max(closes[i - 1] - closes[i], 0) for i in range(1, n)]
        alpha = 1.0 / RSI_PERIOD
        ag = sum(gains[:RSI_PERIOD]) / RSI_PERIOD
        al = sum(losses[:RSI_PERIOD]) / RSI_PERIOD
        rsi[RSI_PERIOD] = 100 - 100 / (1 + ag / al) if al > 0 else 100.0
        for i in range(RSI_PERIOD, len(gains)):
            ag = (1 - alpha) * ag + alpha * gains[i]
            al = (1 - alpha) * al + alpha * losses[i]
            rsi[i + 1] = 100 - 100 / (1 + ag / al) if al > 0 else 100.0

    # Bollinger Bands
    upper_bb = [float("nan")] * n
    lower_bb = [float("nan")] * n
    for i in range(BB_PERIOD - 1, n):
        w = closes[i - BB_PERIOD + 1 : i + 1]
        mean = sum(w) / BB_PERIOD
        std = math.sqrt(sum((x - mean) ** 2 for x in w) / BB_PERIOD)
        upper_bb[i] = mean + BB_STD * std
        lower_bb[i] = mean - BB_STD * std

    # SuperTrend
    st_dir = [0] * n
    st_line = [0.0] * n
    for i in range(1, n):
        if i < ST_PERIOD:
            continue
        atr = sum(
            max(highs[j] - lows[j],
                abs(highs[j] - closes[j - 1]),
                abs(lows[j] - closes[j - 1]))
            for j in range(i - ST_PERIOD + 1, i + 1)
        ) / ST_PERIOD
        hl2 = (highs[i] + lows[i]) / 2
        upper = hl2 + ST_MULT * atr
        lower = hl2 - ST_MULT * atr
        prev_line = st_line[i - 1] if st_line[i - 1] else upper
        if closes[i] > prev_line:
            st_line[i] = max(lower, st_line[i - 1]) if st_dir[i - 1] == 1 else lower
            st_dir[i] = 1
        else:
            st_line[i] = min(upper, st_line[i - 1]) if st_dir[i - 1] == -1 else upper
            st_dir[i] = -1

    # Pivots
    if is_intraday:
        # Use daily pivots pre-added by _add_pivots_intraday
        r1_vals = [b.get("r1", float("nan")) for b in bars]
        s1_vals = [b.get("s1", float("nan")) for b in bars]
    else:
        # Pivot from previous bar (prev day for 1d, prev week for 1w)
        r1_vals = [float("nan")] * n
        s1_vals = [float("nan")] * n
        for i in range(1, n):
            ph, pl, pc = highs[i - 1], lows[i - 1], closes[i - 1]
            pivot = (ph + pl + pc) / 3
            r1_vals[i] = 2 * pivot - pl
            s1_vals[i] = 2 * pivot - ph

    result = [dict(b) for b in bars]
    for i, bar in enumerate(result):
        bar["rsi"] = rsi[i]
        bar["upper_bb"] = upper_bb[i]
        bar["lower_bb"] = lower_bb[i]
        bar["st_dir"] = st_dir[i]
        bar["r1"] = r1_vals[i]
        bar["s1"] = s1_vals[i]
    return result


# ── Cost model ────────────────────────────────────────────────────────────────

def _cost(pos: float, costs: dict) -> float:
    buy = pos * (1 + costs["slippage"])
    sell = pos * (1 - costs["slippage"])
    c = costs["brokerage"] * 2 + sell * costs["stt_sell"]
    c += (buy + sell) * costs["exchange"]
    c += (costs["brokerage"] * 2 + (buy + sell) * costs["exchange"]) * costs["gst"]
    c += buy * costs["stamp"]
    return c


# ── Backtest ──────────────────────────────────────────────────────────────────

def _backtest(
    sym_bars: dict[str, list[dict]],
    cfg: dict,
    start_date: date | None = None,
) -> list[dict]:
    """Run backtest for one timeframe. Returns list of closed trades."""
    costs = cfg["costs"]
    eod_close = cfg.get("eod_close", False)

    # Pre-compute indicators
    indicators: dict[str, list[dict]] = {}
    for sym, bars in sym_bars.items():
        if cfg["is_intraday"]:
            bars = _add_pivots_intraday(bars)
        ind = _compute_indicators(bars, cfg["is_intraday"])
        indicators[sym] = ind

    # Build flat bar sequence for simulation
    # Each entry: (bar_index_for_sym, sym, bar_dict)
    # Sort by date, then time (ts) if available
    all_bar_keys: list[tuple] = []
    for sym, ind in indicators.items():
        for i, bar in enumerate(ind):
            sort_key = bar.get("ts", bar["date"])
            all_bar_keys.append((sort_key, sym, i))
    all_bar_keys.sort(key=lambda x: x[0])

    open_positions: list[dict] = []
    closed_trades: list[dict] = []


    for _, sym, bar_idx in all_bar_keys:
        bar = indicators[sym][bar_idx]
        bar_date = bar["date"]

        if start_date and bar_date < start_date:
            continue

        # ── Check exits ────────────────────────────────────────────────────
        still_open: list[dict] = []
        for pos in open_positions:
            if pos["sym"] != sym:
                still_open.append(pos)
                continue
            close = bar["c"]
            hard_stop_px = pos["entry_px"] * (1 - HARD_STOP)
            bars_held = pos["bars_held"] + 1
            exit_reason = None
            exit_px = close

            if close <= hard_stop_px:
                exit_reason, exit_px = "hard_stop", hard_stop_px
            elif bar["st_dir"] == -1:
                exit_reason = "st_flip"
            elif bars_held >= MAX_HOLD_BARS:
                exit_reason = "time"
            elif eod_close and bar.get("is_last_of_day"):
                exit_reason = "eod"

            if exit_reason:
                pnl = ((exit_px - pos["entry_px"]) / pos["entry_px"]
                       * POSITION_INR - _cost(POSITION_INR, costs))
                closed_trades.append({
                    "sym": sym,
                    "entry_date": pos["entry_date"],
                    "exit_date": bar_date,
                    "entry_px": round(pos["entry_px"], 2),
                    "exit_px": round(exit_px, 2),
                    "bars_held": bars_held,
                    "entry_rsi": round(pos["entry_rsi"], 1),
                    "net_pnl": round(pnl, 2),
                    "ret_pct": round(pnl / POSITION_INR * 100, 2),
                    "exit_reason": exit_reason,
                })
            else:
                pos["bars_held"] = bars_held
                still_open.append(pos)

        open_positions = still_open

        # ── Check entry ────────────────────────────────────────────────────
        if len(open_positions) >= MAX_CONC:
            continue
        if any(p["sym"] == sym for p in open_positions):
            continue
        if bar_idx < BB_PERIOD + ST_PERIOD:
            continue

        r1 = bar.get("r1", float("nan"))
        ub = bar.get("upper_bb", float("nan"))
        if (bar["st_dir"] == 1
                and bar["rsi"] > 70
                and not math.isnan(r1) and bar["c"] > r1
                and not math.isnan(ub) and bar["c"] > ub):
            open_positions.append({
                "sym": sym,
                "entry_date": bar_date,
                "entry_px": bar["c"],
                "entry_rsi": bar["rsi"],
                "bars_held": 0,
            })

    # Force-close any remaining positions at last available price
    for pos in open_positions:
        sym = pos["sym"]
        ind = indicators.get(sym, [])
        last_bar = ind[-1] if ind else None
        last_close = last_bar["c"] if last_bar else pos["entry_px"]
        pnl = ((last_close - pos["entry_px"]) / pos["entry_px"]
               * POSITION_INR - _cost(POSITION_INR, costs))
        closed_trades.append({
            "sym": sym,
            "entry_date": pos["entry_date"],
            "exit_date": last_bar["date"] if last_bar else pos["entry_date"],
            "entry_px": round(pos["entry_px"], 2),
            "exit_px": round(last_close, 2),
            "bars_held": pos["bars_held"],
            "entry_rsi": round(pos["entry_rsi"], 1),
            "net_pnl": round(pnl, 2),
            "ret_pct": round(pnl / POSITION_INR * 100, 2),
            "exit_reason": "end",
        })

    return closed_trades


# ── Metrics + verdict ─────────────────────────────────────────────────────────

def _metrics(trades: list[dict], years: float) -> dict:
    if not trades:
        return {}
    returns = [t["ret_pct"] / 100 for t in trades]
    n = len(trades)
    wins = sum(1 for r in returns if r > 0)
    total = sum(returns)
    cagr = (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else -1.0
    mean_r = total / n
    std_r = math.sqrt(sum((r - mean_r) ** 2 for r in returns) / max(n - 1, 1))
    avg_hold = sum(t["bars_held"] for t in trades) / n
    sharpe = (mean_r / std_r) * math.sqrt(252 / max(avg_hold, 1)) if std_r > 0 else 0.0
    ref = float(MAX_CONC * POSITION_INR)
    cum = peak = max_dd = 0.0
    for t in sorted(trades, key=lambda x: x["exit_date"]):
        cum += t["net_pnl"]
        peak = max(peak, cum)
        max_dd = max(max_dd, (peak - cum) / ref)
    reasons: dict[str, int] = {}
    for t in trades:
        reasons[t["exit_reason"]] = reasons.get(t["exit_reason"], 0) + 1
    return {
        "n_trades": n, "win_rate": wins / n, "cagr": cagr,
        "sharpe": sharpe, "max_dd": max_dd,
        "total_pnl": sum(t["net_pnl"] for t in trades),
        "avg_hold": avg_hold, "avg_ret_pct": mean_r * 100,
        "exit_reasons": reasons,
    }


def _verdict(m: dict) -> str:
    if not m:
        return "OVERRIDE"
    if (m["n_trades"] >= TIER1["trades"] and m["cagr"] >= TIER1["cagr"]
            and m["sharpe"] >= TIER1["sharpe"] and m["max_dd"] <= TIER1["maxdd"]
            and m["win_rate"] >= TIER1["winrate"]):
        return "TIER_1"
    if (m["n_trades"] >= TIER2["trades"] and m["cagr"] >= TIER2["cagr"]
            and m["sharpe"] >= TIER2["sharpe"] and m["max_dd"] <= TIER2["maxdd"]
            and m["win_rate"] >= TIER2["winrate"]):
        return "TIER_2"
    return "OVERRIDE"


def _print_tf_result(tf: str, m: dict, trades: list[dict], cfg: dict | None) -> None:
    sep = "=" * 70
    print()
    print(sep)
    is_intraday = cfg and cfg.get("is_intraday")
    universe = "Nifty 50" if is_intraday else "Nifty 500"
    window = cfg.get("yf_period") or f"from {cfg.get('yf_start', '?')}" if cfg else "N/A"
    hold_note = f"{MAX_HOLD_BARS} bars {'+ EOD force-close' if cfg and cfg.get('eod_close') else ''}"
    print(f"TIMEFRAME: {tf:>4}  |  Universe: {universe}  |  Window: {window}")
    print(f"ST({ST_PERIOD},{ST_MULT}) + RSI>70 + R1 pivot + Upper BB(20,2)  |  Hold: {hold_note}")
    print(sep)

    if not m:
        print("  No trades generated — conditions too strict for this window/universe.")
        print("  VERDICT: OVERRIDE")
        print(sep)
        return

    v = _verdict(m)
    print(f"  Trades        : {m['n_trades']}")
    print(f"  Win rate      : {m['win_rate']*100:.1f}%")
    print(f"  Avg hold      : {m['avg_hold']:.1f} bars")
    print(f"  Avg return    : {m['avg_ret_pct']:+.2f}%")
    print(f"  Total P&L     : ₹{m['total_pnl']:,.0f}")
    print(f"  CAGR          : {m['cagr']*100:+.1f}%")
    print(f"  Sharpe        : {m['sharpe']:.2f}")
    print(f"  Max drawdown  : {m['max_dd']*100:.1f}%")
    exits = ", ".join(f"{k}:{v}" for k, v in sorted(m["exit_reasons"].items()))
    print(f"  Exits         : {exits}")
    print()
    print(f"  VERDICT: {v}")
    if trades:
        top = sorted(trades, key=lambda t: t["ret_pct"], reverse=True)[:5]
        print()
        print("  Top 5 trades:")
        for t in top:
            print(f"    {t['sym']:<14} {str(t['entry_date'])[:10]}  "
                  f"RSI={t['entry_rsi']:.0f}  {t['ret_pct']:+.2f}%  [{t['exit_reason']}]")
    print(sep)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="BB Breakout multi-timeframe backtest"
    )
    parser.add_argument(
        "--tf", nargs="+",
        choices=["3m", "5m", "15m", "1h", "1d", "1w"],
        default=["3m", "5m", "15m", "1h", "1d", "1w"],
        help="Timeframes to test (default: all)",
    )
    args = parser.parse_args()

    summary_rows: list[dict] = []
    n500 = _load_symbols_n500()

    for tf in args.tf:
        print(f"\n{'─'*70}")
        print(f"PROCESSING: {tf}")
        print(f"{'─'*70}")

        if TF_CFG[tf] is None:
            print(f"\n  {tf} — SKIP: yfinance does not support 3-minute interval.")
            print("  To backtest 3m, use Dhan Historical Intraday API:")
            print("    GET /charts/historical?security_id=<id>&exchange_segment=NSE_EQ")
            print("    &instrument_type=EQUITY&interval=3&from_date=<date>&to_date=<date>")
            summary_rows.append({"tf": tf, "verdict": "SKIP (no data source)",
                                  "trades": "-", "cagr": "-", "sharpe": "-",
                                  "maxdd": "-", "winrate": "-"})
            continue

        cfg = TF_CFG[tf]
        is_intraday = cfg["is_intraday"]
        symbols = NIFTY50 if is_intraday else n500

        logger.info("[%s] Downloading %d symbols...", tf, len(symbols))
        if is_intraday:
            sym_bars = _download_intraday(symbols, cfg)
        else:
            sym_bars = _download_daily(symbols, cfg)

        if len(sym_bars) < 3:
            logger.warning("[%s] Too few symbols loaded (%d)", tf, len(sym_bars))
            _print_tf_result(tf, {}, [], cfg)
            summary_rows.append({"tf": tf, "verdict": "OVERRIDE (no data)",
                                  "trades": 0, "cagr": "N/A", "sharpe": "N/A",
                                  "maxdd": "N/A", "winrate": "N/A"})
            continue

        # Determine backtest start date
        if tf in ("5m", "15m"):
            # Use all available data (only ~55 days)
            start_date = None
        elif tf == "1h":
            # yf_period="700d" → data starts ~700 days ago; use None to backtest all of it
            start_date = None
        elif tf in ("1d", "1w"):
            start_date = date(2021, 1, 1)
        else:
            start_date = None

        trades = _backtest(sym_bars, cfg, start_date=start_date)
        logger.info("[%s] %d trades generated", tf, len(trades))

        # Compute years for CAGR
        if start_date:
            years = (date.today() - start_date).days / 365.25
        else:
            # Use first to last trade date
            all_dates = [t["exit_date"] for t in trades]
            if all_dates:
                years = (max(all_dates) - min(all_dates)).days / 365.25
            else:
                years = 1.0
        years = max(years, 0.1)

        m = _metrics(trades, years)
        v = _verdict(m)
        _print_tf_result(tf, m, trades, cfg)

        summary_rows.append({
            "tf": tf,
            "verdict": v,
            "trades": m.get("n_trades", 0),
            "cagr": f"{m['cagr']*100:+.1f}%" if m else "N/A",
            "sharpe": f"{m['sharpe']:.2f}" if m else "N/A",
            "maxdd": f"{m['max_dd']*100:.1f}%" if m else "N/A",
            "winrate": f"{m['win_rate']*100:.1f}%" if m else "N/A",
        })

        # Save per-TF report
        if trades:
            out = Path("reports") / f"bb_breakout_{tf}_{date.today()}.md"
            out.parent.mkdir(exist_ok=True)
            lines = [
                f"# BB Breakout {tf} — {date.today()}",
                f"Universe: {'Nifty 50' if is_intraday else 'Nifty 500'}",
                f"Verdict: **{v}**", "",
                "| Symbol | Entry | Exit | RSI | Bars | Return | Reason |",
                "|---|---|---|---|---|---|---|",
            ]
            for t in sorted(trades, key=lambda x: x["entry_date"]):
                lines.append(
                    f"| {t['sym']} | {str(t['entry_date'])[:10]} | "
                    f"{str(t['exit_date'])[:10]} | {t['entry_rsi']:.0f} | "
                    f"{t['bars_held']} | {t['ret_pct']:+.2f}% | {t['exit_reason']} |"
                )
            out.write_text("\n".join(lines), encoding='utf-8')
            logger.info("[%s] Report saved: %s", tf, out)

    # ── Summary comparison table ────────────────────────────────────────────
    print()
    print("=" * 70)
    print("MULTI-TIMEFRAME COMPARISON SUMMARY")
    print("=" * 70)
    print(f"{'TF':<6} {'Trades':>7} {'CAGR':>10} {'Sharpe':>8} "
          f"{'MaxDD':>8} {'WinRate':>9}  Verdict")
    print("-" * 70)
    for r in summary_rows:
        print(f"{r['tf']:<6} {r['trades']!s:>7} {r['cagr']!s:>10} "
              f"{r['sharpe']!s:>8} {r['maxdd']!s:>8} "
              f"{r['winrate']!s:>9}  {r['verdict']}")
    print("=" * 70)
    print()
    print("NOTES:")
    print("  • 3m  — Requires Dhan intraday API (not in yfinance)")
    print("  • 5m/15m — Only ~55 days of data; sample size too small for statistical significance")
    print("  • 1h  — ~2 years of data; moderate confidence")
    print("  • 1d/1w — 4+ years; highest statistical confidence")
    print()


if __name__ == "__main__":
    main()
