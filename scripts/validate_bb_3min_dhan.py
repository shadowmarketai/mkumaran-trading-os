"""
BB Breakout Strategy — 3-Minute Backtest via Dhan Historical API

Data source: Dhan intraday_minute_data (1-minute) resampled to 3-minute bars.
Max window: 90 trading days (Dhan 1-minute data limit).
Universe: Nifty 50 — liquid intraday-tradeable stocks only.

Same 4-condition bullish entry on each 3-min bar close:
  1. SuperTrend(7,3) direction = +1
  2. RSI(14) > 70
  3. Close > R1 pivot (previous trading day's resistance)
  4. Close > Upper Bollinger Band(20, 2)

Exit: SuperTrend flips to -1 | -5% hard stop | 20-bar time stop | EOD force-close

DATA LIMITATION WARNING:
  90 days × ~125 bars/day × 50 stocks = ~562,500 bars.
  Expected signals: 0–20 total. Results are informational only.
  Statistical significance requires 200+ trades minimum.

Usage:
    python scripts/validate_bb_3min_dhan.py
    python scripts/validate_bb_3min_dhan.py --days 90
"""
from __future__ import annotations

import logging
import math
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("bb_3min")

# ── Strategy constants (same as daily) ───────────────────────────────────────
ST_PERIOD    = 7
ST_MULT      = 3.0
RSI_PERIOD   = 14
BB_PERIOD    = 20
BB_STD       = 2.0
HARD_STOP    = 0.05        # -5% hard stop
MAX_HOLD     = 20          # 20 bars = 60 minutes (intraday)
MAX_CONC     = 5
POSITION_INR = 100_000.0

# Intraday cost model (lower STT, higher slippage)
BROKERAGE  = 20.0
STT_SELL   = 0.00025       # 0.025% sell side intraday
EXCHANGE   = 0.0000345
GST        = 0.18
STAMP      = 0.00003
SLIPPAGE   = 0.001         # 0.1% each side

TIER1 = {"trades": 30,  "cagr": 0.20, "sharpe": 0.8, "maxdd": 0.30, "winrate": 0.50}
TIER2 = {"trades": 15,  "cagr": 0.10, "sharpe": 0.5, "maxdd": 0.40, "winrate": 0.40}

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


# ── Data loading ─────────────────────────────────────────────────────────────

def _load_dhan_3min(symbols: list[str], days: int) -> dict[str, list[dict]]:
    """
    Fetch 1-minute data from Dhan for each symbol, resample to 3-minute bars.
    Returns {sym: [{date, ts, o, h, l, c, is_last_of_day}]}
    """
    import pandas as pd
    from mcp_server.data_provider import DhanSource

    dhan = DhanSource()
    if not dhan.login():
        logger.error("Dhan login failed — check DHAN_CLIENT_ID + DHAN_ACCESS_TOKEN env vars")
        return {}

    logger.info("Dhan logged in. Fetching 1-min data for %d symbols (last %d days)...",
                len(symbols), days)

    result: dict[str, list[dict]] = {}
    for sym in symbols:
        try:
            df1m = dhan.get_historical(sym, interval="1minute", days=days, exchange="NSE")
            if df1m is None or df1m.empty:
                logger.debug("No 1-min data for %s", sym)
                continue

            df1m = df1m.copy()
            df1m["date_col"] = pd.to_datetime(df1m["date"])
            df1m = df1m.set_index("date_col").sort_index()

            # Resample 1-min → 3-min
            df3m = df1m[["open", "high", "low", "close"]].resample("3min").agg({
                "open": "first", "high": "max", "low": "min", "close": "last",
            }).dropna(subset=["close"])

            if len(df3m) < BB_PERIOD + ST_PERIOD + 5:
                continue

            bars: list[dict] = []
            for ts, row in df3m.iterrows():
                bars.append({
                    "date": ts.date(),
                    "ts": ts,
                    "o": float(row["open"]),
                    "h": float(row["high"]),
                    "l": float(row["low"]),
                    "c": float(row["close"]),
                    "is_last_of_day": False,
                })

            # Mark last bar of each trading day
            for i in range(len(bars) - 1):
                if bars[i]["date"] != bars[i + 1]["date"]:
                    bars[i]["is_last_of_day"] = True
            if bars:
                bars[-1]["is_last_of_day"] = True

            result[sym] = bars
            logger.debug("Loaded %s: %d 3-min bars", sym, len(bars))

        except Exception as e:
            logger.warning("Failed %s: %s", sym, e)

    logger.info("Loaded %d / %d symbols with 3-min data", len(result), len(symbols))
    return result


# ── Intraday pivot (prev day H/L/C) ──────────────────────────────────────────

def _add_pivots(bars: list[dict]) -> list[dict]:
    from datetime import date as date_type
    daily: dict[date_type, dict] = {}
    for b in bars:
        d = b["date"]
        if d not in daily:
            daily[d] = {"h": b["h"], "l": b["l"], "c": b["c"]}
        else:
            daily[d]["h"] = max(daily[d]["h"], b["h"])
            daily[d]["l"] = min(daily[d]["l"], b["l"])
            daily[d]["c"] = b["c"]

    sorted_days = sorted(daily.keys())
    day_r1: dict = {}
    day_s1: dict = {}
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


# ── Indicators ────────────────────────────────────────────────────────────────

def _compute_indicators(bars: list[dict]) -> list[dict]:
    n = len(bars)
    closes = [b["c"] for b in bars]
    highs  = [b["h"] for b in bars]
    lows   = [b["l"] for b in bars]

    # RSI (Wilder's)
    rsi = [50.0] * n
    if n > RSI_PERIOD:
        gains  = [max(closes[i] - closes[i-1], 0) for i in range(1, n)]
        losses = [max(closes[i-1] - closes[i], 0) for i in range(1, n)]
        alpha  = 1.0 / RSI_PERIOD
        ag     = sum(gains[:RSI_PERIOD]) / RSI_PERIOD
        al     = sum(losses[:RSI_PERIOD]) / RSI_PERIOD
        rsi[RSI_PERIOD] = 100 - 100 / (1 + ag / al) if al > 0 else 100.0
        for i in range(RSI_PERIOD, len(gains)):
            ag = (1 - alpha) * ag + alpha * gains[i]
            al = (1 - alpha) * al + alpha * losses[i]
            rsi[i + 1] = 100 - 100 / (1 + ag / al) if al > 0 else 100.0

    # Bollinger Bands
    upper_bb = [float("nan")] * n
    for i in range(BB_PERIOD - 1, n):
        w    = closes[i - BB_PERIOD + 1 : i + 1]
        mean = sum(w) / BB_PERIOD
        std  = math.sqrt(sum((x - mean) ** 2 for x in w) / BB_PERIOD)
        upper_bb[i] = mean + BB_STD * std

    # SuperTrend
    st_dir  = [0] * n
    st_line = [0.0] * n
    for i in range(1, n):
        if i < ST_PERIOD:
            continue
        atr = sum(
            max(highs[j] - lows[j],
                abs(highs[j] - closes[j-1]),
                abs(lows[j]  - closes[j-1]))
            for j in range(i - ST_PERIOD + 1, i + 1)
        ) / ST_PERIOD
        hl2   = (highs[i] + lows[i]) / 2
        upper = hl2 + ST_MULT * atr
        lower = hl2 - ST_MULT * atr
        prev  = st_line[i-1] if st_line[i-1] else upper
        if closes[i] > prev:
            st_line[i] = max(lower, st_line[i-1]) if st_dir[i-1] == 1 else lower
            st_dir[i]  = 1
        else:
            st_line[i] = min(upper, st_line[i-1]) if st_dir[i-1] == -1 else upper
            st_dir[i]  = -1

    result = [dict(b) for b in bars]
    for i, bar in enumerate(result):
        bar["rsi"]      = rsi[i]
        bar["upper_bb"] = upper_bb[i]
        bar["st_dir"]   = st_dir[i]
    return result


# ── Cost model ────────────────────────────────────────────────────────────────

def _cost(pos: float) -> float:
    buy  = pos * (1 + SLIPPAGE)
    sell = pos * (1 - SLIPPAGE)
    c    = BROKERAGE * 2 + sell * STT_SELL
    c   += (buy + sell) * EXCHANGE
    c   += (BROKERAGE * 2 + (buy + sell) * EXCHANGE) * GST
    c   += buy * STAMP
    return c


# ── Backtest ──────────────────────────────────────────────────────────────────

def _backtest(sym_bars: dict[str, list[dict]]) -> list[dict]:
    indicators: dict[str, list[dict]] = {}
    for sym, bars in sym_bars.items():
        bars = _add_pivots(bars)
        indicators[sym] = _compute_indicators(bars)

    all_keys: list[tuple] = []
    for sym, ind in indicators.items():
        for i, bar in enumerate(ind):
            all_keys.append((bar["ts"], sym, i))
    all_keys.sort(key=lambda x: x[0])

    open_positions: list[dict] = []
    closed_trades:  list[dict] = []

    for _, sym, bar_idx in all_keys:
        bar = indicators[sym][bar_idx]

        # ── Exits ──────────────────────────────────────────────────────────
        still_open: list[dict] = []
        for pos in open_positions:
            if pos["sym"] != sym:
                still_open.append(pos)
                continue
            close        = bar["c"]
            hard_stop_px = pos["entry_px"] * (1 - HARD_STOP)
            bars_held    = pos["bars_held"] + 1
            exit_reason  = None
            exit_px      = close

            if close <= hard_stop_px:
                exit_reason, exit_px = "hard_stop", hard_stop_px
            elif bar["st_dir"] == -1:
                exit_reason = "st_flip"
            elif bars_held >= MAX_HOLD:
                exit_reason = "time"
            elif bar.get("is_last_of_day"):
                exit_reason = "eod"

            if exit_reason:
                pnl = ((exit_px - pos["entry_px"]) / pos["entry_px"]
                       * POSITION_INR - _cost(POSITION_INR))
                closed_trades.append({
                    "sym": sym, "entry_date": pos["entry_date"],
                    "exit_date": bar["date"],
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

        # ── Entries ─────────────────────────────────────────────────────────
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
                "sym": sym, "entry_date": bar["date"],
                "entry_px": bar["c"], "entry_rsi": bar["rsi"], "bars_held": 0,
            })

    # Force-close remaining
    for pos in open_positions:
        ind  = indicators.get(pos["sym"], [])
        last = ind[-1] if ind else None
        px   = last["c"] if last else pos["entry_px"]
        pnl  = (px - pos["entry_px"]) / pos["entry_px"] * POSITION_INR - _cost(POSITION_INR)
        closed_trades.append({
            "sym": pos["sym"], "entry_date": pos["entry_date"],
            "exit_date": last["date"] if last else pos["entry_date"],
            "entry_px": round(pos["entry_px"], 2), "exit_px": round(px, 2),
            "bars_held": pos["bars_held"], "entry_rsi": round(pos["entry_rsi"], 1),
            "net_pnl": round(pnl, 2),
            "ret_pct": round(pnl / POSITION_INR * 100, 2),
            "exit_reason": "end",
        })

    return closed_trades


# ── Metrics + verdict ─────────────────────────────────────────────────────────

def _metrics(trades: list[dict], years: float) -> dict:
    if not trades:
        return {}
    returns  = [t["ret_pct"] / 100 for t in trades]
    n        = len(trades)
    wins     = sum(1 for r in returns if r > 0)
    total    = sum(returns)
    cagr     = (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else -1.0
    mean_r   = total / n
    std_r    = math.sqrt(sum((r - mean_r) ** 2 for r in returns) / max(n - 1, 1))
    avg_hold = sum(t["bars_held"] for t in trades) / n
    # Annualise using intraday bars: ~125 3-min bars/day × 250 days = 31,250
    sharpe   = (mean_r / std_r) * math.sqrt(31_250 / max(avg_hold, 1)) if std_r > 0 else 0.0
    ref      = float(MAX_CONC * POSITION_INR)
    cum = peak = max_dd = 0.0
    for t in sorted(trades, key=lambda x: x["exit_date"]):
        cum  += t["net_pnl"]
        peak  = max(peak, cum)
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


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="BB Breakout 3-min backtest via Dhan API")
    parser.add_argument("--days", type=int, default=90,
                        help="Days of 1-min history to fetch from Dhan (max ~90)")
    args = parser.parse_args()

    sep = "=" * 68
    print()
    print(sep)
    print("BB BREAKOUT — 3-MINUTE BACKTEST (Dhan 1-min → resample)")
    print(f"Universe: Nifty 50 | Window: last {args.days} days")
    print("ST(7,3) + RSI>70 + R1 pivot + Upper BB(20,2) | EOD force-close")
    print(sep)
    print("NOTE: 90-day window → expected 0-30 signals. Informational only.")
    print()

    sym_bars = _load_dhan_3min(NIFTY50, args.days)
    if len(sym_bars) < 3:
        print("ERROR: Too few symbols loaded. Check Dhan credentials.")
        print("  Required env vars: DHAN_CLIENT_ID + DHAN_ACCESS_TOKEN")
        print("  Or: DHAN_TOTP_KEY + DHAN_PIN for auto-refresh")
        return

    trades = _backtest(sym_bars)
    logger.info("%d trades generated", len(trades))

    all_dates = [t["exit_date"] for t in trades] + [t["entry_date"] for t in trades]
    years = (max(all_dates) - min(all_dates)).days / 365.25 if all_dates else 1.0
    years = max(years, 0.1)

    m = _metrics(trades, years)
    v = _verdict(m)

    print(sep)
    if not m:
        print("No trades — conditions too strict for this universe/window.")
        print("VERDICT: OVERRIDE")
        print(sep)
        return

    print(f"Trades        : {m['n_trades']}")
    print(f"Win rate      : {m['win_rate']*100:.1f}%")
    print(f"Avg hold      : {m['avg_hold']:.1f} bars ({m['avg_hold']*3:.0f} min)")
    print(f"Avg return    : {m['avg_ret_pct']:+.2f}%")
    print(f"Total P&L     : ₹{m['total_pnl']:,.0f}")
    print(f"CAGR          : {m['cagr']*100:+.1f}%")
    print(f"Sharpe        : {m['sharpe']:.2f}")
    print(f"Max drawdown  : {m['max_dd']*100:.1f}%")
    exits = ", ".join(f"{k}:{c}" for k, c in sorted(m["exit_reasons"].items()))
    print(f"Exits         : {exits}")
    print()
    print(f"VERDICT: {v}")
    print()
    checks = [
        (f"Trades ≥ {TIER1['trades']}",     m["n_trades"] >= TIER1["trades"],     m["n_trades"]),
        (f"CAGR ≥ {TIER1['cagr']*100:.0f}%", m["cagr"] >= TIER1["cagr"],         f"{m['cagr']*100:.1f}%"),
        (f"Sharpe ≥ {TIER1['sharpe']}",      m["sharpe"] >= TIER1["sharpe"],      f"{m['sharpe']:.2f}"),
        (f"MaxDD ≤ {TIER1['maxdd']*100:.0f}%", m["max_dd"] <= TIER1["maxdd"],     f"{m['max_dd']*100:.1f}%"),
        (f"WinRate ≥ {TIER1['winrate']*100:.0f}%", m["win_rate"] >= TIER1["winrate"], f"{m['win_rate']*100:.1f}%"),
    ]
    for label, ok, val in checks:
        print(f"  {'✓' if ok else '✗'} {label} → {val}")
    print(sep)

    if trades:
        top = sorted(trades, key=lambda t: t["ret_pct"], reverse=True)[:10]
        print("\nTOP 10 TRADES:")
        print(f"{'Stock':<14} {'Entry':>10}  {'RSI':>5}  {'Bars':>4}  {'Ret':>8}  Reason")
        print("-" * 60)
        for t in top:
            print(f"{t['sym']:<14} {str(t['entry_date'])[:10]:>10}  "
                  f"{t['entry_rsi']:>5.1f}  {t['bars_held']:>4}  "
                  f"{t['ret_pct']:>+7.2f}%  {t['exit_reason']}")

    out = Path("reports") / f"bb_breakout_3min_{date.today()}.md"
    out.parent.mkdir(exist_ok=True)
    lines = [
        f"# BB Breakout 3-min (Dhan) — {date.today()}",
        f"Universe: Nifty 50 | Window: {args.days} days | Verdict: **{v}**",
        "",
        "| Stock | Entry | Exit | RSI | Bars | Return | Reason |",
        "|---|---|---|---|---|---|---|",
    ]
    for t in sorted(trades, key=lambda x: x["entry_date"]):
        lines.append(f"| {t['sym']} | {str(t['entry_date'])[:10]} | "
                     f"{str(t['exit_date'])[:10]} | {t['entry_rsi']:.0f} | "
                     f"{t['bars_held']} | {t['ret_pct']:+.2f}% | {t['exit_reason']} |")
    out.write_text("\n".join(lines))
    logger.info("Report saved: %s", out)


if __name__ == "__main__":
    main()
