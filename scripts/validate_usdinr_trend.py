"""
USDINR Trend Following Validation

Donchian channel breakout on USDINR spot:
  - Long when close > 20-day high (breakout)
  - Exit when close < 10-day low (trailing channel)
  - Hard stop at -1.5% from entry

Pre-committed criteria: docs/strategy_validation/usdinr_trend_criteria.md

Usage:
    python scripts/validate_usdinr_trend.py
    python scripts/validate_usdinr_trend.py --from 2021-01-01
    python scripts/validate_usdinr_trend.py --entry-days 20 --exit-days 10
"""
from __future__ import annotations

import argparse
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
logger = logging.getLogger("usdinr_trend")

ENTRY_DAYS    = 20      # Donchian high window
EXIT_DAYS     = 10      # Donchian low window
HARD_STOP_PCT = 0.015   # -1.5% stop
POSITION_INR  = 1_000_000.0
FRESH_DAYS    = 5       # cooldown after exit before re-entering

# Costs (CDS currency futures)
BROKERAGE  = 20.0
EXCHANGE   = 0.0000045
GST        = 0.18
STAMP      = 0.00002
SLIPPAGE   = 0.0001

TIER1_TRADES     = 20
TIER1_EXCESS_CAGR = 0.08
TIER1_SHARPE     = 0.7
TIER1_MAXDD      = 0.20
TIER1_WINRATE    = 0.40
TIER2_TRADES     = 10
TIER2_EXCESS_CAGR = 0.03
TIER2_SHARPE     = 0.4
TIER2_MAXDD      = 0.30


def _load_usdinr(start_str: str, end_str: str) -> dict[date, float]:
    """Load USDINR from ohlcv_cache first, yfinance fallback."""
    prices: dict[date, float] = {}

    try:
        from sqlalchemy import text

        from mcp_server.db import engine
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT bar_date, close FROM ohlcv_cache "
                     "WHERE ticker IN ('USDINR', 'USDINR-I') AND interval='1d' "
                     "AND bar_date BETWEEN :s AND :e AND close > 0 ORDER BY bar_date"),
                {"s": start_str, "e": end_str},
            ).fetchall()
            if rows:
                prices = {
                    (r.bar_date.date() if hasattr(r.bar_date, "date") else r.bar_date): float(r.close)
                    for r in rows
                }
                logger.info("ohlcv_cache: %d USDINR bars", len(prices))
    except Exception as e:
        logger.debug("ohlcv_cache USDINR lookup: %s", e)

    if len(prices) < 100:
        try:
            import yfinance as yf
            df = yf.download("INR=X", start=start_str, end=end_str,
                             auto_adjust=True, progress=False)
            if not df.empty:
                closes = df["Close"]
                if hasattr(getattr(closes, "columns", None), "__iter__"):
                    closes = closes.iloc[:, 0]
                prices = {d.date(): float(c) for d, c in closes.items()}
                logger.info("yfinance INR=X: %d bars", len(prices))
        except Exception as e:
            logger.error("yfinance USDINR failed: %s", e)

    return prices


def _round_trip_cost(notional: float) -> float:
    cost = BROKERAGE * 2 + notional * EXCHANGE * 2
    cost += (BROKERAGE * 2 + notional * EXCHANGE * 2) * GST
    cost += notional * STAMP + notional * SLIPPAGE * 2
    return cost


def run_backtest(
    prices: dict[date, float],
    start: date, end: date,
    entry_days: int, exit_days: int, stop_pct: float,
) -> list[dict]:
    all_dates = sorted(d for d in prices if start <= d <= end)
    all_prices_sorted = sorted(prices.keys())

    trades: list[dict] = []
    pos = None  # None or dict with entry info
    last_exit: date | None = None

    for i, today in enumerate(all_dates):
        today_close = prices[today]

        # Build lookback using all data including pre-start
        full_idx = all_prices_sorted.index(today) if today in all_prices_sorted else -1
        if full_idx < max(entry_days, exit_days):
            continue

        high_window = [prices[all_prices_sorted[j]] for j in range(full_idx - entry_days, full_idx)]
        low_window  = [prices[all_prices_sorted[j]] for j in range(full_idx - exit_days, full_idx)]
        high_20 = max(high_window)
        low_10  = min(low_window)

        if pos is not None:
            entry_px   = pos["entry_px"]
            hard_stop  = entry_px * (1 - stop_pct)
            exit_reason = None
            exit_px     = today_close

            if today_close <= hard_stop:
                exit_reason, exit_px = "hard_stop", hard_stop
            elif today_close < low_10:
                exit_reason = "trail_exit"

            if exit_reason:
                pnl = (exit_px - entry_px) / entry_px * POSITION_INR - _round_trip_cost(POSITION_INR)
                trades.append({
                    "entry_date": pos["entry_day"], "exit_date": today,
                    "entry_px": round(entry_px, 4), "exit_px": round(exit_px, 4),
                    "trading_days": (today - pos["entry_day"]).days,
                    "net_pnl": round(pnl, 2),
                    "ret_pct": round(pnl / POSITION_INR * 100, 3),
                    "exit_reason": exit_reason,
                })
                pos = None
                last_exit = today

        elif today_close > high_20:
            # Cooldown check
            if last_exit and (today - last_exit).days < FRESH_DAYS:
                continue
            pos = {"entry_day": today, "entry_px": today_close}

    # Force-close
    if pos is not None:
        last_close = prices.get(end, pos["entry_px"])
        pnl = (last_close - pos["entry_px"]) / pos["entry_px"] * POSITION_INR - _round_trip_cost(POSITION_INR)
        trades.append({
            "entry_date": pos["entry_day"], "exit_date": end,
            "entry_px": round(pos["entry_px"], 4), "exit_px": round(last_close, 4),
            "trading_days": (end - pos["entry_day"]).days,
            "net_pnl": round(pnl, 2),
            "ret_pct": round(pnl / POSITION_INR * 100, 3),
            "exit_reason": "end_of_backtest",
        })

    return trades


def _metrics(trades: list[dict], prices: dict[date, float], start: date, end: date) -> dict:
    if not trades:
        return {}
    returns = [t["ret_pct"] / 100 for t in trades]
    n     = len(trades)
    wins  = sum(1 for r in returns if r > 0)
    total = sum(returns)
    years = (end - start).days / 365.25
    cagr  = (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else -1.0

    # Benchmark: USDINR buy-and-hold
    dates_sorted = sorted(d for d in prices if start <= d <= end)
    p0 = prices.get(dates_sorted[0], 1) if dates_sorted else 1
    p1 = prices.get(dates_sorted[-1], 1) if dates_sorted else 1
    bench_cagr = (p1 / p0) ** (1 / max(years, 0.1)) - 1
    excess_cagr = cagr - bench_cagr

    mean_r = total / n
    std_r  = math.sqrt(sum((r - mean_r) ** 2 for r in returns) / max(n - 1, 1))
    sharpe = (mean_r / std_r) * math.sqrt(252 / 15) if std_r > 0 else 0.0

    ref    = POSITION_INR
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
        "bench_cagr": bench_cagr, "excess_cagr": excess_cagr,
        "sharpe": sharpe, "max_dd": max_dd,
        "total_pnl": sum(t["net_pnl"] for t in trades),
        "avg_hold": sum(t["trading_days"] for t in trades) / n,
        "avg_ret_pct": mean_r * 100, "exit_reasons": exit_reasons,
    }


def _verdict(m: dict) -> str:
    if not m:
        return "OVERRIDE"
    if (m["n_trades"] >= TIER1_TRADES and m["excess_cagr"] >= TIER1_EXCESS_CAGR
            and m["sharpe"] >= TIER1_SHARPE and m["max_dd"] <= TIER1_MAXDD
            and m["win_rate"] >= TIER1_WINRATE):
        return "TIER_1"
    if (m["n_trades"] >= TIER2_TRADES and m["excess_cagr"] >= TIER2_EXCESS_CAGR
            and m["sharpe"] >= TIER2_SHARPE and m["max_dd"] <= TIER2_MAXDD):
        return "TIER_2"
    return "OVERRIDE"


def main() -> None:
    parser = argparse.ArgumentParser(description="USDINR trend following backtest")
    parser.add_argument("--from",        dest="start",      default="2021-01-01")
    parser.add_argument("--to",          dest="end",        default=str(date.today()))
    parser.add_argument("--entry-days",  type=int,          default=ENTRY_DAYS)
    parser.add_argument("--exit-days",   type=int,          default=EXIT_DAYS)
    parser.add_argument("--stop-pct",    type=float,        default=HARD_STOP_PCT * 100)
    args = parser.parse_args()

    start     = date.fromisoformat(args.start)
    end       = date.fromisoformat(args.end)
    stop_pct  = args.stop_pct / 100.0
    data_start = date(start.year - 1, start.month, 1)

    prices = _load_usdinr(data_start.isoformat(), end.isoformat())
    if len(prices) < 100:
        logger.error("Insufficient USDINR data (%d bars)", len(prices))
        return

    logger.info("USDINR: %d bars | %s → %s | Entry: %d-day high | Exit: %d-day low",
                len(prices), min(prices), max(prices), args.entry_days, args.exit_days)

    trades = run_backtest(prices, start, end, args.entry_days, args.exit_days, stop_pct)
    m      = _metrics(trades, prices, start, end)
    tier   = _verdict(m)

    sep = "=" * 65
    print()
    print(sep)
    print(f"USDINR TREND FOLLOWING  |  {args.start} → {end}")
    print(f"Donchian {args.entry_days}-day entry / {args.exit_days}-day exit | SL -{args.stop_pct:.1f}%")
    print(sep)

    if not m:
        print("No trades generated.")
        return

    print(f"{'Trades':<30}: {m['n_trades']}")
    print(f"{'Win rate':<30}: {m['win_rate']*100:.1f}%")
    print(f"{'Avg hold (calendar days)':<30}: {m['avg_hold']:.0f}")
    print(f"{'Avg return per trade':<30}: {m['avg_ret_pct']:+.3f}%")
    print(f"{'Total net P&L (₹)':<30}: {m['total_pnl']:,.0f}")
    print()
    print(f"{'Strategy CAGR':<30}: {m['cagr']*100:+.1f}%")
    print(f"{'Benchmark CAGR (B&H)':<30}: {m['bench_cagr']*100:+.1f}%")
    print(f"{'Excess CAGR':<30}: {m['excess_cagr']*100:+.1f}%")
    print(f"{'Sharpe':<30}: {m['sharpe']:.2f}")
    print(f"{'Max drawdown':<30}: {m['max_dd']*100:.1f}%")
    print()
    print("Exit breakdown:")
    for r, c in sorted(m["exit_reasons"].items(), key=lambda x: -x[1]):
        print(f"  {r:<20}: {c}")
    print()
    print(sep)
    print(f"VERDICT: {tier}")
    checks = [
        (f"Trades ≥ {TIER1_TRADES}",         m["n_trades"] >= TIER1_TRADES,            m["n_trades"]),
        (f"Excess CAGR ≥ {TIER1_EXCESS_CAGR*100:.0f}%", m["excess_cagr"] >= TIER1_EXCESS_CAGR, f"{m['excess_cagr']*100:.1f}%"),
        (f"Sharpe ≥ {TIER1_SHARPE}",          m["sharpe"] >= TIER1_SHARPE,              f"{m['sharpe']:.2f}"),
        (f"MaxDD ≤ {TIER1_MAXDD*100:.0f}%",   m["max_dd"] <= TIER1_MAXDD,               f"{m['max_dd']*100:.1f}%"),
        (f"WinRate ≥ {TIER1_WINRATE*100:.0f}%", m["win_rate"] >= TIER1_WINRATE,         f"{m['win_rate']*100:.1f}%"),
    ]
    for label, ok, val in checks:
        print(f"  {'✓' if ok else '✗'} {label} → {val}")
    print(sep)

    by_ret = sorted(trades, key=lambda t: t["ret_pct"], reverse=True)
    print("\nTOP 5 TRADES:")
    for t in by_ret[:5]:
        print(f"  {str(t['entry_date'])[:10]} → {str(t['exit_date'])[:10]}  "
              f"{t['entry_px']:.4f}→{t['exit_px']:.4f}  {t['ret_pct']:+.3f}%  {t['exit_reason']}")
    print("\nBOTTOM 5 TRADES:")
    for t in by_ret[-5:]:
        print(f"  {str(t['entry_date'])[:10]} → {str(t['exit_date'])[:10]}  "
              f"{t['entry_px']:.4f}→{t['exit_px']:.4f}  {t['ret_pct']:+.3f}%  {t['exit_reason']}")

    out = Path("reports") / f"usdinr_trend_{date.today()}.md"
    out.parent.mkdir(exist_ok=True)
    lines = [
        f"# USDINR Trend Following — {date.today()}",
        f"Donchian {args.entry_days}d/{args.exit_days}d | SL {args.stop_pct:.1f}% | {args.start} → {end}",
        "",
        "| Metric | Value |", "|---|---|",
        f"| Trades | {m['n_trades']} |",
        f"| Win Rate | {m['win_rate']*100:.1f}% |",
        f"| Strategy CAGR | {m['cagr']*100:.1f}% |",
        f"| Benchmark CAGR | {m['bench_cagr']*100:.1f}% |",
        f"| Excess CAGR | {m['excess_cagr']*100:.1f}% |",
        f"| Sharpe | {m['sharpe']:.2f} |",
        f"| Max DD | {m['max_dd']*100:.1f}% |",
        "",
        f"## Verdict: **{tier}**",
    ]
    out.write_text("\n".join(lines), encoding='utf-8')
    logger.info("Report saved: %s", out)


if __name__ == "__main__":
    main()
