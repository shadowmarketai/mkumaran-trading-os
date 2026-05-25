"""
BB Breakout Bear — Regime-Filtered Backtest

Bearish BB Breakout (all 4 must fire on daily close):
  1. Close < SuperTrend(7,3) direction = -1
  2. RSI(14) < 30
  3. Close < S1 daily pivot (support broken)
  4. Close < Lower Bollinger Band(20, 2)

REGIME FILTER (the key fix vs plain backtest):
  Only enter short when Nifty 50 is in confirmed bear regime:
  - Nifty 50 close < 200-day SMA  (primary filter)
  - AND Nifty 50 50-day SMA < 200-day SMA (death cross confirms)

In a bull market (2021-2026) this filter blocks almost all signals.
In a genuine bear market (2020 crash, 2022 correction) it fires.

Exit: ST flips to +1 | +5% hard stop (underlying rises) | 20-day time stop
Position: ₹1L per trade, max 5 concurrent (paper short — F&O eligible stocks)

Usage:
    python scripts/validate_bb_breakout_bear.py
    python scripts/validate_bb_breakout_bear.py --from 2020-01-01
"""
from __future__ import annotations

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
logger = logging.getLogger("bb_bear")

ST_PERIOD    = 7
ST_MULT      = 3.0
RSI_PERIOD   = 14
BB_PERIOD    = 20
BB_STD       = 2.0
HARD_STOP    = 0.05      # +5% adverse move on short = stop
MAX_HOLD     = 20
MAX_CONC     = 5
POSITION_INR = 100_000.0
MIN_DAYS     = 252

SMA_LONG     = 200       # Nifty 200-day SMA (primary regime filter)
SMA_SHORT    = 50        # Nifty 50-day SMA (death cross confirmation)

BROKERAGE = 20.0
STT_SELL  = 0.001
EXCHANGE  = 0.0000345
GST       = 0.18
STAMP     = 0.00015
SLIPPAGE  = 0.0005

TIER1 = {"trades": 20, "cagr": 0.15, "sharpe": 0.7, "maxdd": 0.30, "winrate": 0.45}
TIER2 = {"trades": 10, "cagr": 0.08, "sharpe": 0.4, "maxdd": 0.40, "winrate": 0.40}


def _load_symbols() -> list[str]:
    p = Path("data/nifty500.json")
    if not p.exists():
        p = Path(__file__).parent.parent / "data" / "nifty500.json"
    with open(p) as f:
        syms = json.load(f)["symbols"]
    return [s for s in syms if "DUMMY" not in s.upper()]


def _load_prices(symbols: list[str], start_str: str, end_str: str) -> dict[str, dict]:
    import yfinance as yf
    import pandas as pd

    prices: dict[str, dict] = {}
    try:
        from sqlalchemy import text
        from mcp_server.db import engine
        with engine.connect() as conn:
            for sym in symbols:
                rows = conn.execute(
                    text("SELECT bar_date, open, high, low, close FROM ohlcv_cache "
                         "WHERE ticker=:s AND interval='1d' "
                         "AND bar_date BETWEEN :s0 AND :e "
                         "AND close IS NOT NULL AND close > 0 ORDER BY bar_date"),
                    {"s": sym, "s0": start_str, "e": end_str},
                ).fetchall()
                if len(rows) >= MIN_DAYS:
                    prices[sym] = {
                        (r.bar_date.date() if hasattr(r.bar_date, "date") else r.bar_date): {
                            "h": float(r.high or r.close), "l": float(r.low or r.close),
                            "c": float(r.close),
                        }
                        for r in rows
                    }
    except Exception:
        pass

    missing = [s for s in symbols if s not in prices]
    if missing:
        for i in range(0, len(missing), 50):
            chunk = missing[i: i + 50]
            try:
                raw = yf.download([s + ".NS" for s in chunk], start=start_str, end=end_str,
                                  auto_adjust=True, progress=False, threads=True)
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
                            c = raw["Close"].dropna()
                            h = raw["High"].reindex(c.index).fillna(c)
                            lo = raw["Low"].reindex(c.index).fillna(c)
                        if len(c) < MIN_DAYS:
                            continue
                        prices[sym] = {
                            d.date(): {"h": float(h.get(d, c[d])),
                                       "l": float(lo.get(d, c[d])),
                                       "c": float(c[d])}
                            for d in c.index
                        }
                    except Exception:
                        pass
            except Exception as e:
                logger.warning("yfinance batch %d: %s", i, e)

    logger.info("Eligible stocks: %d", len(prices))
    return prices


def _load_nifty(start_str: str, end_str: str) -> dict[date, float]:
    import yfinance as yf
    import pandas as pd
    try:
        raw = yf.download("^NSEI", start=start_str, end=end_str,
                          auto_adjust=True, progress=False)
        if raw is None or raw.empty:
            return {}
        # Handle both MultiIndex (newer yfinance) and flat columns
        if isinstance(raw.columns, pd.MultiIndex):
            c = raw["Close"]["^NSEI"].dropna()
        else:
            c = raw["Close"].dropna()
        result = {}
        for ts, val in c.items():
            d = ts.date() if hasattr(ts, "date") else ts
            result[d] = float(val)
        logger.info("Nifty loaded: %d bars (%s → %s)",
                    len(result), min(result), max(result))
        return result
    except Exception as e:
        logger.warning("Nifty load failed: %s", e)
        return {}


def _build_nifty_regime(nifty: dict[date, float]) -> dict[date, bool]:
    """
    Returns {date: True} when Nifty is in bear regime:
    - Close < 200-day SMA  AND
    - 50-day SMA < 200-day SMA (death cross)
    """
    sorted_dates = sorted(nifty.keys())
    closes = [nifty[d] for d in sorted_dates]
    regime: dict[date, bool] = {}

    for i, d in enumerate(sorted_dates):
        if i < SMA_LONG - 1:
            regime[d] = False
            continue
        sma200 = sum(closes[i - SMA_LONG + 1: i + 1]) / SMA_LONG
        sma50  = sum(closes[i - SMA_SHORT + 1: i + 1]) / SMA_SHORT if i >= SMA_SHORT - 1 else sma200 + 1
        regime[d] = closes[i] < sma200 and sma50 < sma200

    bear_days = sum(1 for v in regime.values() if v)
    logger.info("Bear regime: %d / %d days (%.0f%%)",
                bear_days, len(regime), bear_days / max(len(regime), 1) * 100)
    return regime


def _compute_indicators(ohlcv: list[dict]) -> list[dict]:
    n      = len(ohlcv)
    closes = [b["c"] for b in ohlcv]
    highs  = [b["h"] for b in ohlcv]
    lows   = [b["l"] for b in ohlcv]

    # RSI
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

    # Lower Bollinger Band
    lower_bb = [float("nan")] * n
    for i in range(BB_PERIOD - 1, n):
        w    = closes[i - BB_PERIOD + 1: i + 1]
        mean = sum(w) / BB_PERIOD
        std  = math.sqrt(sum((x - mean) ** 2 for x in w) / BB_PERIOD)
        lower_bb[i] = mean - BB_STD * std

    # SuperTrend
    st_dir  = [0] * n
    st_line = [0.0] * n
    for i in range(1, n):
        if i < ST_PERIOD:
            continue
        atr = sum(
            max(highs[j] - lows[j],
                abs(highs[j] - closes[j-1]),
                abs(lows[j] - closes[j-1]))
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

    # S1 pivot
    s1_vals = [float("nan")] * n
    for i in range(1, n):
        ph, pl, pc = highs[i-1], lows[i-1], closes[i-1]
        pivot   = (ph + pl + pc) / 3
        s1_vals[i] = 2 * pivot - ph

    result = [dict(b) for b in ohlcv]
    for i, bar in enumerate(result):
        bar["rsi"]      = rsi[i]
        bar["lower_bb"] = lower_bb[i]
        bar["st_dir"]   = st_dir[i]
        bar["s1"]       = s1_vals[i]
    return result


def _cost(pos: float) -> float:
    buy  = pos * (1 + SLIPPAGE)
    sell = pos * (1 - SLIPPAGE)
    c    = BROKERAGE * 2 + sell * STT_SELL
    c   += (buy + sell) * EXCHANGE
    c   += (BROKERAGE * 2 + (buy + sell) * EXCHANGE) * GST
    c   += buy * STAMP
    return c


def _backtest(prices: dict, indicators: dict, date_to_idx: dict,
              all_dates: list, start: date, regime: dict,
              rsi_max: float = 30.0, hard_stop: float = HARD_STOP,
              max_conc: int = MAX_CONC) -> list[dict]:
    open_pos: list[dict] = []
    closed:   list[dict] = []
    regime_blocked = 0
    regime_allowed = 0

    for today in all_dates:
        if today < start:
            continue

        # ── Exits ──────────────────────────────────────────────────────────
        still_open: list[dict] = []
        for pos in open_pos:
            sym = pos["sym"]
            idx = date_to_idx.get(sym, {}).get(today)
            if idx is None:
                pos["days_held"] += 1
                still_open.append(pos)
                continue
            bar  = indicators[sym][idx]
            held = pos["days_held"] + 1
            stop = pos["entry_px"] * (1 + hard_stop)  # short stops on price RISE
            ex   = None
            px   = bar["c"]
            if bar["c"] >= stop:
                ex, px = "hard_stop", stop
            elif bar["st_dir"] == 1:   # ST turned bullish → cover short
                ex = "st_flip"
            elif held >= MAX_HOLD:
                ex = "time"
            if ex:
                # Short P&L: profit when price falls
                pnl = (pos["entry_px"] - px) / pos["entry_px"] * POSITION_INR - _cost(POSITION_INR)
                closed.append({
                    "sym": sym, "entry_date": pos["entry_day"], "exit_date": today,
                    "entry_px": round(pos["entry_px"], 2), "exit_px": round(px, 2),
                    "days_held": held, "entry_rsi": round(pos["entry_rsi"], 1),
                    "net_pnl": round(pnl, 2), "ret_pct": round(pnl / POSITION_INR * 100, 2),
                    "exit_reason": ex,
                })
            else:
                pos["days_held"] = held
                still_open.append(pos)
        open_pos = still_open

        # ── Regime check ───────────────────────────────────────────────────
        in_bear_regime = regime.get(today, False)
        if not in_bear_regime:
            regime_blocked += 1
            continue
        regime_allowed += 1

        # ── Entries ─────────────────────────────────────────────────────────
        if len(open_pos) >= max_conc:
            continue
        already = {p["sym"] for p in open_pos}
        for sym, ind in indicators.items():
            if sym in already:
                continue
            idx = date_to_idx.get(sym, {}).get(today)
            if idx is None or idx < BB_PERIOD + ST_PERIOD:
                continue
            bar = ind[idx]
            s1  = bar.get("s1", float("nan"))
            lb  = bar.get("lower_bb", float("nan"))
            if (bar["st_dir"] == -1 and bar["rsi"] < rsi_max
                    and not math.isnan(s1) and bar["c"] < s1
                    and not math.isnan(lb) and bar["c"] < lb):
                open_pos.append({
                    "sym": sym, "entry_day": today,
                    "entry_px": bar["c"], "entry_rsi": bar["rsi"], "days_held": 0,
                })
                if len(open_pos) >= max_conc:
                    break

    logger.info("Regime: %d bear days (allowed entries) | %d bull days (blocked)",
                regime_allowed, regime_blocked)
    return closed


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
    avg_hold = sum(t["days_held"] for t in trades) / n
    sharpe   = (mean_r / std_r) * math.sqrt(252 / max(avg_hold, 1)) if std_r > 0 else 0.0
    cum = peak = max_dd = 0.0
    for t in sorted(trades, key=lambda x: x["exit_date"]):
        cum  += t["net_pnl"]
        peak  = max(peak, cum)
        if peak > 0:
            max_dd = max(max_dd, (peak - cum) / peak)
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
    if all([m["n_trades"] >= TIER1["trades"], m["cagr"] >= TIER1["cagr"],
            m["sharpe"] >= TIER1["sharpe"], m["max_dd"] <= TIER1["maxdd"],
            m["win_rate"] >= TIER1["winrate"]]):
        return "TIER_1"
    if all([m["n_trades"] >= TIER2["trades"], m["cagr"] >= TIER2["cagr"],
            m["sharpe"] >= TIER2["sharpe"], m["max_dd"] <= TIER2["maxdd"],
            m["win_rate"] >= TIER2["winrate"]]):
        return "TIER_2"
    return "OVERRIDE"


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="BB Breakout Bear with Nifty regime filter")
    parser.add_argument("--from",        dest="start",     default="2020-01-01")
    parser.add_argument("--to",          dest="end",       default=str(date.today()))
    parser.add_argument("--rsi-max",     type=float,       default=30.0,
                        help="RSI upper threshold for bear entry (default 30, try 20)")
    parser.add_argument("--hard-stop",   type=float,       default=HARD_STOP,
                        help="Hard stop on short: stock rises this much = stop (default 0.05)")
    parser.add_argument("--max-conc",    type=int,         default=MAX_CONC,
                        help="Max concurrent short positions (default 5, try 3)")
    args = parser.parse_args()

    # Apply CLI overrides
    hard_stop = args.hard_stop
    max_conc  = args.max_conc
    rsi_max   = args.rsi_max

    start      = date.fromisoformat(args.start)
    end        = date.fromisoformat(args.end)
    data_start = date(start.year - 1, start.month, 1)
    years      = (end - start).days / 365.25

    logger.info("Loading Nifty 50 for regime detection...")
    nifty   = _load_nifty(data_start.isoformat(), end.isoformat())
    regime  = _build_nifty_regime(nifty)

    logger.info("Loading Nifty 500 stock prices...")
    symbols = _load_symbols()
    prices  = _load_prices(symbols, data_start.isoformat(), end.isoformat())

    indicators:  dict[str, list[dict]] = {}
    date_to_idx: dict[str, dict]       = {}
    for sym, pd_data in prices.items():
        sym_dates = sorted(pd_data.keys())
        bars      = [pd_data[d] for d in sym_dates]
        indicators[sym]  = _compute_indicators(bars)
        date_to_idx[sym] = {d: i for i, d in enumerate(sym_dates)}

    all_dates = sorted({d for pd_data in prices.values() for d in pd_data
                        if start <= d <= end})

    trades = _backtest(prices, indicators, date_to_idx, all_dates, start, regime,
                       rsi_max=rsi_max, hard_stop=hard_stop, max_conc=max_conc)
    m      = _metrics(trades, years)
    v      = _verdict(m)

    sep = "=" * 68
    print()
    print(sep)
    print(f"BB BREAKOUT BEAR — REGIME FILTERED  |  {args.start} → {end}")
    print("Regime: Nifty < 200-day SMA AND 50-day SMA < 200-day SMA")
    print(f"Entry: ST=-1 + RSI<{rsi_max:.0f} + Close<S1 + Close<Lower BB | Stop: +{hard_stop*100:.0f}% | Conc: {max_conc}")
    print(sep)

    if not m:
        print("No trades — regime filter blocked all signals.")
        print("This means the entire backtest period was a BULL market for Nifty.")
        print("VERDICT: OVERRIDE")
        print(sep)
        return

    print(f"Trades        : {m['n_trades']}")
    print(f"Win rate      : {m['win_rate']*100:.1f}%")
    print(f"Avg hold      : {m['avg_hold']:.1f} days")
    print(f"Avg return    : {m['avg_ret_pct']:+.2f}%")
    print(f"Total P&L     : ₹{m['total_pnl']:,.0f}")
    print(f"CAGR          : {m['cagr']*100:+.1f}%")
    print(f"Sharpe        : {m['sharpe']:.2f}")
    print(f"Max drawdown  : {m['max_dd']*100:.1f}%")
    exits = ", ".join(f"{k}:{c}" for k, c in sorted(m["exit_reasons"].items()))
    print(f"Exits         : {exits}")
    print()
    print(f"VERDICT: {v}")
    checks = [
        (f"Trades ≥ {TIER1['trades']}",       m["n_trades"] >= TIER1["trades"],      m["n_trades"]),
        (f"CAGR ≥ {TIER1['cagr']*100:.0f}%",  m["cagr"] >= TIER1["cagr"],            f"{m['cagr']*100:.1f}%"),
        (f"Sharpe ≥ {TIER1['sharpe']}",        m["sharpe"] >= TIER1["sharpe"],        f"{m['sharpe']:.2f}"),
        (f"MaxDD ≤ {TIER1['maxdd']*100:.0f}%", m["max_dd"] <= TIER1["maxdd"],         f"{m['max_dd']*100:.1f}%"),
        (f"WinRate ≥ {TIER1['winrate']*100:.0f}%", m["win_rate"] >= TIER1["winrate"], f"{m['win_rate']*100:.1f}%"),
    ]
    for label, ok, val in checks:
        print(f"  {'✓' if ok else '✗'} {label} → {val}")
    print(sep)

    if trades:
        top = sorted(trades, key=lambda t: t["ret_pct"], reverse=True)[:10]
        print("\nTOP 10 SHORT TRADES:")
        print(f"{'Stock':<14} {'Entry':>10} {'RSI':>5}  {'Days':>4}  {'Return':>8}  Reason")
        print("-" * 60)
        for t in top:
            print(f"{t['sym']:<14} {str(t['entry_date'])[:10]:>10}"
                  f"  {t['entry_rsi']:>5.1f}  {t['days_held']:>4}  "
                  f"{t['ret_pct']:>+7.2f}%  {t['exit_reason']}")

    out = Path("reports") / f"bb_bear_regime_{date.today()}.md"
    out.parent.mkdir(exist_ok=True)
    lines = [
        f"# BB Breakout Bear (Regime-Filtered) — {date.today()}",
        f"Regime: Nifty < 200-SMA AND 50-SMA < 200-SMA | Verdict: **{v}**", "",
        "| Stock | Entry | Exit | RSI | Days | Return | Reason |",
        "|---|---|---|---|---|---|---|",
    ]
    for t in sorted(trades, key=lambda x: x["entry_date"]):
        lines.append(f"| {t['sym']} | {str(t['entry_date'])[:10]} | "
                     f"{str(t['exit_date'])[:10]} | {t['entry_rsi']:.0f} | "
                     f"{t['days_held']} | {t['ret_pct']:+.2f}% | {t['exit_reason']} |")
    out.write_text("\n".join(lines, encoding='utf-8'))
    logger.info("Report saved: %s", out)


if __name__ == "__main__":
    main()
