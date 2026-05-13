"""
BB Breakout — Revised Parameters for Failing Timeframes

Original result → Revised fix:
  5m  : RSI>70, BBstd 2.0, ₹1L, hold 20 bars → RSI>85, BBstd 2.5, ₹5L, hold 30 bars
  1h  : RSI>70, BBstd 2.0, no filter         → RSI>80, BBstd 2.5, daily ST alignment
  1w  : RSI>70, BBstd 2.0, hold 20w, stop 5% → RSI>60, BBstd 2.0, hold 10w, stop 8%

Usage:
    python scripts/validate_bb_revised.py
    python scripts/validate_bb_revised.py --tf 1h
    python scripts/validate_bb_revised.py --tf 5m 1h 1w
"""
from __future__ import annotations

import argparse
import logging
import math
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("bb_revised")

# ── Shared constants ──────────────────────────────────────────────────────────
ST_PERIOD    = 7
ST_MULT      = 3.0
MAX_CONC     = 5

DELIVERY_COSTS = {"brokerage": 20.0, "stt_sell": 0.001, "exchange": 0.0000345,
                  "gst": 0.18, "stamp": 0.00015, "slippage": 0.0005}
INTRADAY_COSTS = {"brokerage": 20.0, "stt_sell": 0.00025, "exchange": 0.0000345,
                  "gst": 0.18, "stamp": 0.00003, "slippage": 0.001}

TIER1 = {"trades": 30, "cagr": 0.20, "sharpe": 0.8, "maxdd": 0.30, "winrate": 0.50}
TIER2 = {"trades": 15, "cagr": 0.10, "sharpe": 0.5, "maxdd": 0.40, "winrate": 0.40}

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

# ── Data helpers ──────────────────────────────────────────────────────────────

def _download_yf(symbols: list[str], interval: str, period: str | None = None,
                 start: str | None = None) -> dict[str, list[dict]]:
    import yfinance as yf
    import pandas as pd

    result: dict[str, list[dict]] = {}
    kw: dict = {"auto_adjust": True, "progress": False, "threads": False}
    if period:
        kw["period"] = period
    else:
        kw["start"] = start

    for sym in symbols:
        try:
            raw = yf.download(sym + ".NS", interval=interval, **kw)
            if raw is None or raw.empty:
                continue
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.droplevel(1)
            bars: list[dict] = []
            for ts, row in raw.iterrows():
                d = ts.date() if hasattr(ts, "date") else ts
                bars.append({"date": d, "ts": ts,
                             "o": float(row["Open"]), "h": float(row["High"]),
                             "l": float(row["Low"]),  "c": float(row["Close"]),
                             "is_last_of_day": False})
            if not bars:
                continue
            for i in range(len(bars) - 1):
                if bars[i]["date"] != bars[i + 1]["date"]:
                    bars[i]["is_last_of_day"] = True
            bars[-1]["is_last_of_day"] = True
            result[sym] = bars
        except Exception:
            pass
    logger.info("[%s] Loaded %d / %d", interval, len(result), len(symbols))
    return result


def _download_yf_batch(symbols: list[str], interval: str,
                       start: str) -> dict[str, list[dict]]:
    """Batch download for daily/weekly (faster)."""
    import yfinance as yf
    import pandas as pd

    result: dict[str, list[dict]] = {}
    for i in range(0, len(symbols), 50):
        chunk = symbols[i: i + 50]
        try:
            raw = yf.download([s + ".NS" for s in chunk], interval=interval,
                              start=start, auto_adjust=True, progress=False, threads=True)
            if raw is None or raw.empty:
                continue
            for sym in chunk:
                try:
                    yf_sym = sym + ".NS"
                    if isinstance(raw.columns, pd.MultiIndex):
                        c  = raw["Close"][yf_sym].dropna()
                        h  = raw["High"][yf_sym].reindex(c.index).fillna(c)
                        lo = raw["Low"][yf_sym].reindex(c.index).fillna(c)
                    else:
                        c  = raw["Close"].dropna()
                        h  = raw["High"].reindex(c.index).fillna(c)
                        lo = raw["Low"].reindex(c.index).fillna(c)
                    bars = []
                    for ts in c.index:
                        d = ts.date() if hasattr(ts, "date") else ts
                        bars.append({"date": d, "o": float(c[ts]),
                                     "h": float(h.get(ts, c[ts])),
                                     "l": float(lo.get(ts, c[ts])),
                                     "c": float(c[ts])})
                    if bars:
                        result[sym] = bars
                except Exception:
                    pass
        except Exception as e:
            logger.warning("Batch error: %s", e)
    logger.info("[%s batch] Loaded %d / %d", interval, len(result), len(symbols))
    return result


# ── Pivot helpers ─────────────────────────────────────────────────────────────

def _add_pivots_intraday(bars: list[dict]) -> list[dict]:
    daily: dict = {}
    for b in bars:
        d = b["date"]
        if d not in daily:
            daily[d] = {"h": b["h"], "l": b["l"], "c": b["c"]}
        else:
            daily[d]["h"] = max(daily[d]["h"], b["h"])
            daily[d]["l"] = min(daily[d]["l"], b["l"])
            daily[d]["c"] = b["c"]
    sorted_days = sorted(daily)
    day_r1: dict = {}
    for i, d in enumerate(sorted_days):
        if i == 0:
            day_r1[d] = float("nan")
        else:
            prev = daily[sorted_days[i - 1]]
            pivot = (prev["h"] + prev["l"] + prev["c"]) / 3
            day_r1[d] = 2 * pivot - prev["l"]
    for b in bars:
        b["r1"] = day_r1.get(b["date"], float("nan"))
    return bars


def _add_pivots_bar(bars: list[dict]) -> list[dict]:
    """Prev-bar pivot (for daily/weekly)."""
    for i in range(1, len(bars)):
        ph, pl, pc = bars[i-1]["h"], bars[i-1]["l"], bars[i-1]["c"]
        pivot = (ph + pl + pc) / 3
        bars[i]["r1"] = 2 * pivot - pl
    if bars:
        bars[0]["r1"] = float("nan")
    return bars


# ── Indicator engine ──────────────────────────────────────────────────────────

def _compute_indicators(bars: list[dict], bb_std: float, rsi_period: int = 14,
                        bb_period: int = 20) -> list[dict]:
    n = len(bars)
    closes = [b["c"] for b in bars]
    highs  = [b["h"] for b in bars]
    lows   = [b["l"] for b in bars]

    # RSI
    rsi = [50.0] * n
    if n > rsi_period:
        gains  = [max(closes[i] - closes[i-1], 0) for i in range(1, n)]
        losses = [max(closes[i-1] - closes[i], 0) for i in range(1, n)]
        alpha  = 1.0 / rsi_period
        ag     = sum(gains[:rsi_period]) / rsi_period
        al     = sum(losses[:rsi_period]) / rsi_period
        rsi[rsi_period] = 100 - 100 / (1 + ag / al) if al > 0 else 100.0
        for i in range(rsi_period, len(gains)):
            ag = (1 - alpha) * ag + alpha * gains[i]
            al = (1 - alpha) * al + alpha * losses[i]
            rsi[i + 1] = 100 - 100 / (1 + ag / al) if al > 0 else 100.0

    # Bollinger Bands (upper only)
    upper_bb = [float("nan")] * n
    for i in range(bb_period - 1, n):
        w    = closes[i - bb_period + 1 : i + 1]
        mean = sum(w) / bb_period
        std  = math.sqrt(sum((x - mean) ** 2 for x in w) / bb_period)
        upper_bb[i] = mean + bb_std * std

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
        bar["st_prev"]  = st_dir[i-1] if i > 0 else 0
    return result


# ── Cost model ────────────────────────────────────────────────────────────────

def _cost(pos: float, costs: dict) -> float:
    buy  = pos * (1 + costs["slippage"])
    sell = pos * (1 - costs["slippage"])
    c    = costs["brokerage"] * 2 + sell * costs["stt_sell"]
    c   += (buy + sell) * costs["exchange"]
    c   += (costs["brokerage"] * 2 + (buy + sell) * costs["exchange"]) * costs["gst"]
    c   += buy * costs["stamp"]
    return c


# ── Backtest engine ───────────────────────────────────────────────────────────

def _backtest(
    sym_bars: dict[str, list[dict]],
    rsi_threshold: float,
    bb_std: float,
    max_hold: int,
    hard_stop: float,
    position_inr: float,
    costs: dict,
    is_intraday: bool,
    eod_close: bool,
    fresh_st_only: bool = False,
    daily_st_dir: dict | None = None,  # {(sym, date): st_direction} for 1h alignment
) -> list[dict]:

    indicators: dict[str, list[dict]] = {}
    for sym, bars in sym_bars.items():
        if is_intraday:
            bars = _add_pivots_intraday(bars)
        else:
            bars = _add_pivots_bar(bars)
        indicators[sym] = _compute_indicators(bars, bb_std)

    all_keys: list[tuple] = []
    for sym, ind in indicators.items():
        for i, bar in enumerate(ind):
            sort_key = bar.get("ts", bar["date"])
            all_keys.append((sort_key, sym, i))
    all_keys.sort(key=lambda x: x[0])

    open_positions: list[dict] = []
    closed_trades: list[dict] = []

    for _, sym, bar_idx in all_keys:
        bar = indicators[sym][bar_idx]

        # ── Exits ──────────────────────────────────────────────────────────
        still_open: list[dict] = []
        for pos in open_positions:
            if pos["sym"] != sym:
                still_open.append(pos)
                continue
            close        = bar["c"]
            hard_stop_px = pos["entry_px"] * (1 - hard_stop)
            bars_held    = pos["bars_held"] + 1
            exit_reason  = None
            exit_px      = close

            if close <= hard_stop_px:
                exit_reason, exit_px = "hard_stop", hard_stop_px
            elif bar["st_dir"] == -1:
                exit_reason = "st_flip"
            elif bars_held >= max_hold:
                exit_reason = "time"
            elif eod_close and bar.get("is_last_of_day"):
                exit_reason = "eod"

            if exit_reason:
                pnl = ((exit_px - pos["entry_px"]) / pos["entry_px"]
                       * position_inr - _cost(position_inr, costs))
                closed_trades.append({
                    "sym": sym, "entry_date": pos["entry_date"],
                    "exit_date": bar["date"],
                    "entry_px": round(pos["entry_px"], 2),
                    "exit_px":  round(exit_px, 2),
                    "bars_held": bars_held,
                    "entry_rsi": round(pos["entry_rsi"], 1),
                    "net_pnl":   round(pnl, 2),
                    "ret_pct":   round(pnl / position_inr * 100, 2),
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
        if bar_idx < 20 + ST_PERIOD:
            continue

        r1 = bar.get("r1", float("nan"))
        ub = bar.get("upper_bb", float("nan"))

        # Core 4-condition check
        if not (bar["st_dir"] == 1
                and bar["rsi"] > rsi_threshold
                and not math.isnan(r1) and bar["c"] > r1
                and not math.isnan(ub) and bar["c"] > ub):
            continue

        # Optional: only take when ST just flipped (fresh trend)
        if fresh_st_only and bar.get("st_prev", 0) == 1:
            continue

        # Optional: require daily ST also bullish (1h alignment filter)
        if daily_st_dir is not None:
            if daily_st_dir.get((sym, bar["date"]), 0) != 1:
                continue

        open_positions.append({
            "sym": sym, "entry_date": bar["date"],
            "entry_px": bar["c"], "entry_rsi": bar["rsi"], "bars_held": 0,
        })

    # Force-close remaining
    for pos in open_positions:
        ind  = indicators.get(pos["sym"], [])
        last = ind[-1] if ind else None
        px   = last["c"] if last else pos["entry_px"]
        pnl  = (px - pos["entry_px"]) / pos["entry_px"] * position_inr - _cost(position_inr, costs)
        closed_trades.append({
            "sym": pos["sym"], "entry_date": pos["entry_date"],
            "exit_date": last["date"] if last else pos["entry_date"],
            "entry_px": round(pos["entry_px"], 2), "exit_px": round(px, 2),
            "bars_held": pos["bars_held"], "entry_rsi": round(pos["entry_rsi"], 1),
            "net_pnl": round(pnl, 2),
            "ret_pct": round(pnl / position_inr * 100, 2),
            "exit_reason": "end",
        })

    return closed_trades


# ── Metrics ───────────────────────────────────────────────────────────────────

def _metrics(trades: list[dict], years: float, bars_per_year: float = 252) -> dict:
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
    sharpe   = (mean_r / std_r) * math.sqrt(bars_per_year / max(avg_hold, 1)) if std_r > 0 else 0.0
    ref      = float(MAX_CONC * trades[0].get("position_inr", 100_000))
    if ref == 0:
        ref = MAX_CONC * 100_000.0
    cum = peak = max_dd = 0.0
    for t in sorted(trades, key=lambda x: x["exit_date"]):
        cum  += t["net_pnl"]
        peak  = max(peak, cum)
        max_dd = max(max_dd, (peak - cum) / ref)
    reasons: dict[str, int] = {}
    for t in trades:
        reasons[t["exit_reason"]] = reasons.get(t["exit_reason"], 0) + 1
    return {"n_trades": n, "win_rate": wins / n, "cagr": cagr,
            "sharpe": sharpe, "max_dd": max_dd,
            "total_pnl": sum(t["net_pnl"] for t in trades),
            "avg_hold": avg_hold, "avg_ret_pct": mean_r * 100,
            "exit_reasons": reasons}


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


def _print_result(label: str, m: dict, v: str, orig_verdict: str) -> None:
    sep = "=" * 68
    print()
    print(sep)
    print(f"{label}")
    print(sep)
    if not m:
        print("  No trades generated.")
        print(f"  VERDICT: OVERRIDE  (was: {orig_verdict})")
        return
    arrow = "✅ IMPROVED" if (v != "OVERRIDE" and orig_verdict == "OVERRIDE") else (
            "⚠️  SAME" if v == orig_verdict else "📈 CHANGED")
    print(f"  Trades    : {m['n_trades']}")
    print(f"  Win rate  : {m['win_rate']*100:.1f}%")
    print(f"  CAGR      : {m['cagr']*100:+.1f}%")
    print(f"  Sharpe    : {m['sharpe']:.2f}")
    print(f"  Max DD    : {m['max_dd']*100:.1f}%")
    exits = ", ".join(f"{k}:{c}" for k, c in sorted(m["exit_reasons"].items()))
    print(f"  Exits     : {exits}")
    print(f"  VERDICT: {v}  {arrow}  (was: {orig_verdict})")
    print(sep)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tf", nargs="+", choices=["5m", "1h", "1w"],
                        default=["5m", "1h", "1w"])
    args = parser.parse_args()

    summary: list[dict] = []

    # ── 5-minute revised ────────────────────────────────────────────────────
    if "5m" in args.tf:
        logger.info("=== 5m REVISED: RSI>85, BB std 2.5, ₹5L, 30-bar hold ===")
        sym_bars = _download_yf(NIFTY50, "5m", period="55d")
        if sym_bars:
            trades = _backtest(sym_bars,
                rsi_threshold=85, bb_std=2.5, max_hold=30, hard_stop=0.05,
                position_inr=500_000, costs=INTRADAY_COSTS,
                is_intraday=True, eod_close=True)
            all_dates = [t["exit_date"] for t in trades] + [t["entry_date"] for t in trades]
            years = max((max(all_dates) - min(all_dates)).days / 365.25, 0.05) if all_dates else 0.2
            for t in trades:
                t["position_inr"] = 500_000
            m = _metrics(trades, years, bars_per_year=31_250)
            v = _verdict(m)
            _print_result("5m REVISED — RSI>85 | BBstd 2.5 | ₹5L | Hold 30 bars | EOD close",
                          m, v, orig_verdict="OVERRIDE")
            summary.append({"tf": "5m", "orig": "OVERRIDE", "new": v,
                            "trades": m.get("n_trades", 0), "cagr": m.get("cagr", 0),
                            "sharpe": m.get("sharpe", 0)})

    # ── 1-hour revised with daily alignment ─────────────────────────────────
    if "1h" in args.tf:
        logger.info("=== 1h REVISED: RSI>80, BB std 2.5, daily ST alignment ===")
        sym_bars_1h = _download_yf(NIFTY50, "60m", period="700d")
        sym_bars_1d = _download_yf_batch(NIFTY50, "1d", start="2022-01-01")

        # Build daily ST direction lookup
        daily_st_dir: dict[tuple, int] = {}
        for sym, bars in sym_bars_1d.items():
            bars_with_piv = _add_pivots_bar(list(bars))
            ind = _compute_indicators(bars_with_piv, bb_std=2.0)
            for bar in ind:
                daily_st_dir[(sym, bar["date"])] = bar["st_dir"]
        logger.info("Daily ST direction built for %d symbols", len(sym_bars_1d))

        if sym_bars_1h:
            trades = _backtest(sym_bars_1h,
                rsi_threshold=80, bb_std=2.5, max_hold=20, hard_stop=0.05,
                position_inr=100_000, costs=INTRADAY_COSTS,
                is_intraday=True, eod_close=False, fresh_st_only=True,
                daily_st_dir=daily_st_dir)
            all_dates = [t["exit_date"] for t in trades] + [t["entry_date"] for t in trades]
            years = max((max(all_dates) - min(all_dates)).days / 365.25, 0.1) if all_dates else 1.0
            for t in trades:
                t["position_inr"] = 100_000
            m = _metrics(trades, years, bars_per_year=1_250)
            v = _verdict(m)
            _print_result(
                "1h REVISED — RSI>80 | BBstd 2.5 | Fresh ST flip | Daily ST alignment filter",
                m, v, orig_verdict="OVERRIDE")
            summary.append({"tf": "1h", "orig": "OVERRIDE", "new": v,
                            "trades": m.get("n_trades", 0), "cagr": m.get("cagr", 0),
                            "sharpe": m.get("sharpe", 0)})

    # ── 1-week revised ───────────────────────────────────────────────────────
    if "1w" in args.tf:
        logger.info("=== 1w REVISED: RSI>60, hard stop 8%%, hold 10 bars ===")
        import json
        from pathlib import Path
        p = Path("data/nifty500.json")
        if not p.exists():
            p = Path(__file__).parent.parent / "data" / "nifty500.json"
        with open(p) as f:
            n500 = [s for s in json.load(f)["symbols"] if "DUMMY" not in s.upper()]

        sym_bars_1w = _download_yf_batch(n500, "1wk", start="2020-01-01")
        if sym_bars_1w:
            trades = _backtest(sym_bars_1w,
                rsi_threshold=60, bb_std=2.0, max_hold=10, hard_stop=0.08,
                position_inr=100_000, costs=DELIVERY_COSTS,
                is_intraday=False, eod_close=False)
            all_dates = [t["exit_date"] for t in trades] + [t["entry_date"] for t in trades]
            years = max((max(all_dates) - min(all_dates)).days / 365.25, 0.5) if all_dates else 1.0
            for t in trades:
                t["position_inr"] = 100_000
            m = _metrics(trades, years, bars_per_year=52)
            v = _verdict(m)
            _print_result("1w REVISED — RSI>60 | Hard stop 8% | Hold 10 bars (10 weeks)",
                          m, v, orig_verdict="OVERRIDE")
            summary.append({"tf": "1w", "orig": "OVERRIDE", "new": v,
                            "trades": m.get("n_trades", 0), "cagr": m.get("cagr", 0),
                            "sharpe": m.get("sharpe", 0)})

    # ── Summary ──────────────────────────────────────────────────────────────
    if len(summary) > 1:
        print()
        print("=" * 68)
        print("REVISED PARAMETERS SUMMARY")
        print("=" * 68)
        print(f"{'TF':<6} {'Trades':>7} {'CAGR':>10} {'Sharpe':>8}  Was → Now")
        print("-" * 68)
        for r in summary:
            arrow = "✅" if r["new"] != "OVERRIDE" else "❌"
            print(f"{r['tf']:<6} {r['trades']:>7} {r['cagr']*100:>+9.1f}%"
                  f" {r['sharpe']:>8.2f}  {r['orig']} → {r['new']} {arrow}")
        print("=" * 68)


if __name__ == "__main__":
    main()
