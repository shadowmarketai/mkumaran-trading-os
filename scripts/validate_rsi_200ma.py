"""
RSI Mean-Reversion + 200-Day MA Filter

Same as validate_rsi_meanreversion.py but adds one gate at entry:
  stock close must be ABOVE its 200-day simple moving average.

This filters "strong stock having a pullback" from "weak stock in downtrend."
Prior run without filter: 23.8% win rate, -3.36% avg return (OVERRIDE).

Pre-committed criteria: docs/strategy_validation/rsi_200ma_criteria.md

Usage:
    python scripts/validate_rsi_200ma.py
    python scripts/validate_rsi_200ma.py --from 2021-01-01
    python scripts/validate_rsi_200ma.py --ma-period 200 --rsi-entry 30
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("rsi_200ma")

# ── Constants (match criteria doc) ──────────────────────────────────────────

RSI_PERIOD     = 14
RSI_ENTRY      = 30.0
RSI_EXIT       = 50.0
HOLD_DAYS      = 10
STOP_PCT       = 0.07
MA_PERIOD      = 200
MAX_CONCURRENT = 5
POSITION_INR   = 100_000.0
MIN_DATA_DAYS  = 750

BROKERAGE  = 20.0
STT_SELL   = 0.001
EXCHANGE   = 0.0000345
GST        = 0.18
STAMP      = 0.00015
SLIPPAGE   = 0.0005

TIER1_TRADES  = 30
TIER1_CAGR    = 0.12
TIER1_SHARPE  = 0.8
TIER1_MAXDD   = 0.25
TIER1_WINRATE = 0.55
TIER2_TRADES  = 20
TIER2_CAGR    = 0.06
TIER2_SHARPE  = 0.5
TIER2_MAXDD   = 0.35
TIER2_WINRATE = 0.50


# ── Data loading ─────────────────────────────────────────────────────────────

def _load_symbols() -> list[str]:
    p = Path("data/nifty500.json")
    if not p.exists():
        p = Path(__file__).parent.parent / "data" / "nifty500.json"
    with open(p) as f:
        return json.load(f)["symbols"]


def _load_all_prices(symbols: list[str], start_str: str, end_str: str) -> dict[str, dict[date, float]]:
    import yfinance as yf
    from sqlalchemy import text
    from mcp_server.db import engine

    prices: dict[str, dict[date, float]] = {}
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


# ── Indicators ───────────────────────────────────────────────────────────────

def _compute_rsi(closes: list[float], period: int = RSI_PERIOD) -> list[float]:
    if len(closes) <= period:
        return [50.0] * len(closes)
    rsi = [50.0] * period
    gains  = [max(closes[i] - closes[i-1], 0.0) for i in range(1, len(closes))]
    losses = [max(closes[i-1] - closes[i], 0.0) for i in range(1, len(closes))]
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
        rsi.append(100.0 if avg_l == 0 else 100.0 - 100.0 / (1.0 + avg_g / avg_l))
    return rsi


def _compute_sma(closes: list[float], period: int) -> list[float]:
    """Simple moving average. First (period-1) values = NaN (0.0 placeholder)."""
    sma = [0.0] * (period - 1)
    for i in range(period - 1, len(closes)):
        sma.append(sum(closes[i - period + 1 : i + 1]) / period)
    return sma


# ── Cost model ────────────────────────────────────────────────────────────────

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
    rsi_entry: float, rsi_exit: float,
    hold_days: int, stop_pct: float, ma_period: int,
) -> list[dict]:
    # Pre-compute RSI and SMA for each stock
    rsi_by_sym: dict[str, dict[date, float]] = {}
    sma_by_sym: dict[str, dict[date, float]] = {}
    date_prices: dict[str, tuple[list[date], list[float]]] = {}

    for sym, pd_data in prices_by_sym.items():
        sym_dates = sorted(d for d in pd_data if d <= end)
        sym_closes = [pd_data[d] for d in sym_dates]
        if len(sym_dates) < max(RSI_PERIOD, ma_period) + 2:
            continue
        rsi_vals = _compute_rsi(sym_closes)
        sma_vals = _compute_sma(sym_closes, ma_period)
        rsi_by_sym[sym] = dict(zip(sym_dates, rsi_vals))
        sma_by_sym[sym] = dict(zip(sym_dates, sma_vals))
        date_prices[sym] = (sym_dates, sym_closes)

    all_dates = sorted({d for pd_data in prices_by_sym.values() for d in pd_data if start <= d <= end})
    open_positions: list[dict] = []
    closed_trades:  list[dict] = []

    for today in all_dates:
        # Check exits
        still_open = []
        for pos in open_positions:
            sym = pos["sym"]
            today_close = prices_by_sym.get(sym, {}).get(today)
            trading_days_held = pos["trading_days_held"] + 1
            if today_close is None:
                pos["trading_days_held"] = trading_days_held
                still_open.append(pos)
                continue

            today_rsi = rsi_by_sym.get(sym, {}).get(today, 50.0)
            stop_price = pos["entry_px"] * (1 - stop_pct)

            exit_reason = None
            exit_px = today_close
            if today_close <= stop_price:
                exit_reason, exit_px = "stop", stop_price
            elif today_rsi > rsi_exit:
                exit_reason = "rsi_exit"
            elif trading_days_held >= hold_days:
                exit_reason = "time"

            if exit_reason:
                net_pnl = (exit_px - pos["entry_px"]) / pos["entry_px"] * POSITION_INR - _round_trip_cost(POSITION_INR)
                closed_trades.append({
                    "sym": sym, "entry_date": pos["entry_day"], "exit_date": today,
                    "entry_px": round(pos["entry_px"], 2), "exit_px": round(exit_px, 2),
                    "entry_rsi": round(pos["entry_rsi"], 1),
                    "above_ma": pos["above_ma"],
                    "trading_days": trading_days_held,
                    "net_pnl": round(net_pnl, 2),
                    "ret_pct": round(net_pnl / POSITION_INR * 100, 2),
                    "exit_reason": exit_reason,
                })
            else:
                pos["trading_days_held"] = trading_days_held
                still_open.append(pos)
        open_positions = still_open

        # Scan new entries
        slots = MAX_CONCURRENT - len(open_positions)
        if slots <= 0:
            continue

        already = {p["sym"] for p in open_positions}
        candidates: list[tuple[float, str, float, float]] = []

        for sym, rsi_map in rsi_by_sym.items():
            if sym in already:
                continue
            today_rsi = rsi_map.get(today)
            if today_rsi is None or today_rsi >= rsi_entry:
                continue

            sym_dates, _ = date_prices.get(sym, ([], []))
            idx = next((i for i, d in enumerate(sym_dates) if d == today), None)
            if idx is None or idx == 0:
                continue
            if rsi_by_sym[sym].get(sym_dates[idx - 1], 50.0) < rsi_entry:
                continue  # not a fresh crossover

            today_close = prices_by_sym[sym].get(today)
            if not today_close or today_close <= 0:
                continue

            # ── 200-day MA filter ─────────────────────────────────────────
            today_sma = sma_by_sym.get(sym, {}).get(today, 0.0)
            above_ma  = today_sma > 0 and today_close > today_sma
            if not above_ma:
                continue  # stock below MA — skip

            candidates.append((today_rsi, sym, today_close, today_sma))

        candidates.sort(key=lambda x: x[0])
        for rsi_val, sym, close_px, sma_val in candidates[:slots]:
            open_positions.append({
                "sym": sym, "entry_day": today, "entry_px": close_px,
                "entry_rsi": rsi_val, "above_ma": True,
                "trading_days_held": 0,
            })

    # Force-close remaining
    for pos in open_positions:
        sym = pos["sym"]
        last = prices_by_sym.get(sym, {}).get(end) or pos["entry_px"]
        net_pnl = (last - pos["entry_px"]) / pos["entry_px"] * POSITION_INR - _round_trip_cost(POSITION_INR)
        closed_trades.append({
            "sym": sym, "entry_date": pos["entry_day"], "exit_date": end,
            "entry_px": round(pos["entry_px"], 2), "exit_px": round(last, 2),
            "entry_rsi": round(pos["entry_rsi"], 1), "above_ma": pos["above_ma"],
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
    sharpe  = (mean_r / std_r) * math.sqrt(252 / 10) if std_r > 0 else 0.0
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
    parser = argparse.ArgumentParser(description="RSI + 200-day MA mean-reversion backtest")
    parser.add_argument("--from",      dest="start",    default="2021-01-01")
    parser.add_argument("--to",        dest="end",      default=str(date.today()))
    parser.add_argument("--rsi-entry", type=float,      default=RSI_ENTRY)
    parser.add_argument("--rsi-exit",  type=float,      default=RSI_EXIT)
    parser.add_argument("--hold-days", type=int,        default=HOLD_DAYS)
    parser.add_argument("--stop-pct",  type=float,      default=STOP_PCT * 100)
    parser.add_argument("--ma-period", type=int,        default=MA_PERIOD)
    args = parser.parse_args()

    start    = date.fromisoformat(args.start)
    end      = date.fromisoformat(args.end)
    stop_pct = args.stop_pct / 100.0
    data_start = date(start.year - 2, start.month, 1)  # extra year for 200-day MA warm-up

    symbols = _load_symbols()
    prices  = _load_all_prices(symbols, data_start.isoformat(), end.isoformat())

    # Nifty 50 benchmark
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

    logger.info("Backtest: %s → %s | RSI<%s + close>%d-day SMA | hold=%dd | SL=%.0f%%",
                start, end, args.rsi_entry, args.ma_period, args.hold_days, args.stop_pct)

    trades = run_backtest(prices, start, end, args.rsi_entry, args.rsi_exit,
                          args.hold_days, stop_pct, args.ma_period)
    m      = _metrics(trades, start, end)
    tier   = _verdict(m)

    sep = "=" * 70
    print()
    print(sep)
    print(f"RSI + {args.ma_period}-DAY MA FILTER BACKTEST  |  {args.start} → {end}")
    print(f"Entry: RSI<{args.rsi_entry} AND close>{args.ma_period}d SMA")
    print(f"Exit: RSI>{args.rsi_exit} OR {args.hold_days}d OR SL-{args.stop_pct:.0f}%")
    print(sep)

    if not m:
        print("No trades — check data.")
        return

    prev_wr   = 23.8  # prior run without filter
    prev_cagr = -100.0
    print(f"{'Universe stocks':<35}: {len(prices)}")
    print(f"{'Total trades':<35}: {m['n_trades']}  (prior: 797)")
    print(f"{'Win rate':<35}: {m['win_rate']*100:.1f}%  (prior: {prev_wr}%)")
    print(f"{'Avg holding (trading days)':<35}: {m['avg_hold']:.1f}")
    print(f"{'Avg return per trade':<35}: {m['avg_ret_pct']:+.2f}%  (prior: -3.36%)")
    print(f"{'Total net P&L (₹)':<35}: {m['total_pnl']:,.0f}")
    print()
    print(f"{'Strategy CAGR':<35}: {m['cagr']*100:+.1f}%  (prior: {prev_cagr:.0f}%)")
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
    print("Per-criteria (Tier 1):")
    checks = [
        (f"Trades ≥ {TIER1_TRADES}",     m["n_trades"] >= TIER1_TRADES,    m["n_trades"]),
        (f"CAGR ≥ {TIER1_CAGR*100:.0f}%", m["cagr"] >= TIER1_CAGR,         f"{m['cagr']*100:.1f}%"),
        (f"Sharpe ≥ {TIER1_SHARPE}",      m["sharpe"] >= TIER1_SHARPE,      f"{m['sharpe']:.2f}"),
        (f"MaxDD ≤ {TIER1_MAXDD*100:.0f}%", m["max_dd"] <= TIER1_MAXDD,     f"{m['max_dd']*100:.1f}%"),
        (f"WinRate ≥ {TIER1_WINRATE*100:.0f}%", m["win_rate"] >= TIER1_WINRATE, f"{m['win_rate']*100:.1f}%"),
    ]
    for label, ok, val in checks:
        print(f"  {'✓' if ok else '✗'} {label} → {val}")
    print(sep)

    by_ret = sorted(trades, key=lambda t: t["ret_pct"], reverse=True)
    print("\nTOP 10 TRADES:")
    print(f"{'Stock':<12} {'Entry':>10} {'RSI':>5}  {'Days':>5}  {'Return':>8}  Reason")
    print("-" * 55)
    for t in by_ret[:10]:
        print(f"{t['sym']:<12} {str(t['entry_date'])[:10]:>10} {t['entry_rsi']:>5.1f}  "
              f"{t['trading_days']:>5}  {t['ret_pct']:>+7.2f}%  {t['exit_reason']}")

    out = Path("reports") / f"rsi_200ma_{date.today()}.md"
    out.parent.mkdir(exist_ok=True)
    lines = [
        f"# RSI + 200-day MA Filter Backtest — {date.today()}",
        f"Entry: RSI<{args.rsi_entry} AND above {args.ma_period}-day SMA",
        f"Period: {args.start} → {end}",
        "",
        "| Metric | Value | Prior (no filter) |",
        "|---|---|---|",
        f"| Trades | {m['n_trades']} | 797 |",
        f"| Win Rate | {m['win_rate']*100:.1f}% | 23.8% |",
        f"| CAGR | {m['cagr']*100:.1f}% | -100% |",
        f"| Sharpe | {m['sharpe']:.2f} | -4.05 |",
        f"| Max DD | {m['max_dd']*100:.1f}% | n/a |",
        f"| Nifty 50 CAGR | {nifty_cagr*100:.1f}% | — |",
        "",
        f"## Verdict: **{tier}**",
        "",
        "| Stock | Entry | RSI | Days | Return | Reason |",
        "|---|---|---|---|---|---|",
    ]
    for t in sorted(trades, key=lambda x: x["entry_date"]):
        lines.append(f"| {t['sym']} | {str(t['entry_date'])[:10]} | {t['entry_rsi']:.1f} "
                     f"| {t['trading_days']} | {t['ret_pct']:+.2f}% | {t['exit_reason']} |")
    out.write_text("\n".join(lines))
    logger.info("Report saved: %s", out)


if __name__ == "__main__":
    main()
