"""
RSI Mean-Reversion Validation — Nifty 100

Buys stocks when RSI(14) crosses below 30 (oversold). Exits when RSI > 50,
10 trading days elapsed, or -7% stop loss — whichever comes first.

Pre-committed decision criteria:
  docs/strategy_validation/rsi_meanreversion_criteria.md

Usage:
    python scripts/validate_rsi_meanreversion.py
    python scripts/validate_rsi_meanreversion.py --from 2021-01-01
    python scripts/validate_rsi_meanreversion.py --rsi-entry 30 --rsi-exit 50
    python scripts/validate_rsi_meanreversion.py --hold-days 10 --stop-pct 7
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
logger = logging.getLogger("rsi_val")

# ── Strategy constants (must match criteria doc) ────────────────────────────

RSI_PERIOD     = 14
RSI_ENTRY      = 30.0    # enter when RSI crosses below this
RSI_EXIT       = 50.0    # exit when RSI recovers above this
HOLD_DAYS      = 10      # max holding in trading days
STOP_PCT       = 0.07    # -7% hard stop from entry
MAX_CONCURRENT = 5       # max open positions at once
POSITION_INR   = 100_000.0  # ₹1 lakh per position
MIN_DATA_DAYS  = 750     # ≈ Nifty 100 filter (large-cap proxy)

# Costs (Indian equity delivery)
BROKERAGE    = 20.0
STT_SELL     = 0.001      # 0.1%
EXCHANGE     = 0.0000345  # per side
GST          = 0.18
STAMP        = 0.00015
SLIPPAGE     = 0.0005     # per side

# Tier thresholds
TIER1_TRADES  = 50
TIER1_CAGR    = 0.15
TIER1_SHARPE  = 0.8
TIER1_MAXDD   = 0.25
TIER1_WINRATE = 0.55

TIER2_TRADES  = 30
TIER2_CAGR    = 0.08
TIER2_SHARPE  = 0.5
TIER2_MAXDD   = 0.35
TIER2_WINRATE = 0.50


# ── Data loading ─────────────────────────────────────────────────────────────

def _load_symbols() -> list[str]:
    p = Path("data/nifty500.json")
    if not p.exists():
        p = Path(__file__).parent.parent / "data" / "nifty500.json"
    with open(p) as f:
        syms = json.load(f)["symbols"]
    return [s for s in syms if "DUMMY" not in s.upper()]


def _load_all_prices(symbols: list[str], start_str: str, end_str: str) -> dict[str, dict[date, float]]:
    """Load daily closes from ohlcv_cache; yfinance batch for gaps."""
    import yfinance as yf
    from sqlalchemy import text

    from mcp_server.db import engine

    prices: dict[str, dict[date, float]] = {}

    logger.info("Loading %d symbols from ohlcv_cache...", len(symbols))
    with engine.connect() as conn:
        for sym in symbols:
            rows = conn.execute(
                text(
                    "SELECT bar_date, close FROM ohlcv_cache "
                    "WHERE ticker=:s AND interval='1d' "
                    "AND bar_date BETWEEN :s0 AND :e "
                    "AND close IS NOT NULL AND close > 0 "
                    "ORDER BY bar_date"
                ),
                {"s": sym, "s0": start_str, "e": end_str},
            ).fetchall()
            if len(rows) >= MIN_DATA_DAYS:
                prices[sym] = {
                    (r.bar_date.date() if hasattr(r.bar_date, "date") else r.bar_date): float(r.close)
                    for r in rows
                }

    missing = [s for s in symbols if s not in prices]
    logger.info("DB: %d symbols | yfinance needed: %d", len(prices), len(missing))

    if missing:
        import pandas as pd
        batch = 50
        for i in range(0, len(missing), batch):
            chunk = missing[i : i + batch]
            yf_syms = [s + ".NS" for s in chunk]
            try:
                raw = yf.download(
                    yf_syms, start=start_str, end=end_str,
                    auto_adjust=True, progress=False, threads=True,
                )
                if raw.empty:
                    continue
                for sym, yf_sym in zip(chunk, yf_syms):
                    try:
                        closes = (
                            raw["Close"][yf_sym].dropna()
                            if isinstance(raw.columns, pd.MultiIndex)
                            else raw["Close"].dropna()
                        )
                        if len(closes) >= MIN_DATA_DAYS:
                            prices[sym] = {d.date(): float(c) for d, c in closes.items()}
                    except Exception:
                        pass
            except Exception as e:
                logger.warning("yfinance batch %d: %s", i, e)

    logger.info("Total eligible stocks (≥%d days): %d", MIN_DATA_DAYS, len(prices))
    return prices


# ── RSI calculation ───────────────────────────────────────────────────────────

def _compute_rsi(closes: list[float], period: int = RSI_PERIOD) -> list[float]:
    """Wilder's RSI. Returns list same length as closes; first `period` values = NaN (50)."""
    if len(closes) <= period:
        return [50.0] * len(closes)

    rsi = [50.0] * period  # warm-up placeholder

    gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, len(closes))]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi.append(100.0 - 100.0 / (1.0 + rs))

    return rsi


# ── Cost model ────────────────────────────────────────────────────────────────

def _round_trip_cost(position_inr: float) -> float:
    """Full delivery cost for one buy + sell."""
    buy_val  = position_inr * (1 + SLIPPAGE)
    sell_val = position_inr * (1 - SLIPPAGE)
    cost  = BROKERAGE * 2
    cost += sell_val * STT_SELL
    cost += (buy_val + sell_val) * EXCHANGE
    cost += (BROKERAGE * 2 + (buy_val + sell_val) * EXCHANGE) * GST
    cost += buy_val * STAMP
    return cost


# ── Backtest ──────────────────────────────────────────────────────────────────

def run_backtest(
    prices_by_sym: dict[str, dict[date, float]],
    start: date,
    end: date,
    rsi_entry: float,
    rsi_exit: float,
    hold_days: int,
    stop_pct: float,
) -> dict:
    """
    Event-driven daily simulation across all stocks.

    Each day:
      1. Check open positions → close any that hit exit conditions.
      2. If slots available, scan for new RSI < rsi_entry signals.
         - Only the FIRST day RSI crosses below rsi_entry (cross, not level).
         - Priority: most oversold (lowest RSI) when slots are limited.
    """
    # Pre-compute RSI for each stock indexed by date
    rsi_by_sym: dict[str, dict[date, float]] = {}
    date_prices: dict[str, tuple[list[date], list[float]]] = {}

    for sym, pd_data in prices_by_sym.items():
        sym_dates = sorted(d for d in pd_data if d <= end)
        sym_closes = [pd_data[d] for d in sym_dates]
        if len(sym_dates) < RSI_PERIOD + 2:
            continue
        rsi_vals = _compute_rsi(sym_closes)
        rsi_by_sym[sym] = dict(zip(sym_dates, rsi_vals))
        date_prices[sym] = (sym_dates, sym_closes)

    # All unique trading dates in the backtest window
    all_dates = sorted({d for pd_data in prices_by_sym.values() for d in pd_data if start <= d <= end})

    # Simulation state
    open_positions: list[dict] = []   # active trades
    closed_trades:  list[dict] = []   # completed trades
    portfolio_value = 0.0             # cumulative P&L (relative)

    for today in all_dates:
        # ── Step 1: Check exits for open positions ──────────────────────────
        still_open = []
        for pos in open_positions:
            sym        = pos["sym"]
            entry_px   = pos["entry_px"]
            entry_day  = pos["entry_day"]
            trading_days_held = pos["trading_days_held"] + 1

            # Get today's close for this stock
            today_close = prices_by_sym.get(sym, {}).get(today)
            if today_close is None:
                pos["trading_days_held"] = trading_days_held
                still_open.append(pos)
                continue

            today_rsi = rsi_by_sym.get(sym, {}).get(today, 50.0)
            stop_price = entry_px * (1 - stop_pct)

            exit_reason = None
            exit_px     = today_close

            if today_close <= stop_price:
                exit_reason = "stop"
                exit_px     = stop_price  # approximate fill at stop
            elif today_rsi > rsi_exit:
                exit_reason = "rsi_exit"
            elif trading_days_held >= hold_days:
                exit_reason = "time"

            if exit_reason:
                gross_pnl = (exit_px - entry_px) / entry_px * POSITION_INR
                cost      = _round_trip_cost(POSITION_INR)
                net_pnl   = gross_pnl - cost
                ret_pct   = net_pnl / POSITION_INR

                closed_trades.append({
                    "sym":          sym,
                    "entry_date":   entry_day,
                    "exit_date":    today,
                    "entry_px":     round(entry_px, 2),
                    "exit_px":      round(exit_px, 2),
                    "entry_rsi":    round(pos["entry_rsi"], 1),
                    "trading_days": trading_days_held,
                    "gross_pnl":    round(gross_pnl, 2),
                    "net_pnl":      round(net_pnl, 2),
                    "ret_pct":      round(ret_pct * 100, 2),
                    "exit_reason":  exit_reason,
                })
                portfolio_value += net_pnl
            else:
                pos["trading_days_held"] = trading_days_held
                still_open.append(pos)

        open_positions = still_open

        # ── Step 2: Scan for new entry signals ─────────────────────────────
        slots = MAX_CONCURRENT - len(open_positions)
        if slots <= 0:
            continue

        already_holding = {p["sym"] for p in open_positions}
        candidates: list[tuple[float, str, float]] = []  # (rsi, sym, close_price)

        for sym, rsi_map in rsi_by_sym.items():
            if sym in already_holding:
                continue
            today_rsi = rsi_map.get(today)
            if today_rsi is None or today_rsi >= rsi_entry:
                continue

            # Require crossover (first day below rsi_entry)
            sym_dates, sym_closes = date_prices.get(sym, ([], []))
            idx = next((i for i, d in enumerate(sym_dates) if d == today), None)
            if idx is None or idx == 0:
                continue
            prev_rsi = rsi_map.get(sym_dates[idx - 1], 50.0)
            if prev_rsi < rsi_entry:
                continue  # already was below — not a fresh crossover

            today_close = prices_by_sym[sym].get(today)
            if today_close is None or today_close <= 0:
                continue

            candidates.append((today_rsi, sym, today_close))

        # Sort by RSI ascending (most oversold first), fill slots
        candidates.sort(key=lambda x: x[0])
        for rsi_val, sym, close_px in candidates[:slots]:
            open_positions.append({
                "sym":              sym,
                "entry_day":        today,
                "entry_px":         close_px,
                "entry_rsi":        rsi_val,
                "trading_days_held": 0,
            })

    # Force-close any positions still open at end of backtest
    for pos in open_positions:
        sym       = pos["sym"]
        last_close = prices_by_sym.get(sym, {}).get(end) or pos["entry_px"]
        gross_pnl = (last_close - pos["entry_px"]) / pos["entry_px"] * POSITION_INR
        cost      = _round_trip_cost(POSITION_INR)
        net_pnl   = gross_pnl - cost
        closed_trades.append({
            "sym":          sym,
            "entry_date":   pos["entry_day"],
            "exit_date":    end,
            "entry_px":     round(pos["entry_px"], 2),
            "exit_px":      round(last_close, 2),
            "entry_rsi":    round(pos["entry_rsi"], 1),
            "trading_days": pos["trading_days_held"],
            "gross_pnl":    round(gross_pnl, 2),
            "net_pnl":      round(net_pnl, 2),
            "ret_pct":      round(net_pnl / POSITION_INR * 100, 2),
            "exit_reason":  "end_of_backtest",
        })
        portfolio_value += net_pnl

    return {"trades": closed_trades, "total_pnl": portfolio_value}


# ── Metrics ───────────────────────────────────────────────────────────────────

def _metrics(trades: list[dict], start: date, end: date) -> dict:
    if not trades:
        return {}

    returns = [t["ret_pct"] / 100 for t in trades]
    n = len(trades)
    wins = sum(1 for r in returns if r > 0)
    total_ret = sum(returns)  # sum of per-trade returns (trade-level, not time-series)

    # Annualized using trade-level returns (per-trade Sharpe)
    years = (end - start).days / 365.25
    cagr = (1 + total_ret) ** (1 / years) - 1 if years > 0 and total_ret > -1 else -1.0

    mean_r = total_ret / n
    std_r  = math.sqrt(sum((r - mean_r) ** 2 for r in returns) / max(n - 1, 1))
    sharpe = (mean_r / std_r) * math.sqrt(252 / 10) if std_r > 0 else 0.0  # annualize per 10-day trade

    # Drawdown on cumulative P&L sequence
    # Reference capital = max concurrent positions × position size
    ref_capital = float(MAX_CONCURRENT * POSITION_INR)
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in sorted(trades, key=lambda x: x["exit_date"]):
        cum  += t["net_pnl"]
        peak  = max(peak, cum)
        max_dd = max(max_dd, (peak - cum) / ref_capital)

    exit_reasons = {}
    for t in trades:
        r = t["exit_reason"]
        exit_reasons[r] = exit_reasons.get(r, 0) + 1

    return {
        "n_trades":     n,
        "win_rate":     wins / n,
        "cagr":         cagr,
        "sharpe":       sharpe,
        "max_dd":       max_dd,
        "total_pnl":    sum(t["net_pnl"] for t in trades),
        "avg_hold":     sum(t["trading_days"] for t in trades) / n,
        "avg_ret_pct":  mean_r * 100,
        "exit_reasons": exit_reasons,
    }


def _tier_verdict(m: dict) -> str:
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


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="RSI mean-reversion backtest")
    parser.add_argument("--from",      dest="start",     default="2021-01-01")
    parser.add_argument("--to",        dest="end",       default=str(date.today()))
    parser.add_argument("--rsi-entry", type=float,       default=RSI_ENTRY)
    parser.add_argument("--rsi-exit",  type=float,       default=RSI_EXIT)
    parser.add_argument("--hold-days", type=int,         default=HOLD_DAYS)
    parser.add_argument("--stop-pct",  type=float,       default=STOP_PCT * 100)
    args = parser.parse_args()

    start     = date.fromisoformat(args.start)
    end       = date.fromisoformat(args.end)
    stop_pct  = args.stop_pct / 100.0
    data_start = date(start.year - 1, start.month, 1)  # extra year for RSI warm-up

    symbols = _load_symbols()
    prices  = _load_all_prices(symbols, data_start.isoformat(), end.isoformat())

    if len(prices) < 10:
        logger.error("Too few stocks loaded (%d) — check DB connection", len(prices))
        return

    # Load Nifty 50 benchmark
    nifty_prices: dict[date, float] = {}
    try:
        import yfinance as yf
        df = yf.download("^NSEI", start=start.isoformat(), end=end.isoformat(),
                         auto_adjust=True, progress=False)
        if not df.empty:
            closes = df["Close"]
            if hasattr(getattr(closes, "columns", None), "__iter__"):
                closes = closes.iloc[:, 0]
            nifty_prices = {d.date(): float(c) for d, c in closes.items()}
    except Exception as e:
        logger.warning("Nifty 50 benchmark fetch failed: %s", e)

    logger.info("Running backtest: %s → %s | RSI entry<%s exit>%s | hold=%s days | SL=%.0f%%",
                start, end, args.rsi_entry, args.rsi_exit, args.hold_days, args.stop_pct)

    result = run_backtest(prices, start, end, args.rsi_entry, args.rsi_exit,
                          args.hold_days, stop_pct)
    trades = result["trades"]
    m      = _metrics(trades, start, end)
    tier   = _tier_verdict(m)

    # Nifty 50 buy-and-hold CAGR for comparison
    nifty_cagr = 0.0
    if nifty_prices:
        n_dates = sorted(nifty_prices)
        p0 = nifty_prices.get(n_dates[0], 1)
        p1 = nifty_prices.get(n_dates[-1], 1)
        years = (end - start).days / 365.25
        nifty_cagr = (p1 / p0) ** (1 / years) - 1 if years > 0 else 0.0

    # ── Print results ─────────────────────────────────────────────────────────
    sep = "=" * 70
    print()
    print(sep)
    print(f"RSI MEAN-REVERSION BACKTEST  |  {args.start} → {end}")
    print(f"Entry: RSI<{args.rsi_entry}  Exit: RSI>{args.rsi_exit} OR {args.hold_days}d OR SL-{args.stop_pct:.0f}%")
    print(sep)

    if not m:
        print("No trades generated — check data or parameters.")
        return

    print(f"{'Universe stocks':<35}: {len(prices)}")
    print(f"{'Total trades':<35}: {m['n_trades']}")
    print(f"{'Win rate':<35}: {m['win_rate']*100:.1f}%")
    print(f"{'Avg holding (trading days)':<35}: {m['avg_hold']:.1f}")
    print(f"{'Avg return per trade':<35}: {m['avg_ret_pct']:+.2f}%")
    print(f"{'Total net P&L (₹)':<35}: {m['total_pnl']:,.0f}")
    print()
    print(f"{'Strategy CAGR':<35}: {m['cagr']*100:+.1f}%")
    print(f"{'Nifty 50 CAGR (buy+hold)':<35}: {nifty_cagr*100:+.1f}%")
    print(f"{'Sharpe ratio (ann.)':<35}: {m['sharpe']:.2f}")
    print(f"{'Max drawdown':<35}: {m['max_dd']*100:.1f}%")
    print()
    print("Exit breakdown:")
    for reason, count in sorted(m["exit_reasons"].items(), key=lambda x: -x[1]):
        print(f"  {reason:<20}: {count}")
    print()
    print(sep)
    print(f"VERDICT: {tier}")
    print()
    print("Per-criteria checklist:")
    checks = [
        (f"Trades ≥ {TIER1_TRADES}", m["n_trades"] >= TIER1_TRADES, m["n_trades"]),
        (f"CAGR ≥ {TIER1_CAGR*100:.0f}%", m["cagr"] >= TIER1_CAGR, f"{m['cagr']*100:.1f}%"),
        (f"Sharpe ≥ {TIER1_SHARPE}", m["sharpe"] >= TIER1_SHARPE, f"{m['sharpe']:.2f}"),
        (f"MaxDD ≤ {TIER1_MAXDD*100:.0f}%", m["max_dd"] <= TIER1_MAXDD, f"{m['max_dd']*100:.1f}%"),
        (f"WinRate ≥ {TIER1_WINRATE*100:.0f}%", m["win_rate"] >= TIER1_WINRATE, f"{m['win_rate']*100:.1f}%"),
    ]
    for label, ok, val in checks:
        print(f"  {'✓' if ok else '✗'} {label} → {val}")
    print(sep)

    # Top 10 and bottom 10 trades
    by_ret = sorted(trades, key=lambda t: t["ret_pct"], reverse=True)
    print("\nTOP 10 TRADES:")
    print(f"{'Stock':<12} {'Entry':>10} {'Exit':>10} {'RSI':>5}  {'Days':>5}  {'Return':>8}  Reason")
    print("-" * 65)
    for t in by_ret[:10]:
        print(f"{t['sym']:<12} {str(t['entry_date'])[:10]:>10} {str(t['exit_date'])[:10]:>10} "
              f"{t['entry_rsi']:>5.1f}  {t['trading_days']:>5}  {t['ret_pct']:>+7.2f}%  {t['exit_reason']}")

    print("\nBOTTOM 10 TRADES:")
    print(f"{'Stock':<12} {'Entry':>10} {'Exit':>10} {'RSI':>5}  {'Days':>5}  {'Return':>8}  Reason")
    print("-" * 65)
    for t in by_ret[-10:]:
        print(f"{t['sym']:<12} {str(t['entry_date'])[:10]:>10} {str(t['exit_date'])[:10]:>10} "
              f"{t['entry_rsi']:>5.1f}  {t['trading_days']:>5}  {t['ret_pct']:>+7.2f}%  {t['exit_reason']}")

    # ── Save report ───────────────────────────────────────────────────────────
    out = Path("reports") / f"rsi_meanreversion_{date.today()}.md"
    out.parent.mkdir(exist_ok=True)
    lines = [
        f"# RSI Mean-Reversion Backtest — {date.today()}",
        f"Entry: RSI<{args.rsi_entry} | Exit: RSI>{args.rsi_exit} OR {args.hold_days}d OR SL-{args.stop_pct:.0f}%",
        f"Period: {args.start} → {end}",
        "",
        "## Summary",
        "",
        "| Metric | Value | Nifty 50 |",
        "|---|---|---|",
        f"| Trades | {m['n_trades']} | — |",
        f"| Win Rate | {m['win_rate']*100:.1f}% | — |",
        f"| CAGR | {m['cagr']*100:.1f}% | {nifty_cagr*100:.1f}% |",
        f"| Sharpe | {m['sharpe']:.2f} | — |",
        f"| Max Drawdown | {m['max_dd']*100:.1f}% | — |",
        f"| Avg Hold (days) | {m['avg_hold']:.1f} | — |",
        f"| Total Net P&L | ₹{m['total_pnl']:,.0f} | — |",
        "",
        f"## Verdict: **{tier}**",
        "",
        "## All Trades",
        "",
        "| Stock | Entry Date | Exit Date | Entry RSI | Days | Return% | Reason |",
        "|---|---|---|---|---|---|---|",
    ]
    for t in sorted(trades, key=lambda x: x["entry_date"]):
        lines.append(
            f"| {t['sym']} | {str(t['entry_date'])[:10]} | {str(t['exit_date'])[:10]} "
            f"| {t['entry_rsi']:.1f} | {t['trading_days']} | {t['ret_pct']:+.2f}% | {t['exit_reason']} |"
        )
    out.write_text("\n".join(lines), encoding='utf-8')
    logger.info("Report saved: %s", out)


if __name__ == "__main__":
    main()
