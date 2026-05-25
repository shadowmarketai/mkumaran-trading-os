"""
52-Week Breakout Validation — Nifty 500

Buys when a stock closes above its 252-day high for the first time (fresh breakout).
Exits on trailing stop (close < 20-day low), -10% hard stop, or 63 trading days.

Pre-committed criteria: docs/strategy_validation/breakout_52w_criteria.md

Usage:
    python scripts/validate_52w_breakout.py
    python scripts/validate_52w_breakout.py --from 2021-01-01
    python scripts/validate_52w_breakout.py --hold-days 63 --trail-days 20
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
logger = logging.getLogger("breakout_52w")

# ── Constants ────────────────────────────────────────────────────────────────

LOOKBACK_HIGH   = 252   # 52-week high lookback
TRAIL_DAYS      = 20    # trailing stop = 20-day low
HARD_STOP_PCT   = 0.10  # -10% hard stop
MAX_HOLD_DAYS   = 63    # ~3 months
FRESH_DAYS      = 10    # ignore breakout if stock broke out in last N days
MAX_CONCURRENT  = 10
POSITION_INR    = 100_000.0
MIN_DATA_DAYS   = 750

BROKERAGE = 20.0
STT_SELL  = 0.001
EXCHANGE  = 0.0000345
GST       = 0.18
STAMP     = 0.00015
SLIPPAGE  = 0.0005

TIER1_TRADES  = 50
TIER1_CAGR    = 0.15
TIER1_SHARPE  = 0.8
TIER1_MAXDD   = 0.30
TIER1_WINRATE = 0.50
TIER2_TRADES  = 30
TIER2_CAGR    = 0.08
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


def _load_all_prices(symbols: list[str], start_str: str, end_str: str) -> dict[str, dict[date, float]]:
    import yfinance as yf

    prices: dict[str, dict[date, float]] = {}
    try:
        from sqlalchemy import text
        from mcp_server.db import engine
        logger.info("Loading %d symbols from ohlcv_cache...", len(symbols))
        with engine.connect() as conn:
            for sym in symbols:
                rows = conn.execute(
                    text("SELECT bar_date, close FROM ohlcv_cache "
                         "WHERE ticker=:s AND interval='1d' "
                         "AND bar_date BETWEEN :s0 AND :e "
                         "AND close IS NOT NULL AND close > 0 ORDER BY bar_date"),
                    {"s": sym, "s0": start_str, "e": end_str},
                ).fetchall()
                if len(rows) >= MIN_DATA_DAYS:
                    prices[sym] = {
                        (r.bar_date.date() if hasattr(r.bar_date, "date") else r.bar_date): float(r.close)
                        for r in rows
                    }
    except Exception as db_err:
        logger.warning("DB unavailable (%s) — using yfinance for all symbols", db_err.__class__.__name__)

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
                        closes = (raw["Close"][sym + ".NS"].dropna()
                                  if isinstance(raw.columns, pd.MultiIndex)
                                  else raw["Close"].dropna())
                        if len(closes) >= MIN_DATA_DAYS:
                            prices[sym] = {d.date(): float(c) for d, c in closes.items()}
                    except Exception:
                        pass
            except Exception as e:
                logger.warning("yfinance batch %d: %s", i, e)

    logger.info("Eligible stocks (≥%d days): %d", MIN_DATA_DAYS, len(prices))
    return prices


# ── Cost model ───────────────────────────────────────────────────────────────

def _round_trip_cost(pos_inr: float) -> float:
    buy = pos_inr * (1 + SLIPPAGE)
    sell = pos_inr * (1 - SLIPPAGE)
    cost = BROKERAGE * 2 + sell * STT_SELL + (buy + sell) * EXCHANGE
    cost += (BROKERAGE * 2 + (buy + sell) * EXCHANGE) * GST + buy * STAMP
    return cost


# ── Backtest ──────────────────────────────────────────────────────────────────

def run_backtest(
    prices_by_sym: dict[str, dict[date, float]],
    start: date, end: date,
    lookback_high: int, trail_days: int,
    hard_stop_pct: float, max_hold_days: int,
) -> list[dict]:
    # Pre-index each symbol's dates and closes in sorted order
    sym_index: dict[str, tuple[list[date], list[float]]] = {}
    for sym, pd_data in prices_by_sym.items():
        sym_dates = sorted(d for d in pd_data if d <= end)
        sym_closes = [pd_data[d] for d in sym_dates]
        if len(sym_dates) >= lookback_high + trail_days + 5:
            sym_index[sym] = (sym_dates, sym_closes)

    all_dates = sorted({d for pd_data in prices_by_sym.values() for d in pd_data if start <= d <= end})
    open_positions: list[dict] = []
    closed_trades:  list[dict] = []
    last_breakout: dict[str, date] = {}  # track last breakout date per symbol

    for today in all_dates:
        # ── Check exits ───────────────────────────────────────────────────
        still_open = []
        for pos in open_positions:
            sym           = pos["sym"]
            entry_px      = pos["entry_px"]
            trading_days  = pos["trading_days_held"] + 1
            sym_dates, sym_closes = sym_index.get(sym, ([], []))
            idx = next((i for i, d in enumerate(sym_dates) if d == today), None)

            if idx is None:
                pos["trading_days_held"] = trading_days
                still_open.append(pos)
                continue

            today_close = sym_closes[idx]
            hard_stop   = entry_px * (1 - hard_stop_pct)

            exit_reason = None
            exit_px     = today_close

            if today_close <= hard_stop:
                exit_reason, exit_px = "hard_stop", hard_stop
            elif trading_days >= max_hold_days:
                exit_reason = "time"
            elif idx >= trail_days:
                trail_low = min(sym_closes[idx - trail_days : idx])
                if today_close < trail_low:
                    exit_reason = "trail_stop"
                    exit_px     = trail_low

            if exit_reason:
                net_pnl = (exit_px - entry_px) / entry_px * POSITION_INR - _round_trip_cost(POSITION_INR)
                closed_trades.append({
                    "sym": sym, "entry_date": pos["entry_day"], "exit_date": today,
                    "entry_px": round(entry_px, 2), "exit_px": round(exit_px, 2),
                    "entry_52w_hi": round(pos["entry_52w_hi"], 2),
                    "trading_days": trading_days,
                    "net_pnl": round(net_pnl, 2),
                    "ret_pct": round(net_pnl / POSITION_INR * 100, 2),
                    "exit_reason": exit_reason,
                })
            else:
                pos["trading_days_held"] = trading_days
                still_open.append(pos)

        open_positions = still_open

        # ── Scan new breakouts ────────────────────────────────────────────
        slots = MAX_CONCURRENT - len(open_positions)
        if slots <= 0:
            continue

        already = {p["sym"] for p in open_positions}
        candidates: list[tuple[float, str, float, float]] = []  # (pct_above_hi, sym, close, hi)

        for sym, (sym_dates, sym_closes) in sym_index.items():
            if sym in already:
                continue
            idx = next((i for i, d in enumerate(sym_dates) if d == today), None)
            if idx is None or idx < lookback_high:
                continue

            today_close = sym_closes[idx]
            window      = sym_closes[idx - lookback_high : idx]
            if not window:
                continue

            hi_52w = max(window)

            # New 52-week high today
            if today_close <= hi_52w:
                continue

            # Fresh breakout: was it already a 52w high in the last FRESH_DAYS?
            recent_was_breakout = any(
                sym_closes[j] > max(sym_closes[max(0, j - lookback_high) : j])
                for j in range(max(1, idx - FRESH_DAYS), idx)
                if j >= lookback_high
            )
            if recent_was_breakout:
                continue

            pct_above = (today_close - hi_52w) / hi_52w
            candidates.append((pct_above, sym, today_close, hi_52w))

        # Sort: smallest breakout distance first (tightest breakout = least extended)
        candidates.sort(key=lambda x: x[0])
        for pct_above, sym, close_px, hi_52w in candidates[:slots]:
            open_positions.append({
                "sym": sym, "entry_day": today, "entry_px": close_px,
                "entry_52w_hi": hi_52w, "trading_days_held": 0,
            })
            last_breakout[sym] = today

    # Force-close remaining
    for pos in open_positions:
        sym = pos["sym"]
        last = prices_by_sym.get(sym, {}).get(end) or pos["entry_px"]
        net_pnl = (last - pos["entry_px"]) / pos["entry_px"] * POSITION_INR - _round_trip_cost(POSITION_INR)
        closed_trades.append({
            "sym": sym, "entry_date": pos["entry_day"], "exit_date": end,
            "entry_px": round(pos["entry_px"], 2), "exit_px": round(last, 2),
            "entry_52w_hi": round(pos["entry_52w_hi"], 2),
            "trading_days": pos["trading_days_held"],
            "net_pnl": round(net_pnl, 2),
            "ret_pct": round(net_pnl / POSITION_INR * 100, 2),
            "exit_reason": "end_of_backtest",
        })

    return closed_trades


# ── Metrics + verdict ─────────────────────────────────────────────────────────

def _metrics(trades: list[dict], start: date, end: date) -> dict:
    if not trades:
        return {}
    returns = [t["ret_pct"] / 100 for t in trades]
    n       = len(trades)
    wins    = sum(1 for r in returns if r > 0)
    total   = sum(returns)
    years   = (end - start).days / 365.25
    cagr    = (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else -1.0
    mean_r  = total / n
    std_r   = math.sqrt(sum((r - mean_r) ** 2 for r in returns) / max(n - 1, 1))
    sharpe  = (mean_r / std_r) * math.sqrt(252 / MAX_HOLD_DAYS) if std_r > 0 else 0.0
    ref     = float(MAX_CONCURRENT * POSITION_INR)
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
        "avg_hold": sum(t["trading_days"] for t in trades) / n,
        "avg_ret_pct": mean_r * 100, "exit_reasons": exit_reasons,
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
    parser = argparse.ArgumentParser(description="52-week breakout backtest")
    parser.add_argument("--from",       dest="start",         default="2021-01-01")
    parser.add_argument("--to",         dest="end",           default=str(date.today()))
    parser.add_argument("--hold-days",  type=int,             default=MAX_HOLD_DAYS)
    parser.add_argument("--trail-days", type=int,             default=TRAIL_DAYS)
    parser.add_argument("--stop-pct",   type=float,           default=HARD_STOP_PCT * 100)
    args = parser.parse_args()

    start      = date.fromisoformat(args.start)
    end        = date.fromisoformat(args.end)
    stop_pct   = args.stop_pct / 100.0
    data_start = date(start.year - 2, start.month, 1)  # extra history for 52w lookback

    symbols = _load_symbols()
    prices  = _load_all_prices(symbols, data_start.isoformat(), end.isoformat())

    nifty_cagr = 0.0
    try:
        import yfinance as yf
        df = yf.download("^NSEI", start=start.isoformat(), end=end.isoformat(),
                         auto_adjust=True, progress=False)
        if not df.empty:
            closes = df["Close"]
            if hasattr(getattr(closes, "columns", None), "__iter__"):
                closes = closes.iloc[:, 0]
            vals = list(closes.values)
            if vals[0] > 0:
                nifty_cagr = (vals[-1] / vals[0]) ** (1 / max((end - start).days / 365.25, 1)) - 1
    except Exception:
        pass

    logger.info("Backtest: %s → %s | 52w breakout | trail=%dd | SL=%.0f%% | hold=%dd",
                start, end, args.trail_days, args.stop_pct, args.hold_days)

    trades = run_backtest(prices, start, end, LOOKBACK_HIGH, args.trail_days,
                          stop_pct, args.hold_days)
    m      = _metrics(trades, start, end)
    tier   = _verdict(m)

    sep = "=" * 70
    print()
    print(sep)
    print(f"52-WEEK BREAKOUT BACKTEST  |  {args.start} → {end}")
    print(f"Trail stop: {args.trail_days}-day low | Hard SL: {args.stop_pct:.0f}% | Max hold: {args.hold_days}d")
    print(sep)

    if not m:
        print("No trades — check data.")
        return

    print(f"{'Universe stocks':<35}: {len(prices)}")
    print(f"{'Total trades':<35}: {m['n_trades']}")
    print(f"{'Win rate':<35}: {m['win_rate']*100:.1f}%")
    print(f"{'Avg holding (trading days)':<35}: {m['avg_hold']:.1f}")
    print(f"{'Avg return per trade':<35}: {m['avg_ret_pct']:+.2f}%")
    print(f"{'Total net P&L (₹)':<35}: {m['total_pnl']:,.0f}")
    print()
    print(f"{'Strategy CAGR':<35}: {m['cagr']*100:+.1f}%")
    print(f"{'Nifty 50 CAGR':<35}: {nifty_cagr*100:+.1f}%")
    print(f"{'Sharpe':<35}: {m['sharpe']:.2f}")
    print(f"{'Max drawdown':<35}: {m['max_dd']*100:.1f}%")
    print()
    print("Exit breakdown:")
    for reason, cnt in sorted(m["exit_reasons"].items(), key=lambda x: -x[1]):
        print(f"  {reason:<20}: {cnt}")
    print()
    print(sep)
    print(f"VERDICT: {tier}")
    print()
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
    print(f"{'Stock':<12} {'Entry':>10} {'Exit':>10} {'Days':>5}  {'Return':>8}  Reason")
    print("-" * 58)
    for t in by_ret[:10]:
        print(f"{t['sym']:<12} {str(t['entry_date'])[:10]:>10} {str(t['exit_date'])[:10]:>10} "
              f"{t['trading_days']:>5}  {t['ret_pct']:>+7.2f}%  {t['exit_reason']}")

    out = Path("reports") / f"breakout_52w_{date.today()}.md"
    out.parent.mkdir(exist_ok=True)
    lines = [
        f"# 52-Week Breakout Backtest — {date.today()}",
        f"Trail: {args.trail_days}-day low | SL: {args.stop_pct:.0f}% | Max hold: {args.hold_days}d",
        f"Period: {args.start} → {end}",
        "",
        "| Metric | Value | Nifty 50 |",
        "|---|---|---|",
        f"| Trades | {m['n_trades']} | — |",
        f"| Win Rate | {m['win_rate']*100:.1f}% | — |",
        f"| CAGR | {m['cagr']*100:.1f}% | {nifty_cagr*100:.1f}% |",
        f"| Sharpe | {m['sharpe']:.2f} | — |",
        f"| Max DD | {m['max_dd']*100:.1f}% | — |",
        "",
        f"## Verdict: **{tier}**",
        "",
        "| Stock | Entry | Exit | Days | Return | Reason |",
        "|---|---|---|---|---|---|",
    ]
    for t in sorted(trades, key=lambda x: x["entry_date"]):
        lines.append(f"| {t['sym']} | {str(t['entry_date'])[:10]} | {str(t['exit_date'])[:10]} "
                     f"| {t['trading_days']} | {t['ret_pct']:+.2f}% | {t['exit_reason']} |")
    out.write_text("\n".join(lines, encoding='utf-8'))
    logger.info("Report saved: %s", out)


if __name__ == "__main__":
    main()
