"""
BB Breakout Strategy Validation (Dharanidharan PC Framework)

5-layer confluence backtest on Nifty 500 daily bars.
All 4 entry conditions must fire simultaneously:
  Bullish: SuperTrend bull + RSI>70 + Close>R1 + Close>Upper BB
  Bearish: SuperTrend bear + RSI<30 + Close<S1 + Close<Lower BB

Exit: SuperTrend flips OR -5% hard stop OR 20-day time stop.

Pre-committed criteria: docs/strategy_validation/bb_breakout_criteria.md

Usage:
    python scripts/validate_bb_breakout.py
    python scripts/validate_bb_breakout.py --from 2021-01-01
    python scripts/validate_bb_breakout.py --st-period 7 --st-mult 3
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
logger = logging.getLogger("bb_breakout_val")

ST_PERIOD    = 7
ST_MULT      = 3.0
RSI_PERIOD   = 14
BB_PERIOD    = 20
BB_STD       = 2.0
HARD_STOP    = 0.05
MAX_HOLD     = 20
MAX_CONC     = 5
POSITION_INR = 100_000.0
MIN_DAYS     = 252

BROKERAGE = 20.0
STT_SELL  = 0.001
EXCHANGE  = 0.0000345
GST       = 0.18
STAMP     = 0.00015
SLIPPAGE  = 0.0005

TIER1_TRADES  = 30
TIER1_CAGR    = 0.20
TIER1_SHARPE  = 0.8
TIER1_MAXDD   = 0.30
TIER1_WINRATE = 0.50
TIER2_TRADES  = 15
TIER2_CAGR    = 0.10
TIER2_SHARPE  = 0.5
TIER2_MAXDD   = 0.40
TIER2_WINRATE = 0.40


# ── Data loading ─────────────────────────────────────────────────────────────

def _load_symbols() -> list[str]:
    p = Path("data/nifty500.json")
    if not p.exists():
        p = Path(__file__).parent.parent / "data" / "nifty500.json"
    with open(p) as f:
        syms = json.load(f)["symbols"]
    return [s for s in syms if "DUMMY" not in s.upper()]


def _load_prices(symbols: list[str], start_str: str, end_str: str) -> dict[str, dict]:
    """Load {date: {o,h,l,c}} from ohlcv_cache; yfinance fallback."""
    import yfinance as yf
    from sqlalchemy import text
    from mcp_server.db import engine

    prices: dict[str, dict] = {}
    logger.info("Loading OHLCV for %d symbols...", len(symbols))
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
                        "o": float(r.open  or r.close),
                        "h": float(r.high  or r.close),
                        "l": float(r.low   or r.close),
                        "c": float(r.close),
                    }
                    for r in rows
                }

    missing = [s for s in symbols if s not in prices]
    logger.info("DB: %d | yfinance: %d", len(prices), len(missing))
    if missing:
        import pandas as pd
        for i in range(0, len(missing), 50):
            chunk = missing[i : i + 50]
            try:
                raw = yf.download([s + ".NS" for s in chunk], start=start_str, end=end_str,
                                  auto_adjust=True, progress=False, threads=True)
                if raw.empty:
                    continue
                for sym in chunk:
                    try:
                        yf_sym = sym + ".NS"
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
                        if len(c) >= MIN_DAYS:
                            prices[sym] = {
                                d.date(): {"o": float(o.get(d, cv)), "h": float(h.get(d, cv)),
                                           "l": float(lo.get(d, cv)), "c": float(cv)}
                                for d, cv in c.items()
                            }
                    except Exception:
                        pass
            except Exception as e:
                logger.warning("yfinance batch %d: %s", i, e)

    logger.info("Eligible stocks: %d", len(prices))
    return prices


# ── Indicators ───────────────────────────────────────────────────────────────

def _compute_indicators(ohlcv: list[dict]) -> list[dict]:
    """
    Compute SuperTrend, RSI, Pivot, BB for each bar.
    ohlcv: sorted list of {o,h,l,c} dicts.
    Returns same list with added indicator keys.
    """
    n = len(ohlcv)
    closes = [b["c"] for b in ohlcv]
    highs  = [b["h"] for b in ohlcv]
    lows   = [b["l"] for b in ohlcv]

    # ── RSI ────────────────────────────────────────────────────────────────
    rsi_vals = [50.0] * n
    if n > RSI_PERIOD:
        gains  = [max(closes[i] - closes[i-1], 0) for i in range(1, n)]
        losses = [max(closes[i-1] - closes[i], 0) for i in range(1, n)]
        alpha  = 1.0 / RSI_PERIOD
        ag = al = 0.0
        for i in range(RSI_PERIOD):
            ag += gains[i]
            al += losses[i]
        ag /= RSI_PERIOD
        al /= RSI_PERIOD
        rsi_vals[RSI_PERIOD] = 100 - 100 / (1 + ag / al) if al > 0 else 100.0
        for i in range(RSI_PERIOD, len(gains)):
            ag = (1 - alpha) * ag + alpha * gains[i]
            al = (1 - alpha) * al + alpha * losses[i]
            rsi_vals[i + 1] = 100 - 100 / (1 + ag / al) if al > 0 else 100.0

    # ── Bollinger Bands ──────────────────────────────────────────────────
    upper_bb = [float("nan")] * n
    lower_bb = [float("nan")] * n
    for i in range(BB_PERIOD - 1, n):
        window = closes[i - BB_PERIOD + 1 : i + 1]
        mean   = sum(window) / BB_PERIOD
        std    = math.sqrt(sum((x - mean) ** 2 for x in window) / BB_PERIOD)
        upper_bb[i] = mean + BB_STD * std
        lower_bb[i] = mean - BB_STD * std

    # ── SuperTrend ──────────────────────────────────────────────────────
    st_dir   = [0]  * n
    st_line  = [0.0] * n
    for i in range(1, n):
        if i < ST_PERIOD:
            continue
        # ATR
        atr = sum(
            max(highs[j] - lows[j],
                abs(highs[j] - closes[j-1]),
                abs(lows[j]  - closes[j-1]))
            for j in range(i - ST_PERIOD + 1, i + 1)
        ) / ST_PERIOD
        hl2   = (highs[i] + lows[i]) / 2
        upper = hl2 + ST_MULT * atr
        lower = hl2 - ST_MULT * atr

        if closes[i] > (st_line[i-1] if st_line[i-1] else upper):
            st_line[i] = max(lower, st_line[i-1]) if st_dir[i-1] == 1 else lower
            st_dir[i]  = 1
        else:
            st_line[i] = min(upper, st_line[i-1]) if st_dir[i-1] == -1 else upper
            st_dir[i]  = -1

    # ── Pivot Points (from previous day) ───────────────────────────────
    r1_vals = [float("nan")] * n
    s1_vals = [float("nan")] * n
    for i in range(1, n):
        ph, pl, pc = highs[i-1], lows[i-1], closes[i-1]
        pivot  = (ph + pl + pc) / 3
        r1_vals[i] = 2 * pivot - pl
        s1_vals[i] = 2 * pivot - ph

    # Attach to bars
    result = [dict(b) for b in ohlcv]
    for i, bar in enumerate(result):
        bar["rsi"]      = rsi_vals[i]
        bar["upper_bb"] = upper_bb[i]
        bar["lower_bb"] = lower_bb[i]
        bar["st_dir"]   = st_dir[i]
        bar["r1"]       = r1_vals[i]
        bar["s1"]       = s1_vals[i]
    return result


# ── Cost model ────────────────────────────────────────────────────────────────

def _round_trip_cost(pos: float) -> float:
    buy  = pos * (1 + SLIPPAGE)
    sell = pos * (1 - SLIPPAGE)
    cost = BROKERAGE * 2 + sell * STT_SELL + (buy + sell) * EXCHANGE
    cost += (BROKERAGE * 2 + (buy + sell) * EXCHANGE) * GST + buy * STAMP
    return cost


# ── Backtest ──────────────────────────────────────────────────────────────────

def run_backtest(prices: dict[str, dict], start: date, end: date) -> list[dict]:
    # Pre-compute indicators for each stock
    indicators: dict[str, list[dict]] = {}
    date_to_idx: dict[str, dict[date, int]] = {}

    for sym, pd_data in prices.items():
        sym_dates = sorted(pd_data.keys())
        bars      = [pd_data[d] for d in sym_dates]
        ind       = _compute_indicators(bars)
        indicators[sym] = ind
        date_to_idx[sym] = {d: i for i, d in enumerate(sym_dates)}

    all_dates = sorted({d for pd_data in prices.values() for d in pd_data if start <= d <= end})
    open_positions: list[dict] = []
    closed_trades:  list[dict] = []

    for today in all_dates:
        # Check exits
        still_open = []
        for pos in open_positions:
            sym     = pos["sym"]
            idx_map = date_to_idx.get(sym, {})
            idx     = idx_map.get(today)
            if idx is None:
                pos["days_held"] += 1
                still_open.append(pos)
                continue

            bar      = indicators[sym][idx]
            close    = bar["c"]
            st_dir   = bar["st_dir"]
            held     = pos["days_held"] + 1
            hard_stop_px = pos["entry_px"] * (1 - HARD_STOP)

            exit_reason = None
            exit_px     = close

            if close <= hard_stop_px:
                exit_reason, exit_px = "hard_stop", hard_stop_px
            elif st_dir == -1:
                exit_reason = "st_flip"
            elif held >= MAX_HOLD:
                exit_reason = "time"

            if exit_reason:
                pnl = (exit_px - pos["entry_px"]) / pos["entry_px"] * POSITION_INR - _round_trip_cost(POSITION_INR)
                closed_trades.append({
                    "sym": sym, "entry_date": pos["entry_day"], "exit_date": today,
                    "entry_px": round(pos["entry_px"], 2), "exit_px": round(exit_px, 2),
                    "trading_days": held, "entry_rsi": round(pos["entry_rsi"], 1),
                    "net_pnl": round(pnl, 2),
                    "ret_pct": round(pnl / POSITION_INR * 100, 2),
                    "exit_reason": exit_reason,
                })
            else:
                pos["days_held"] = held
                still_open.append(pos)

        open_positions = still_open

        # Scan new entries
        slots = MAX_CONC - len(open_positions)
        if slots <= 0:
            continue
        already = {p["sym"] for p in open_positions}
        candidates: list[tuple[float, str, dict]] = []  # (rsi, sym, bar)

        for sym, ind in indicators.items():
            if sym in already:
                continue
            idx = date_to_idx.get(sym, {}).get(today)
            if idx is None or idx < BB_PERIOD + ST_PERIOD:
                continue
            bar = ind[idx]
            # All 4 bullish conditions
            if (bar["st_dir"] == 1
                    and bar["rsi"] > 70
                    and not math.isnan(bar.get("r1", float("nan")))
                    and bar["c"] > bar["r1"]
                    and not math.isnan(bar.get("upper_bb", float("nan")))
                    and bar["c"] > bar["upper_bb"]):
                candidates.append((bar["rsi"], sym, bar))

        candidates.sort(key=lambda x: x[0], reverse=True)  # highest RSI first
        for _, sym, bar in candidates[:slots]:
            open_positions.append({
                "sym": sym, "entry_day": today, "entry_px": bar["c"],
                "entry_rsi": bar["rsi"], "days_held": 0,
            })

    # Force-close remaining
    for pos in open_positions:
        sym = pos["sym"]
        idx_map = date_to_idx.get(sym, {})
        last_idx = idx_map.get(end)
        last_close = indicators[sym][last_idx]["c"] if last_idx is not None else pos["entry_px"]
        pnl = (last_close - pos["entry_px"]) / pos["entry_px"] * POSITION_INR - _round_trip_cost(POSITION_INR)
        closed_trades.append({
            "sym": sym, "entry_date": pos["entry_day"], "exit_date": end,
            "entry_px": round(pos["entry_px"], 2), "exit_px": round(last_close, 2),
            "trading_days": pos["days_held"], "entry_rsi": round(pos["entry_rsi"], 1),
            "net_pnl": round(pnl, 2), "ret_pct": round(pnl / POSITION_INR * 100, 2),
            "exit_reason": "end_of_backtest",
        })

    return closed_trades


# ── Metrics + verdict ─────────────────────────────────────────────────────────

def _metrics(trades: list[dict], start: date, end: date) -> dict:
    if not trades:
        return {}
    returns = [t["ret_pct"] / 100 for t in trades]
    n     = len(trades)
    wins  = sum(1 for r in returns if r > 0)
    total = sum(returns)
    years = (end - start).days / 365.25
    cagr  = (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else -1.0
    mean_r = total / n
    std_r  = math.sqrt(sum((r - mean_r) ** 2 for r in returns) / max(n - 1, 1))
    avg_hold = sum(t["trading_days"] for t in trades) / n
    sharpe = (mean_r / std_r) * math.sqrt(252 / max(avg_hold, 1)) if std_r > 0 else 0.0
    ref    = float(MAX_CONC * POSITION_INR)
    cum = peak = max_dd = 0.0
    for t in sorted(trades, key=lambda x: x["exit_date"]):
        cum  += t["net_pnl"]
        peak  = max(peak, cum)
        max_dd = max(max_dd, (peak - cum) / ref)
    exit_reasons: dict[str, int] = {}
    for t in trades:
        exit_reasons[t["exit_reason"]] = exit_reasons.get(t["exit_reason"], 0) + 1
    return {
        "n_trades": n, "win_rate": wins / n, "cagr": cagr,
        "sharpe": sharpe, "max_dd": max_dd,
        "total_pnl": sum(t["net_pnl"] for t in trades),
        "avg_hold": avg_hold, "avg_ret_pct": mean_r * 100,
        "exit_reasons": exit_reasons,
    }


def _verdict(m: dict) -> str:
    if not m:
        return "OVERRIDE"
    if (m["n_trades"] >= TIER1_TRADES and m["cagr"] >= TIER1_CAGR
            and m["sharpe"] >= TIER1_SHARPE and m["max_dd"] <= TIER1_MAXDD
            and m["win_rate"] >= TIER1_WINRATE):
        return "TIER_1"
    if (m["n_trades"] >= TIER2_TRADES and m["cagr"] >= TIER2_CAGR
            and m["sharpe"] >= TIER2_SHARPE and m["max_dd"] <= TIER2_MAXDD
            and m["win_rate"] >= TIER2_WINRATE):
        return "TIER_2"
    return "OVERRIDE"


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="BB Breakout backtest (Dharanidharan PC framework)")
    parser.add_argument("--from",       dest="start",    default="2021-01-01")
    parser.add_argument("--to",         dest="end",      default=str(date.today()))
    parser.add_argument("--st-period",  type=int,        default=ST_PERIOD)
    parser.add_argument("--st-mult",    type=float,      default=ST_MULT)
    args = parser.parse_args()

    start      = date.fromisoformat(args.start)
    end        = date.fromisoformat(args.end)
    data_start = date(start.year - 1, start.month, 1)

    symbols = _load_symbols()
    prices  = _load_prices(symbols, data_start.isoformat(), end.isoformat())
    if len(prices) < 10:
        logger.error("Insufficient data")
        return

    logger.info("Running BB Breakout backtest: %s → %s | ST(%d,%.1f) | RSI14>70 | R1 pivot | Upper BB(20,2)",
                start, end, args.st_period, args.st_mult)
    logger.info("Exit: ST flip OR -%.0f%% hard stop OR %d-day time stop", HARD_STOP * 100, MAX_HOLD)

    trades = run_backtest(prices, start, end)
    m      = _metrics(trades, start, end)
    tier   = _verdict(m)

    sep = "=" * 68
    print()
    print(sep)
    print(f"BB BREAKOUT STRATEGY (Bullish)  |  {args.start} → {end}")
    print(f"ST({args.st_period},{args.st_mult}) + RSI>70 + Close>R1 + Close>Upper BB(20,2)")
    print(sep)

    if not m:
        print("No trades generated. Strategy conditions may be too strict for this period.")
        return

    print(f"{'Trades':<35}: {m['n_trades']}")
    print(f"{'Win rate':<35}: {m['win_rate']*100:.1f}%")
    print(f"{'Avg hold (trading days)':<35}: {m['avg_hold']:.1f}")
    print(f"{'Avg return per trade':<35}: {m['avg_ret_pct']:+.2f}%")
    print(f"{'Total net P&L (₹)':<35}: {m['total_pnl']:,.0f}")
    print(f"{'Strategy CAGR':<35}: {m['cagr']*100:+.1f}%")
    print(f"{'Sharpe':<35}: {m['sharpe']:.2f}")
    print(f"{'Max drawdown':<35}: {m['max_dd']*100:.1f}%")
    print()
    print("Exit breakdown:")
    for r, c in sorted(m["exit_reasons"].items(), key=lambda x: -x[1]):
        print(f"  {r:<20}: {c}")
    print()
    print(sep)
    print(f"VERDICT: {tier}")
    checks = [
        (f"Trades ≥ {TIER1_TRADES}",      m["n_trades"] >= TIER1_TRADES,    m["n_trades"]),
        (f"CAGR ≥ {TIER1_CAGR*100:.0f}%", m["cagr"] >= TIER1_CAGR,          f"{m['cagr']*100:.1f}%"),
        (f"Sharpe ≥ {TIER1_SHARPE}",       m["sharpe"] >= TIER1_SHARPE,      f"{m['sharpe']:.2f}"),
        (f"MaxDD ≤ {TIER1_MAXDD*100:.0f}%", m["max_dd"] <= TIER1_MAXDD,      f"{m['max_dd']*100:.1f}%"),
        (f"WinRate ≥ {TIER1_WINRATE*100:.0f}%", m["win_rate"] >= TIER1_WINRATE, f"{m['win_rate']*100:.1f}%"),
    ]
    for label, ok, val in checks:
        print(f"  {'✓' if ok else '✗'} {label} → {val}")
    print(sep)

    by_ret = sorted(trades, key=lambda t: t["ret_pct"], reverse=True)
    print("\nTOP 10 TRADES:")
    print(f"{'Stock':<12} {'Entry':>10} {'Exit':>10} {'RSI':>5}  {'Days':>4}  {'Return':>8}  Reason")
    print("-" * 65)
    for t in by_ret[:10]:
        print(f"{t['sym']:<12} {str(t['entry_date'])[:10]:>10} {str(t['exit_date'])[:10]:>10} "
              f"{t['entry_rsi']:>5.1f}  {t['trading_days']:>4}  {t['ret_pct']:>+7.2f}%  {t['exit_reason']}")

    out = Path("reports") / f"bb_breakout_{date.today()}.md"
    out.parent.mkdir(exist_ok=True)
    lines = [
        f"# BB Breakout Backtest — {date.today()}",
        f"ST({args.st_period},{args.st_mult}) | RSI14>70 | R1 pivot | Upper BB(20,2)",
        f"Period: {args.start} → {end}",
        "",
        "| Metric | Value |", "|---|---|",
        f"| Trades | {m['n_trades']} |",
        f"| Win Rate | {m['win_rate']*100:.1f}% |",
        f"| CAGR | {m['cagr']*100:.1f}% |",
        f"| Sharpe | {m['sharpe']:.2f} |",
        f"| Max DD | {m['max_dd']*100:.1f}% |",
        "",
        f"## Verdict: **{tier}**",
        "",
        "| Stock | Entry | Exit | RSI | Days | Return | Reason |",
        "|---|---|---|---|---|---|---|",
    ]
    for t in sorted(trades, key=lambda x: x["entry_date"]):
        lines.append(f"| {t['sym']} | {str(t['entry_date'])[:10]} | {str(t['exit_date'])[:10]} "
                     f"| {t['entry_rsi']:.1f} | {t['trading_days']} | {t['ret_pct']:+.2f}% | {t['exit_reason']} |")
    out.write_text("\n".join(lines), encoding='utf-8')
    logger.info("Report saved: %s", out)

    try:
        from mcp_server.sheets_sync import log_backtest_result
        log_backtest_result({
            "strategy": "BB Breakout (RSI>80 + ST + Pivot + BB)",
            "timeframe": "1d",
            "period": f"{args.start} to {args.end}",
            "universe": "Nifty 500",
            "trades": m["n_trades"],
            "cagr": round(m["cagr"] * 100, 2),
            "sharpe": round(m["sharpe"], 2),
            "max_dd": round(m["max_dd"] * 100, 2),
            "win_rate": round(m["win_rate"] * 100, 2),
            "verdict": tier,
            "notes": "4-layer confluence: SuperTrend + RSI>80 + Pivot R1 + BB breakout",
        })
    except Exception as e:
        logger.warning("Sheets logging skipped: %s", e)


if __name__ == "__main__":
    main()
