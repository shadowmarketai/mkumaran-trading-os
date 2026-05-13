"""
NSE Sector Rotation Validation

Monthly rebalance into the top 3 NSE sectoral indices by 3-month momentum.
Uses yfinance sectoral index data (no DB dependency).

Pre-committed criteria: docs/strategy_validation/sector_rotation_criteria.md

Usage:
    python scripts/validate_sector_rotation.py
    python scripts/validate_sector_rotation.py --top-sectors 3 --lookback 63
"""
from __future__ import annotations

import argparse
import logging
import math
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sector_rotation")

SECTORS = {
    "Bank":    "^NSEBANK",              # Nifty Bank (^CNXBANK 404s on yfinance)
    "IT":      "^CNXIT",
    "Pharma":  "^CNXPHARMA",
    "Auto":    "^CNXAUTO",
    "FMCG":    "^CNXFMCG",
    "Metal":   "^CNXMETAL",
    "Realty":  "^CNXREALTY",
    "Energy":  "^CNXENERGY",
    "Finance": "NIFTY_FIN_SERVICE.NS",  # Nifty Financial Services
    "Infra":   "^CNXINFRA",
}

TOP_SECTORS  = 3
LOOKBACK     = 63    # 3 months in trading days
PORTFOLIO_INR = 1_000_000.0

BROKERAGE = 20.0
STT_SELL  = 0.001
EXCHANGE  = 0.0000345
GST       = 0.18
STAMP     = 0.00015
SLIPPAGE  = 0.0005

TIER1_ALPHA   = 0.05
TIER1_SHARPE  = 0.8
TIER1_MAXDD   = 0.35
TIER1_WR      = 0.55
TIER2_ALPHA   = 0.02
TIER2_SHARPE  = 0.5
TIER2_MAXDD   = 0.45
TIER2_WR      = 0.50


def _load_prices(tickers: dict[str, str], start_str: str, end_str: str) -> dict[str, dict[date, float]]:
    import yfinance as yf
    import pandas as pd
    all_syms = list(tickers.values()) + ["^NSEI"]
    try:
        raw = yf.download(all_syms, start=start_str, end=end_str,
                          auto_adjust=True, progress=False, threads=True)
        if raw.empty:
            return {}
        prices: dict[str, dict[date, float]] = {}
        for name, sym in tickers.items():
            try:
                closes = (raw["Close"][sym].dropna()
                          if isinstance(raw.columns, pd.MultiIndex)
                          else raw["Close"].dropna())
                if len(closes) >= 100:
                    prices[name] = {d.date(): float(c) for d, c in closes.items()}
            except Exception:
                pass
        try:
            nifty_closes = (raw["Close"]["^NSEI"].dropna()
                            if isinstance(raw.columns, pd.MultiIndex)
                            else raw["Close"].dropna())
            prices["__NIFTY50"] = {d.date(): float(c) for d, c in nifty_closes.items()}
        except Exception:
            pass
        logger.info("Loaded %d sectors + Nifty 50", len(prices) - (1 if "__NIFTY50" in prices else 0))
        return prices
    except Exception as e:
        logger.error("yfinance batch failed: %s", e)
        return {}


def _get_price_at(prices: dict[date, float], target: date, tol: int = 5):
    for delta in range(tol + 1):
        for sign in [0, -1, 1]:
            d = date.fromordinal(target.toordinal() + sign * delta)
            if d in prices:
                return prices[d]
    return None


def _monthly_rebalance_dates(start: date, end: date, all_dates: set) -> list[date]:
    result = []
    cur = date(start.year, start.month, 1)
    while cur <= end:
        d = cur
        for _ in range(10):
            if d in all_dates:
                result.append(d)
                break
            d += timedelta(days=1)
        cur = date(cur.year + 1, 1, 1) if cur.month == 12 else date(cur.year, cur.month + 1, 1)
    return result


def _cost_pct(n_trades: int, position_inr: float) -> float:
    cost = BROKERAGE * n_trades * 2
    cost += position_inr * STT_SELL
    cost += position_inr * 2 * EXCHANGE
    cost += (BROKERAGE * n_trades * 2 + position_inr * 2 * EXCHANGE) * GST
    cost += position_inr * STAMP
    cost += position_inr * 2 * SLIPPAGE
    return cost / position_inr


def main() -> None:
    parser = argparse.ArgumentParser(description="NSE sector rotation backtest")
    parser.add_argument("--from",         dest="start",       default="2021-01-01")
    parser.add_argument("--to",           dest="end",         default=str(date.today()))
    parser.add_argument("--top-sectors",  type=int,           default=TOP_SECTORS)
    parser.add_argument("--lookback",     type=int,           default=LOOKBACK)
    parser.add_argument("--exclude",      nargs="+",          default=[],
                        help="Sector names to exclude e.g. --exclude Bank Finance")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end   = date.fromisoformat(args.end)
    data_start = date(start.year - 1, start.month, 1)

    # Filter sectors based on --exclude list
    active_sectors = {k: v for k, v in SECTORS.items() if k not in args.exclude}
    if args.exclude:
        logger.info("Excluded sectors: %s | Running with %d sectors: %s",
                    args.exclude, len(active_sectors), list(active_sectors))
    global SECTORS
    SECTORS = active_sectors

    prices = _load_prices(SECTORS, data_start.isoformat(), end.isoformat())
    if len(prices) < 3:
        logger.error("Insufficient sector data")
        return

    nifty_prices = prices.pop("__NIFTY50", {})
    sector_names = [k for k in prices if k != "__NIFTY50"]

    all_dates: set = set()
    for pd_data in prices.values():
        all_dates.update(pd_data.keys())
    all_dates.update(nifty_prices.keys())

    rebal_dates = _monthly_rebalance_dates(start, end, all_dates)
    logger.info("Rebalance dates: %d (%s → %s)", len(rebal_dates), rebal_dates[0], rebal_dates[-1])

    portfolio_returns: list[float] = []
    nifty_returns:     list[float] = []
    monthly_records:   list[dict]  = []
    prior_sectors: set[str] = set()
    total_cost_pct = 0.0

    for i, rebal in enumerate(rebal_dates[:-1]):
        next_rebal = rebal_dates[i + 1]
        lookback_date = date.fromordinal(rebal.toordinal() - args.lookback)

        scores: dict[str, float] = {}
        for name in sector_names:
            p_now = _get_price_at(prices[name], rebal)
            p_old = _get_price_at(prices[name], lookback_date, tol=8)
            if p_now and p_old and p_old > 0:
                scores[name] = p_now / p_old - 1

        if len(scores) < args.top_sectors:
            continue

        top = sorted(scores, key=lambda s: scores[s], reverse=True)[:args.top_sectors]
        top_set = set(top)

        # Monthly return for each top sector
        returns = []
        for name in top:
            p0 = _get_price_at(prices[name], rebal)
            p1 = _get_price_at(prices[name], next_rebal)
            if p0 and p1 and p0 > 0:
                returns.append(p1 / p0 - 1)
        portfolio_ret = sum(returns) / len(returns) if returns else 0.0

        # Costs
        changes = len(top_set.symmetric_difference(prior_sectors))
        pos_size = PORTFOLIO_INR / args.top_sectors
        cost_pct = _cost_pct(changes, pos_size) if changes else 0.0
        net_ret  = portfolio_ret - cost_pct
        total_cost_pct += cost_pct
        prior_sectors = top_set

        # Nifty return
        n0 = _get_price_at(nifty_prices, rebal)
        n1 = _get_price_at(nifty_prices, next_rebal)
        nifty_ret = (n1 / n0 - 1) if (n0 and n1 and n0 > 0) else 0.0

        portfolio_returns.append(net_ret)
        nifty_returns.append(nifty_ret)
        monthly_records.append({
            "date": rebal.isoformat(), "top": ", ".join(sorted(top)),
            "port_ret": round(portfolio_ret * 100, 2),
            "net_ret":  round(net_ret * 100, 2),
            "nifty_ret": round(nifty_ret * 100, 2),
            "excess":   round((net_ret - nifty_ret) * 100, 2),
        })

    if not portfolio_returns:
        print("No monthly returns computed.")
        return

    n_months = len(portfolio_returns)
    years    = n_months / 12

    total_port  = 1.0
    total_nifty = 1.0
    for pr, nr in zip(portfolio_returns, nifty_returns):
        total_port  *= (1 + pr)
        total_nifty *= (1 + nr)

    port_cagr  = total_port  ** (1 / max(years, 0.1)) - 1
    nifty_cagr = total_nifty ** (1 / max(years, 0.1)) - 1
    alpha      = port_cagr - nifty_cagr

    mean_r = sum(portfolio_returns) / n_months
    std_r  = math.sqrt(sum((r - mean_r) ** 2 for r in portfolio_returns) / max(n_months - 1, 1))
    sharpe = (mean_r / std_r) * math.sqrt(12) if std_r > 0 else 0.0

    equity = 1.0
    peak   = 1.0
    max_dd = 0.0
    for r in portfolio_returns:
        equity *= (1 + r)
        peak    = max(peak, equity)
        max_dd  = max(max_dd, (peak - equity) / peak)

    excess = [pr - nr for pr, nr in zip(portfolio_returns, nifty_returns)]
    win_months = sum(1 for e in excess if e > 0)
    win_rate   = win_months / n_months

    tier = "OVERRIDE"
    if alpha >= TIER1_ALPHA and sharpe >= TIER1_SHARPE and max_dd <= TIER1_MAXDD and win_rate >= TIER1_WR:
        tier = "TIER_1"
    elif alpha >= TIER2_ALPHA and sharpe >= TIER2_SHARPE and max_dd <= TIER2_MAXDD and win_rate >= TIER2_WR:
        tier = "TIER_2"

    sep = "=" * 68
    print()
    print(sep)
    print(f"NSE SECTOR ROTATION  |  Top {args.top_sectors} by {args.lookback}-day momentum")
    print(f"Period: {args.start} → {end}  |  {n_months} months simulated")
    print(sep)
    print(f"{'Portfolio CAGR':<35}: {port_cagr*100:+.1f}%")
    print(f"{'Nifty 50 CAGR':<35}: {nifty_cagr*100:+.1f}%")
    print(f"{'Alpha vs Nifty 50':<35}: {alpha*100:+.1f}pp")
    print(f"{'Sharpe (ann.)':<35}: {sharpe:.2f}")
    print(f"{'Max drawdown':<35}: {max_dd*100:.1f}%")
    print(f"{'Win rate (months > Nifty)':<35}: {win_rate*100:.1f}%")
    print()
    print(sep)
    print(f"VERDICT: {tier}")
    checks = [
        (f"Alpha ≥ {TIER1_ALPHA*100:.0f}pp",   alpha >= TIER1_ALPHA,    f"{alpha*100:.1f}pp"),
        (f"Sharpe ≥ {TIER1_SHARPE}",            sharpe >= TIER1_SHARPE,  f"{sharpe:.2f}"),
        (f"MaxDD ≤ {TIER1_MAXDD*100:.0f}%",     max_dd <= TIER1_MAXDD,   f"{max_dd*100:.1f}%"),
        (f"WinRate ≥ {TIER1_WR*100:.0f}%",      win_rate >= TIER1_WR,    f"{win_rate*100:.1f}%"),
    ]
    for label, ok, val in checks:
        print(f"  {'✓' if ok else '✗'} {label} → {val}")
    print(sep)

    print("\nLast 12 months:")
    print(f"{'Month':<12} {'Top 3 Sectors':<35} {'Port%':>6}  {'Nifty%':>6}  {'Excess':>7}")
    print("-" * 70)
    for rec in monthly_records[-12:]:
        print(f"{rec['date']:<12} {rec['top']:<35} {rec['net_ret']:>+5.1f}%  "
              f"{rec['nifty_ret']:>+5.1f}%  {rec['excess']:>+6.1f}%")

    out = Path("reports") / f"sector_rotation_{date.today()}.md"
    out.parent.mkdir(exist_ok=True)
    lines = [
        f"# NSE Sector Rotation — {date.today()}",
        f"Top {args.top_sectors} sectors by {args.lookback}-day momentum | {args.start} → {end}",
        "",
        "| Metric | Value |", "|---|---|",
        f"| Portfolio CAGR | {port_cagr*100:.1f}% |",
        f"| Nifty 50 CAGR | {nifty_cagr*100:.1f}% |",
        f"| Alpha | {alpha*100:.1f}pp |",
        f"| Sharpe | {sharpe:.2f} |",
        f"| Max DD | {max_dd*100:.1f}% |",
        f"| Win Rate | {win_rate*100:.1f}% |",
        "",
        f"## Verdict: **{tier}**",
        "",
        "| Month | Top Sectors | Port% | Nifty% | Excess |",
        "|---|---|---|---|---|",
    ]
    for rec in monthly_records:
        lines.append(f"| {rec['date']} | {rec['top']} | {rec['net_ret']} | {rec['nifty_ret']} | {rec['excess']} |")
    out.write_text("\n".join(lines))
    logger.info("Report saved: %s", out)


if __name__ == "__main__":
    main()
