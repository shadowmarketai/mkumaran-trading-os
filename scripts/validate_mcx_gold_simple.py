"""
MCX Gold Simple SMA Trend Validation

Hold gold whenever close > 50-day SMA, exit when close < 50-day SMA.
No crossover complexity, no time stop — pure trend following.

Prior run (20d/50d crossover): 10 trades, OVERRIDE.
This run targets capturing the full gold trend with minimal entry friction.

Pre-committed criteria: docs/strategy_validation/mcx_gold_simple_criteria.md

Usage:
    python scripts/validate_mcx_gold_simple.py
    python scripts/validate_mcx_gold_simple.py --sma-period 50
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("gold_simple")

SMA_PERIOD    = 50
HARD_STOP     = 0.04
POSITION_INR  = 1_000_000.0
BROKERAGE = 20.0
CTT       = 0.0001
EXCHANGE  = 0.00003
GST       = 0.18
SLIPPAGE  = 0.0005

TIER1_TRADES  = 5
TIER1_EXCESS  = 0.03
TIER1_SHARPE  = 0.7
TIER1_MAXDD   = 0.30
TIER2_TRADES  = 3
TIER2_EXCESS  = 0.0
TIER2_SHARPE  = 0.4
TIER2_MAXDD   = 0.40


def _load_gold_inr(start_str: str, end_str: str) -> dict[date, float]:
    try:
        import yfinance as yf
        import pandas as pd
        raw = yf.download(["GC=F", "INR=X"], start=start_str, end=end_str,
                          auto_adjust=True, progress=False)
        if raw.empty:
            return {}
        if isinstance(raw.columns, pd.MultiIndex):
            gold_usd = raw["Close"]["GC=F"].dropna()
            usd_inr  = raw["Close"]["INR=X"].dropna()
        else:
            return {}
        combined = pd.DataFrame({"gold": gold_usd, "fx": usd_inr}).dropna()
        combined["gold_inr"] = combined["gold"] * combined["fx"]
        result = {d.date(): float(v) for d, v in combined["gold_inr"].items()}
        logger.info("Gold INR: %d bars | ₹%.0f → ₹%.0f",
                    len(result), list(result.values())[0], list(result.values())[-1])
        return result
    except Exception as e:
        logger.error("Gold load failed: %s", e)
        return {}


def _sma(values: list[float], period: int) -> list[float]:
    out = [0.0] * (period - 1)
    for i in range(period - 1, len(values)):
        out.append(sum(values[i - period + 1 : i + 1]) / period)
    return out


def _cost(notional: float) -> float:
    sell = notional * (1 - SLIPPAGE)
    buy  = notional * (1 + SLIPPAGE)
    c = BROKERAGE * 2 + sell * CTT + (buy + sell) * EXCHANGE
    c += (BROKERAGE * 2 + (buy + sell) * EXCHANGE) * GST
    return c


def run_backtest(prices: dict[date, float], start: date, end: date, sma_period: int) -> list[dict]:
    all_dates  = sorted(prices.keys())
    all_closes = [prices[d] for d in all_dates]
    sma_vals   = _sma(all_closes, sma_period)

    bt_dates = [d for d in all_dates if start <= d <= end]
    trades: list[dict] = []
    pos = None

    for i_bt, today in enumerate(bt_dates):
        full_i = all_dates.index(today)
        if full_i < sma_period:
            continue

        close   = prices[today]
        sma_now = sma_vals[full_i]
        sma_prev = sma_vals[full_i - 1]

        if pos is not None:
            holding   = pos["days_held"] + 1
            hard_stop = pos["entry_px"] * (1 - HARD_STOP)
            exit_reason = None
            exit_px     = close

            if close <= hard_stop:
                exit_reason, exit_px = "hard_stop", hard_stop
            elif sma_now > 0 and close < sma_now:
                exit_reason = "sma_exit"

            if exit_reason:
                pnl = (exit_px - pos["entry_px"]) / pos["entry_px"] * POSITION_INR - _cost(POSITION_INR)
                trades.append({
                    "entry_date": pos["entry_day"], "exit_date": today,
                    "entry_px": round(pos["entry_px"], 2), "exit_px": round(exit_px, 2),
                    "trading_days": holding,
                    "net_pnl": round(pnl, 2),
                    "ret_pct": round(pnl / POSITION_INR * 100, 3),
                    "exit_reason": exit_reason,
                })
                pos = None
            else:
                pos["days_held"] = holding

        elif sma_prev > 0 and sma_now > 0 and sma_prev < prices[all_dates[full_i - 1]] and close > sma_now:
            # Fresh crossover above SMA (yesterday was below, today above)
            pos = {"entry_day": today, "entry_px": close, "days_held": 0}

    if pos is not None:
        last = prices.get(end, pos["entry_px"])
        pnl  = (last - pos["entry_px"]) / pos["entry_px"] * POSITION_INR - _cost(POSITION_INR)
        trades.append({
            "entry_date": pos["entry_day"], "exit_date": end,
            "entry_px": round(pos["entry_px"], 2), "exit_px": round(last, 2),
            "trading_days": pos["days_held"],
            "net_pnl": round(pnl, 2),
            "ret_pct": round(pnl / POSITION_INR * 100, 3),
            "exit_reason": "end_of_backtest",
        })

    return trades


def _metrics(trades: list[dict], prices: dict[date, float], start: date, end: date) -> dict:
    if not trades:
        return {}
    returns = [t["ret_pct"] / 100 for t in trades]
    n = len(trades)
    wins  = sum(1 for r in returns if r > 0)
    total = sum(returns)
    years = (end - start).days / 365.25
    cagr  = (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else -1.0
    dates_sorted = sorted(d for d in prices if start <= d <= end)
    p0 = prices.get(dates_sorted[0], 1) if dates_sorted else 1
    p1 = prices.get(dates_sorted[-1], 1) if dates_sorted else 1
    bench = (p1 / p0) ** (1 / max(years, 0.1)) - 1
    avg_hold = sum(t["trading_days"] for t in trades) / n
    mean_r = total / n
    std_r  = math.sqrt(sum((r - mean_r) ** 2 for r in returns) / max(n - 1, 1))
    sharpe = (mean_r / std_r) * math.sqrt(252 / max(avg_hold, 1)) if std_r > 0 else 0.0
    cum = peak = max_dd = 0.0
    for t in sorted(trades, key=lambda x: x["exit_date"]):
        cum  += t["net_pnl"]
        peak  = max(peak, cum)
        max_dd = max(max_dd, (peak - cum) / POSITION_INR)
    exit_reasons: dict[str, int] = {}
    for t in trades:
        exit_reasons[t["exit_reason"]] = exit_reasons.get(t["exit_reason"], 0) + 1
    return {
        "n_trades": n, "win_rate": wins / n, "cagr": cagr,
        "bench_cagr": bench, "excess_cagr": cagr - bench,
        "sharpe": sharpe, "max_dd": max_dd, "avg_hold": avg_hold,
        "total_pnl": sum(t["net_pnl"] for t in trades),
        "avg_ret_pct": mean_r * 100, "exit_reasons": exit_reasons,
    }


def _verdict(m: dict) -> str:
    if not m:
        return "OVERRIDE"
    if (m["n_trades"] >= TIER1_TRADES and m["excess_cagr"] >= TIER1_EXCESS
            and m["sharpe"] >= TIER1_SHARPE and m["max_dd"] <= TIER1_MAXDD):
        return "TIER_1"
    if (m["n_trades"] >= TIER2_TRADES and m["excess_cagr"] >= TIER2_EXCESS
            and m["sharpe"] >= TIER2_SHARPE and m["max_dd"] <= TIER2_MAXDD):
        return "TIER_2"
    return "OVERRIDE"


def main() -> None:
    parser = argparse.ArgumentParser(description="MCX Gold simple SMA trend backtest")
    parser.add_argument("--from",       dest="start",    default="2021-01-01")
    parser.add_argument("--to",         dest="end",      default=str(date.today()))
    parser.add_argument("--sma-period", type=int,        default=SMA_PERIOD)
    parser.add_argument("--stop-pct",   type=float,      default=HARD_STOP * 100)
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end   = date.fromisoformat(args.end)
    data_start = date(start.year - 1, start.month, 1)

    prices = _load_gold_inr(data_start.isoformat(), end.isoformat())
    if len(prices) < 100:
        logger.error("Insufficient Gold data")
        return

    trades = run_backtest(prices, start, end, args.sma_period)
    m      = _metrics(trades, prices, start, end)
    tier   = _verdict(m)

    sep = "=" * 62
    print()
    print(sep)
    print(f"MCX GOLD SIMPLE {args.sma_period}-DAY SMA TREND  |  {args.start} → {end}")
    print(sep)
    if not m:
        print("No trades.")
        return
    print(f"{'Trades':<30}: {m['n_trades']}  (prior: 10)")
    print(f"{'Win rate':<30}: {m['win_rate']*100:.1f}%")
    print(f"{'Avg hold (trading days)':<30}: {m['avg_hold']:.0f}")
    print(f"{'Total net P&L (₹)':<30}: {m['total_pnl']:,.0f}")
    print(f"{'Strategy CAGR':<30}: {m['cagr']*100:+.1f}%")
    print(f"{'Gold B&H CAGR':<30}: {m['bench_cagr']*100:+.1f}%")
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
        (f"Trades ≥ {TIER1_TRADES}",         m["n_trades"] >= TIER1_TRADES,     m["n_trades"]),
        (f"Excess CAGR ≥ {TIER1_EXCESS*100:.0f}%", m["excess_cagr"] >= TIER1_EXCESS, f"{m['excess_cagr']*100:.1f}%"),
        (f"Sharpe ≥ {TIER1_SHARPE}",          m["sharpe"] >= TIER1_SHARPE,       f"{m['sharpe']:.2f}"),
        (f"MaxDD ≤ {TIER1_MAXDD*100:.0f}%",   m["max_dd"] <= TIER1_MAXDD,        f"{m['max_dd']*100:.1f}%"),
    ]
    for label, ok, val in checks:
        print(f"  {'✓' if ok else '✗'} {label} → {val}")
    print(sep)
    print("\nAll trades:")
    for t in sorted(trades, key=lambda x: x["entry_date"]):
        print(f"  {str(t['entry_date'])[:10]} → {str(t['exit_date'])[:10]}  "
              f"₹{t['entry_px']:,.0f}→₹{t['exit_px']:,.0f}  {t['ret_pct']:+.2f}%  {t['exit_reason']}")

    out = Path("reports") / f"mcx_gold_simple_{date.today()}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(
        f"# MCX Gold Simple SMA{args.sma_period} — {date.today()}\n"
        f"| Metric | Value |\n|---|---|\n"
        f"| Trades | {m['n_trades']} |\n"
        f"| Excess CAGR | {m['excess_cagr']*100:.1f}% |\n"
        f"| Sharpe | {m['sharpe']:.2f} |\n"
        f"| Max DD | {m['max_dd']*100:.1f}% |\n\n"
        f"## Verdict: **{tier}**\n"
    )
    logger.info("Report saved: %s", out)


if __name__ == "__main__":
    main()
