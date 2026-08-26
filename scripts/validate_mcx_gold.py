"""
MCX Gold Momentum Validation

Long-only trend strategy on Gold (INR-denominated):
  - Trend filter: close > 50-day SMA
  - Entry: price crosses above 20-day SMA (while above 50-day)
  - Exit: close < 20-day trailing low OR -4% hard stop OR 30-day time stop

Prices: yfinance GC=F (USD) × INR=X (USD/INR) → Gold in INR per troy oz

Pre-committed criteria: docs/strategy_validation/mcx_gold_criteria.md

Usage:
    python scripts/validate_mcx_gold.py
    python scripts/validate_mcx_gold.py --from 2021-01-01
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
logger = logging.getLogger("mcx_gold")

MA_TREND     = 50
MA_ENTRY     = 20
TRAIL_DAYS   = 20
HARD_STOP    = 0.04   # -4%
MAX_HOLD     = 30     # trading days
POSITION_INR = 1_000_000.0

# Costs (MCX commodity futures)
BROKERAGE = 20.0
CTT       = 0.0001    # 0.01% on sell
EXCHANGE  = 0.00003
GST       = 0.18
SLIPPAGE  = 0.0005

TIER1_TRADES  = 15
TIER1_EXCESS  = 0.05
TIER1_SHARPE  = 0.7
TIER1_MAXDD   = 0.25
TIER1_WINRATE = 0.45
TIER2_TRADES  = 8
TIER2_EXCESS  = 0.02
TIER2_SHARPE  = 0.4
TIER2_MAXDD   = 0.35


def _load_gold_inr(start_str: str, end_str: str) -> dict[date, float]:
    """Gold price in INR = COMEX Gold (USD/oz) × USDINR rate."""
    try:
        import pandas as pd
        import yfinance as yf

        raw = yf.download(["GC=F", "INR=X"], start=start_str, end=end_str,
                          auto_adjust=True, progress=False)
        if raw.empty:
            return {}

        if isinstance(raw.columns, pd.MultiIndex):
            gold_usd = raw["Close"]["GC=F"].dropna()
            usd_inr  = raw["Close"]["INR=X"].dropna()
        else:
            logger.warning("Unexpected column structure from yfinance dual download")
            return {}

        combined = pd.DataFrame({"gold": gold_usd, "fx": usd_inr}).dropna()
        combined["gold_inr"] = combined["gold"] * combined["fx"]

        result = {d.date(): float(v) for d, v in combined["gold_inr"].items()}
        logger.info("Gold INR: %d bars (GC=F × INR=X)", len(result))
        return result

    except Exception as e:
        logger.error("Gold INR load failed: %s", e)
        return {}


def _sma(values: list[float], period: int) -> list[float]:
    out = [0.0] * (period - 1)
    for i in range(period - 1, len(values)):
        out.append(sum(values[i - period + 1 : i + 1]) / period)
    return out


def _round_trip_cost(notional: float) -> float:
    sell = notional * (1 - SLIPPAGE)
    buy  = notional * (1 + SLIPPAGE)
    cost = BROKERAGE * 2 + sell * CTT + (buy + sell) * EXCHANGE
    cost += (BROKERAGE * 2 + (buy + sell) * EXCHANGE) * GST
    return cost


def run_backtest(
    prices: dict[date, float], start: date, end: date,
    ma_trend: int, ma_entry: int, trail_days: int,
    hard_stop: float, max_hold: int,
) -> list[dict]:
    all_dates    = sorted(prices.keys())
    all_closes   = [prices[d] for d in all_dates]
    sma_trend    = _sma(all_closes, ma_trend)
    sma_entry    = _sma(all_closes, ma_entry)

    bt_dates = [d for d in all_dates if start <= d <= end]
    trades: list[dict] = []
    pos = None

    for i_bt, today in enumerate(bt_dates):
        full_i = all_dates.index(today)
        if full_i < max(ma_trend, trail_days) + 1:
            continue

        close      = prices[today]
        sma_t_now  = sma_trend[full_i]
        sma_e_now  = sma_entry[full_i]
        sma_e_prev = sma_entry[full_i - 1]

        if pos is not None:
            holding     = pos["trading_days_held"] + 1
            entry_px    = pos["entry_px"]
            hard_stop_px = entry_px * (1 - hard_stop)
            trail_low   = min(all_closes[max(0, full_i - trail_days) : full_i])

            exit_reason = None
            exit_px     = close

            if close <= hard_stop_px:
                exit_reason, exit_px = "hard_stop", hard_stop_px
            elif close < trail_low:
                exit_reason = "trail_stop"
            elif close < sma_t_now:  # trend broken
                exit_reason = "trend_break"
            elif holding >= max_hold:
                exit_reason = "time"

            if exit_reason:
                pnl = (exit_px - entry_px) / entry_px * POSITION_INR - _round_trip_cost(POSITION_INR)
                trades.append({
                    "entry_date": pos["entry_day"], "exit_date": today,
                    "entry_px": round(entry_px, 2), "exit_px": round(exit_px, 2),
                    "trading_days": holding,
                    "net_pnl": round(pnl, 2),
                    "ret_pct": round(pnl / POSITION_INR * 100, 3),
                    "exit_reason": exit_reason,
                })
                pos = None
            else:
                pos["trading_days_held"] = holding

        elif (sma_t_now > 0 and close > sma_t_now
              and sma_e_prev > 0 and sma_e_now > 0
              and sma_e_prev <= sma_t_now and sma_e_now > sma_t_now):
            # 20-day SMA crosses above 50-day SMA while price above 50-day
            pos = {"entry_day": today, "entry_px": close, "trading_days_held": 0}

    if pos is not None:
        last = prices.get(end, pos["entry_px"])
        pnl  = (last - pos["entry_px"]) / pos["entry_px"] * POSITION_INR - _round_trip_cost(POSITION_INR)
        trades.append({
            "entry_date": pos["entry_day"], "exit_date": end,
            "entry_px": round(pos["entry_px"], 2), "exit_px": round(last, 2),
            "trading_days": pos["trading_days_held"],
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

    dates_sorted = sorted(d for d in prices if start <= d <= end)
    p0 = prices.get(dates_sorted[0], 1) if dates_sorted else 1
    p1 = prices.get(dates_sorted[-1], 1) if dates_sorted else 1
    bench_cagr  = (p1 / p0) ** (1 / max(years, 0.1)) - 1
    excess_cagr = cagr - bench_cagr

    mean_r = total / n
    std_r  = math.sqrt(sum((r - mean_r) ** 2 for r in returns) / max(n - 1, 1))
    sharpe = (mean_r / std_r) * math.sqrt(252 / max_hold_for_sharpe(trades)) if std_r > 0 else 0.0

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


def max_hold_for_sharpe(trades: list[dict]) -> float:
    if not trades:
        return 20.0
    return max(sum(t["trading_days"] for t in trades) / len(trades), 1.0)


def _verdict(m: dict) -> str:
    if not m:
        return "OVERRIDE"
    if (m["n_trades"] >= TIER1_TRADES and m["excess_cagr"] >= TIER1_EXCESS
            and m["sharpe"] >= TIER1_SHARPE and m["max_dd"] <= TIER1_MAXDD
            and m["win_rate"] >= TIER1_WINRATE):
        return "TIER_1"
    if (m["n_trades"] >= TIER2_TRADES and m["excess_cagr"] >= TIER2_EXCESS
            and m["sharpe"] >= TIER2_SHARPE and m["max_dd"] <= TIER2_MAXDD):
        return "TIER_2"
    return "OVERRIDE"


def main() -> None:
    parser = argparse.ArgumentParser(description="MCX Gold momentum backtest")
    parser.add_argument("--from",       dest="start",    default="2021-01-01")
    parser.add_argument("--to",         dest="end",      default=str(date.today()))
    parser.add_argument("--ma-trend",   type=int,        default=MA_TREND)
    parser.add_argument("--ma-entry",   type=int,        default=MA_ENTRY)
    parser.add_argument("--stop-pct",   type=float,      default=HARD_STOP * 100)
    args = parser.parse_args()

    start     = date.fromisoformat(args.start)
    end       = date.fromisoformat(args.end)
    hard_stop = args.stop_pct / 100.0
    data_start = date(start.year - 1, start.month, 1)

    prices = _load_gold_inr(data_start.isoformat(), end.isoformat())
    if len(prices) < 100:
        logger.error("Insufficient Gold INR data (%d bars)", len(prices))
        return

    logger.info("Gold INR: %d bars | range ₹%.0f–₹%.0f", len(prices),
                min(prices.values()), max(prices.values()))

    trades = run_backtest(prices, start, end, args.ma_trend, args.ma_entry,
                          TRAIL_DAYS, hard_stop, MAX_HOLD)
    m      = _metrics(trades, prices, start, end)
    tier   = _verdict(m)

    sep = "=" * 65
    print()
    print(sep)
    print(f"MCX GOLD MOMENTUM  |  {args.start} → {end}")
    print(f"Trend: {args.ma_trend}-day SMA | Entry: {args.ma_entry}-day cross | SL -{args.stop_pct:.0f}%")
    print(sep)

    if not m:
        print("No trades generated.")
        return

    print(f"{'Trades':<30}: {m['n_trades']}")
    print(f"{'Win rate':<30}: {m['win_rate']*100:.1f}%")
    print(f"{'Avg hold (trading days)':<30}: {m['avg_hold']:.0f}")
    print(f"{'Avg return per trade':<30}: {m['avg_ret_pct']:+.3f}%")
    print(f"{'Total net P&L (₹)':<30}: {m['total_pnl']:,.0f}")
    print()
    print(f"{'Strategy CAGR':<30}: {m['cagr']*100:+.1f}%")
    print(f"{'Gold buy-and-hold CAGR':<30}: {m['bench_cagr']*100:+.1f}%")
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
        (f"Trades ≥ {TIER1_TRADES}",        m["n_trades"] >= TIER1_TRADES,      m["n_trades"]),
        (f"Excess CAGR ≥ {TIER1_EXCESS*100:.0f}%", m["excess_cagr"] >= TIER1_EXCESS, f"{m['excess_cagr']*100:.1f}%"),
        (f"Sharpe ≥ {TIER1_SHARPE}",         m["sharpe"] >= TIER1_SHARPE,        f"{m['sharpe']:.2f}"),
        (f"MaxDD ≤ {TIER1_MAXDD*100:.0f}%",  m["max_dd"] <= TIER1_MAXDD,         f"{m['max_dd']*100:.1f}%"),
        (f"WinRate ≥ {TIER1_WINRATE*100:.0f}%", m["win_rate"] >= TIER1_WINRATE,  f"{m['win_rate']*100:.1f}%"),
    ]
    for label, ok, val in checks:
        print(f"  {'✓' if ok else '✗'} {label} → {val}")
    print(sep)

    by_ret = sorted(trades, key=lambda t: t["ret_pct"], reverse=True)
    print("\nTOP 5 TRADES:")
    for t in by_ret[:5]:
        print(f"  {str(t['entry_date'])[:10]} → {str(t['exit_date'])[:10]}  "
              f"₹{t['entry_px']:,.0f}→₹{t['exit_px']:,.0f}  {t['ret_pct']:+.2f}%  {t['exit_reason']}")

    out = Path("reports") / f"mcx_gold_{date.today()}.md"
    out.parent.mkdir(exist_ok=True)
    lines = [
        f"# MCX Gold Momentum — {date.today()}",
        f"SMA{args.ma_trend}/{args.ma_entry} | SL {args.stop_pct:.0f}% | {args.start} → {end}",
        "",
        "| Metric | Value |", "|---|---|",
        f"| Trades | {m['n_trades']} |",
        f"| Win Rate | {m['win_rate']*100:.1f}% |",
        f"| Strategy CAGR | {m['cagr']*100:.1f}% |",
        f"| Gold B&H CAGR | {m['bench_cagr']*100:.1f}% |",
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
