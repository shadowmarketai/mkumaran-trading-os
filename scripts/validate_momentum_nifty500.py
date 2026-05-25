"""
12-Month Cross-Sectional Momentum — Nifty 500

Ranks Nifty 500 stocks by trailing 12-month return, holds the top quintile,
rebalances monthly, and applies the full Indian equity delivery cost model.
Compares to an equal-weight universe benchmark and Nifty 50.

Pre-committed decision criteria: docs/strategy_validation/momentum_nifty500_criteria.md

Usage:
    python scripts/validate_momentum_nifty500.py
    python scripts/validate_momentum_nifty500.py --from 2021-01-01
    python scripts/validate_momentum_nifty500.py --top-pct 20  # quintile (default)
    python scripts/validate_momentum_nifty500.py --portfolio-size 1000000

Output:
  - Monthly return table (portfolio vs benchmark)
  - CAGR, Sharpe, max drawdown, win rate
  - Tier verdict per criteria doc
  - Reports saved to reports/momentum_nifty500_YYYY-MM-DD.md
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows cp1252 fix

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("momentum_val")

# ── Strategy constants (must match criteria doc) ────────────────────────────

LOOKBACK_TRADING_DAYS = 252      # ~12 months
TOP_QUINTILE_PCT      = 20       # top 20% = ~100 stocks of 500
PORTFOLIO_SIZE_INR    = 1_000_000  # ₹10 lakhs

# Cost model (Indian equity delivery, Zerodha)
BROKERAGE_PER_ORDER = 20.0       # ₹20 flat per order
STT_SELL_PCT        = 0.001      # 0.1% on sell turnover
EXCHANGE_PCT        = 0.0000345  # per side
GST_PCT             = 0.18       # on (brokerage + exchange)
STAMP_BUY_PCT       = 0.00015   # 0.015% on buy turnover
SLIPPAGE_PCT        = 0.0005     # 0.05% per side

MIN_ELIGIBLE_STOCKS  = 50        # skip rebalance if fewer eligible


def _load_nifty500_symbols() -> list[str]:
    p = Path("data/nifty500.json")
    if not p.exists():
        p = Path(__file__).parent.parent / "data" / "nifty500.json"
    with open(p) as f:
        syms = json.load(f)["symbols"]
    return [s for s in syms if "DUMMY" not in s.upper()]


def _load_prices(symbols: list[str], start_str: str, end_str: str) -> dict[str, dict]:
    """Load daily close prices from ohlcv_cache; yfinance for gaps."""
    import yfinance as yf

    prices: dict[str, dict] = {}

    try:
        from sqlalchemy import text
        from mcp_server.db import engine
        logger.info("Loading prices from ohlcv_cache for %d symbols...", len(symbols))
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
                if rows:
                    prices[sym] = {
                        (r.bar_date.date() if hasattr(r.bar_date, "date") else r.bar_date): float(r.close)
                        for r in rows
                    }
    except Exception as db_err:
        logger.warning("DB unavailable (%s) — using yfinance for all symbols", db_err.__class__.__name__)

    in_db = len(prices)
    missing = [s for s in symbols if s not in prices or len(prices[s]) < 100]
    logger.info("DB hit: %d  |  yfinance needed: %d", in_db, len(missing))

    if missing:
        yf_syms = [s + ".NS" for s in missing]
        batch_size = 50
        for i in range(0, len(yf_syms), batch_size):
            batch_symbols = missing[i : i + batch_size]
            batch_yf = yf_syms[i : i + batch_size]
            try:
                import pandas as pd
                raw = yf.download(
                    batch_yf,
                    start=start_str,
                    end=end_str,
                    auto_adjust=True,
                    progress=False,
                    threads=True,
                )
                if raw.empty:
                    continue
                for sym, yf_sym in zip(batch_symbols, batch_yf):
                    try:
                        if isinstance(raw.columns, pd.MultiIndex):
                            closes = raw["Close"][yf_sym].dropna()
                        else:
                            closes = raw["Close"].dropna()
                        if len(closes) >= 100:
                            prices[sym] = {d.date(): float(c) for d, c in closes.items()}
                    except Exception:
                        pass
            except Exception as e:
                logger.warning("yfinance batch %d-%d failed: %s", i, i + batch_size, e)
        logger.info("After yfinance: %d symbols with data", len(prices))

    return prices


def _sorted_dates(price_dict: dict) -> list:
    return sorted(price_dict.keys())


def _get_price_at(price_dict: dict, dates: list, target_date, tolerance_days: int = 5):
    """Return close price closest to target_date within tolerance."""
    from datetime import date as date_type
    if isinstance(target_date, date_type):
        t = target_date
    else:
        t = target_date
    candidates = [d for d in dates if abs((d - t).days) <= tolerance_days]
    if not candidates:
        return None
    best = min(candidates, key=lambda d: abs((d - t).days))
    return price_dict.get(best)


def _monthly_rebalance_dates(start: date, end: date, all_dates: list) -> list[date]:
    """First available trading date in each calendar month."""
    all_date_set = set(all_dates)
    rebalance_dates = []
    current = date(start.year, start.month, 1)
    while current <= end:
        # Find first trading day of this month
        d = current
        for _ in range(10):
            if d in all_date_set:
                rebalance_dates.append(d)
                break
            d += timedelta(days=1)
        # Move to first day of next month
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    return rebalance_dates


def _compute_round_trip_cost(trade_value_inr: float, orders: int) -> float:
    """Full cost of one round-trip trade."""
    brokerage = BROKERAGE_PER_ORDER * orders * 2  # buy + sell orders
    stt = STT_SELL_PCT * trade_value_inr           # sell-side only
    exchange = EXCHANGE_PCT * trade_value_inr * 2  # both sides
    gst = GST_PCT * (brokerage / orders / 2 + exchange / orders / 2) * orders * 2
    stamp = STAMP_BUY_PCT * trade_value_inr        # buy-side only
    slippage = SLIPPAGE_PCT * trade_value_inr * 2  # both sides
    return brokerage + stt + exchange + gst + stamp + slippage


def _cagr(total_return: float, years: float) -> float:
    if years <= 0:
        return 0.0
    return (1 + total_return) ** (1 / years) - 1


def _sharpe(monthly_returns: list[float], risk_free_annual: float = 0.065) -> float:
    """Annualized Sharpe from monthly excess returns."""
    import math
    rfr_monthly = (1 + risk_free_annual) ** (1 / 12) - 1
    excess = [r - rfr_monthly for r in monthly_returns]
    if len(excess) < 2:
        return 0.0
    mean_e = sum(excess) / len(excess)
    var_e = sum((r - mean_e) ** 2 for r in excess) / (len(excess) - 1)
    std_e = math.sqrt(var_e) if var_e > 0 else 1e-9
    return (mean_e / std_e) * (12 ** 0.5)


def _max_drawdown(monthly_returns: list[float]) -> float:
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in monthly_returns:
        equity *= (1 + r)
        peak = max(peak, equity)
        dd = (peak - equity) / peak
        max_dd = max(max_dd, dd)
    return max_dd


def main() -> None:
    parser = argparse.ArgumentParser(description="Nifty 500 momentum backtest")
    parser.add_argument("--from", dest="start", default="2021-01-01")
    parser.add_argument("--to", dest="end", default=str(date.today()))
    parser.add_argument("--top-pct", type=int, default=TOP_QUINTILE_PCT)
    parser.add_argument("--portfolio-size", type=float, default=PORTFOLIO_SIZE_INR)
    parser.add_argument("--skip-days", type=int, default=0,
                        help="Calendar days to skip for 1-month skip variant (use 30)")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    top_pct = args.top_pct
    portfolio_inr = args.portfolio_size

    symbols = _load_nifty500_symbols()
    logger.info("Nifty 500 universe: %d symbols", len(symbols))

    # Extend start back 15 months for initial lookback window
    data_start = date(start.year - 1, max(1, start.month - 3), 1)
    prices = _load_prices(symbols, data_start.isoformat(), end.isoformat())
    logger.info("Loaded prices for %d symbols", len(prices))

    if len(prices) < 50:
        logger.error("Insufficient price data — need at least 50 symbols")
        return

    # Build unified trading date list (union of all dates)
    all_dates_set: set = set()
    for pd in prices.values():
        all_dates_set.update(pd.keys())
    all_dates = sorted(all_dates_set)

    # Also fetch Nifty 50 for secondary benchmark
    import yfinance as yf
    nifty50_closes: dict = {}
    try:
        df = yf.download("^NSEI", start=data_start.isoformat(), end=end.isoformat(),
                         auto_adjust=True, progress=False)
        if not df.empty:
            closes = df["Close"]
            if hasattr(getattr(closes, "columns", None), "__iter__"):
                closes = closes.iloc[:, 0]
            nifty50_closes = {d.date(): float(c) for d, c in closes.items()}
            logger.info("Nifty 50 benchmark: %d bars", len(nifty50_closes))
    except Exception as e:
        logger.warning("Nifty 50 benchmark fetch failed: %s", e)

    # Rebalance dates (first trading day of each month in backtest window)
    rebal_dates = _monthly_rebalance_dates(start, end, all_dates)
    logger.info("Rebalance dates: %d (%s → %s)", len(rebal_dates), rebal_dates[0], rebal_dates[-1])

    # ── Main backtest loop ──────────────────────────────────────────────────

    portfolio_monthly_returns: list[float] = []
    benchmark_monthly_returns: list[float] = []  # equal-weight universe
    nifty50_monthly_returns: list[float] = []

    total_cost_inr = 0.0
    monthly_records: list[dict] = []
    prior_portfolio: set[str] = set()

    for i, rebal_date in enumerate(rebal_dates[:-1]):
        next_rebal = rebal_dates[i + 1]

        # ── Step 1: Rank eligible stocks ──────────────────────────────────
        # 1-month skip: rank on price[t - skip_days] / price[t - skip_days - lookback]
        # skip_days=0 → standard trailing return to today
        rank_date    = date.fromordinal(rebal_date.toordinal() - args.skip_days)
        lookback_date = date.fromordinal(rank_date.toordinal() - LOOKBACK_TRADING_DAYS)

        scores: dict[str, float] = {}
        for sym, pd_data in prices.items():
            sym_dates = _sorted_dates(pd_data)
            p_now = _get_price_at(pd_data, sym_dates, rank_date, tolerance_days=5 + args.skip_days // 5)
            p_old = _get_price_at(pd_data, sym_dates, lookback_date, tolerance_days=10)
            if p_now and p_old and p_old > 0:
                scores[sym] = p_now / p_old - 1

        eligible = list(scores.keys())
        n_eligible = len(eligible)

        if n_eligible < MIN_ELIGIBLE_STOCKS:
            logger.warning("Rebal %s: only %d eligible stocks — skipping", rebal_date, n_eligible)
            continue

        # Top quintile
        n_top = max(1, int(n_eligible * top_pct / 100))
        ranked = sorted(eligible, key=lambda s: scores[s], reverse=True)
        top_stocks = set(ranked[:n_top])

        # ── Step 2: Compute next-month returns ────────────────────────────
        def _monthly_return(stock_set: set[str]) -> float:
            """Equal-weight portfolio return from rebal_date to next_rebal."""
            returns = []
            for sym in stock_set:
                pd_data = prices.get(sym, {})
                sym_dates = _sorted_dates(pd_data)
                p0 = _get_price_at(pd_data, sym_dates, rebal_date, tolerance_days=5)
                p1 = _get_price_at(pd_data, sym_dates, next_rebal, tolerance_days=5)
                if p0 and p1 and p0 > 0:
                    returns.append(p1 / p0 - 1)
            if not returns:
                return 0.0
            return sum(returns) / len(returns)

        portfolio_ret = _monthly_return(top_stocks)
        universe_ret = _monthly_return(set(eligible))

        # Nifty 50 monthly return
        n50_dates = sorted(nifty50_closes.keys())
        p0_n50 = _get_price_at(nifty50_closes, n50_dates, rebal_date, tolerance_days=5)
        p1_n50 = _get_price_at(nifty50_closes, n50_dates, next_rebal, tolerance_days=5)
        nifty50_ret = (p1_n50 / p0_n50 - 1) if (p0_n50 and p1_n50 and p0_n50 > 0) else 0.0

        # ── Step 3: Compute costs ─────────────────────────────────────────
        # Stocks entering or exiting the portfolio
        entries = top_stocks - prior_portfolio
        exits = prior_portfolio - top_stocks
        n_trades = len(entries) + len(exits)

        cost_inr = 0.0
        if n_trades > 0:
            # Approximate position size per stock
            pos_size = portfolio_inr / max(n_top, 1)
            cost_inr = _compute_round_trip_cost(pos_size, n_trades)
            cost_pct = cost_inr / portfolio_inr
        else:
            cost_pct = 0.0

        net_portfolio_ret = portfolio_ret - cost_pct
        total_cost_inr += cost_inr
        prior_portfolio = top_stocks

        portfolio_monthly_returns.append(net_portfolio_ret)
        benchmark_monthly_returns.append(universe_ret)
        nifty50_monthly_returns.append(nifty50_ret)

        monthly_records.append({
            "date": rebal_date.isoformat(),
            "n_eligible": n_eligible,
            "n_portfolio": len(top_stocks),
            "n_trades": n_trades,
            "portfolio_ret": round(portfolio_ret * 100, 2),
            "net_portfolio_ret": round(net_portfolio_ret * 100, 2),
            "universe_ret": round(universe_ret * 100, 2),
            "nifty50_ret": round(nifty50_ret * 100, 2),
            "excess_vs_universe": round((net_portfolio_ret - universe_ret) * 100, 2),
            "cost_pct": round(cost_pct * 100, 3),
        })

        if i % 6 == 0:
            logger.info(
                "Rebal %s: eligible=%d portfolio=%d n_trades=%d "
                "gross=%.1f%% net=%.1f%% bench=%.1f%%",
                rebal_date, n_eligible, len(top_stocks), n_trades,
                portfolio_ret * 100, net_portfolio_ret * 100, universe_ret * 100,
            )

    # ── Metrics ────────────────────────────────────────────────────────────

    n_months = len(portfolio_monthly_returns)
    if n_months == 0:
        logger.error("No monthly returns computed — check data")
        return

    years = n_months / 12
    total_portfolio_ret = 1.0
    total_bench_ret = 1.0
    total_n50_ret = 1.0
    for pr, br, nr in zip(portfolio_monthly_returns, benchmark_monthly_returns, nifty50_monthly_returns):
        total_portfolio_ret *= (1 + pr)
        total_bench_ret *= (1 + br)
        total_n50_ret *= (1 + nr)

    total_portfolio_ret -= 1
    total_bench_ret -= 1
    total_n50_ret -= 1

    portfolio_cagr = _cagr(total_portfolio_ret, years)
    bench_cagr = _cagr(total_bench_ret, years)
    n50_cagr = _cagr(total_n50_ret, years)
    alpha_vs_bench = portfolio_cagr - bench_cagr

    sharpe = _sharpe(portfolio_monthly_returns)
    bench_sharpe = _sharpe(benchmark_monthly_returns)
    max_dd = _max_drawdown(portfolio_monthly_returns)
    bench_max_dd = _max_drawdown(benchmark_monthly_returns)

    excess_rets = [pr - br for pr, br in zip(portfolio_monthly_returns, benchmark_monthly_returns)]
    win_months = sum(1 for e in excess_rets if e > 0)
    win_rate = win_months / n_months * 100 if n_months > 0 else 0

    # ── Tier verdict per criteria doc ──────────────────────────────────────

    tier = "OVERRIDE"
    verdict_notes = []

    if alpha_vs_bench * 100 > 7 and sharpe > 0.8 and max_dd < 0.40 and win_rate > 55:
        tier = "TIER_1"
        verdict_notes.append("All Tier 1 conditions met")
    elif alpha_vs_bench * 100 > 3 and sharpe > 0.5 and max_dd < 0.50 and win_rate > 50:
        tier = "TIER_2"
        verdict_notes.append("Tier 2: acceptable but caution warranted")
    else:
        reasons = []
        if alpha_vs_bench * 100 <= 3:
            reasons.append(f"Alpha {alpha_vs_bench*100:.1f}pp ≤ 3pp threshold")
        if sharpe <= 0.5:
            reasons.append(f"Sharpe {sharpe:.2f} ≤ 0.50")
        if max_dd >= 0.50:
            reasons.append(f"MaxDD {max_dd*100:.1f}% ≥ 50%")
        if win_rate <= 50:
            reasons.append(f"Win rate {win_rate:.0f}% ≤ 50%")
        verdict_notes = reasons

    # ── Print results ──────────────────────────────────────────────────────

    sep = "=" * 72
    print()
    print(sep)
    skip_label = f" | {args.skip_days}-day skip" if args.skip_days else ""
    print(f"NIFTY 500 12-MONTH MOMENTUM BACKTEST{skip_label}  |  {args.start} → {end}")
    print(sep)
    print(f"{'Months simulated':<35}: {n_months}")
    print(f"{'Avg eligible stocks/month':<35}: {sum(r['n_eligible'] for r in monthly_records) / n_months:.0f}")
    print(f"{'Avg portfolio size/month':<35}: {sum(r['n_portfolio'] for r in monthly_records) / n_months:.0f}")
    print(f"{'Total rebalance cost (₹)':<35}: {total_cost_inr:,.0f}")
    print()
    print(f"{'Metric':<35}  {'Portfolio':>12}  {'EW Universe':>12}  {'Nifty 50':>12}")
    print("-" * 72)
    print(f"{'Total Return':<35}  {total_portfolio_ret*100:>11.1f}%  {total_bench_ret*100:>11.1f}%  {total_n50_ret*100:>11.1f}%")
    print(f"{'CAGR':<35}  {portfolio_cagr*100:>11.1f}%  {bench_cagr*100:>11.1f}%  {n50_cagr*100:>11.1f}%")
    print(f"{'Alpha vs EW universe (CAGR)':<35}  {alpha_vs_bench*100:>+11.1f}%")
    print(f"{'Sharpe ratio (ann.)':<35}  {sharpe:>12.2f}  {bench_sharpe:>12.2f}")
    print(f"{'Max drawdown':<35}  {max_dd*100:>11.1f}%  {bench_max_dd*100:>11.1f}%")
    print(f"{'Win rate (months > bench)':<35}  {win_rate:>11.1f}%")
    print()
    print(sep)
    print(f"VERDICT: {tier}")
    for note in verdict_notes:
        print(f"  • {note}")
    print(sep)
    print()
    print("TIER 1  = Proceed: build live monthly rebalancer (alpha > 7pp, Sharpe > 0.8)")
    print("TIER 2  = Paper trade 3 months (alpha 3-7pp, Sharpe 0.5-0.8)")
    print("OVERRIDE = Hypothesis disproven")
    print()
    print("NOTE: Survivorship bias in current Nifty 500 composition overstates CAGR by ~2-3pp.")

    # ── Monthly detail table ────────────────────────────────────────────────
    print()
    print("MONTHLY PERFORMANCE (last 12 months):")
    print(f"{'Month':<12} {'Port%':>7}  {'Net%':>7}  {'Bench%':>7}  {'Excess':>7}  {'Cost%':>7}  {'N_stocks':>8}")
    print("-" * 65)
    for rec in monthly_records[-12:]:
        print(
            f"{rec['date']:<12} {rec['portfolio_ret']:>6.1f}%  "
            f"{rec['net_portfolio_ret']:>6.1f}%  "
            f"{rec['universe_ret']:>6.1f}%  "
            f"{rec['excess_vs_universe']:>+6.1f}%  "
            f"{rec['cost_pct']:>6.3f}%  "
            f"{rec['n_portfolio']:>8}"
        )

    # ── Save report ─────────────────────────────────────────────────────────

    out = Path("reports") / f"momentum_nifty500_{date.today()}.md"
    out.parent.mkdir(exist_ok=True)
    lines = [
        f"# Nifty 500 12-Month Momentum Backtest — {date.today()}",
        f"Period: {args.start} → {end} | Universe: Nifty 500 | Top {top_pct}%",
        "",
        "## Summary Metrics",
        "",
        "| Metric | Portfolio | EW Universe | Nifty 50 |",
        "|---|---|---|---|",
        f"| Total Return | {total_portfolio_ret*100:.1f}% | {total_bench_ret*100:.1f}% | {total_n50_ret*100:.1f}% |",
        f"| CAGR | {portfolio_cagr*100:.1f}% | {bench_cagr*100:.1f}% | {n50_cagr*100:.1f}% |",
        f"| Alpha vs EW | {alpha_vs_bench*100:+.1f}pp | | |",
        f"| Sharpe | {sharpe:.2f} | {bench_sharpe:.2f} | |",
        f"| Max Drawdown | {max_dd*100:.1f}% | {bench_max_dd*100:.1f}% | |",
        f"| Win Rate | {win_rate:.0f}% | | |",
        f"| Total Cost (₹) | {total_cost_inr:,.0f} | | |",
        "",
        f"## Verdict: **{tier}**",
        "",
        "### Reasons:",
    ]
    for note in verdict_notes:
        lines.append(f"- {note}")
    lines += [
        "",
        "### Per-criteria checklist:",
        f"- Alpha > 7pp: {'✅' if alpha_vs_bench*100 > 7 else '❌'} ({alpha_vs_bench*100:.1f}pp)",
        f"- Sharpe > 0.8: {'✅' if sharpe > 0.8 else '❌'} ({sharpe:.2f})",
        f"- Max DD < 40%: {'✅' if max_dd < 0.40 else '❌'} ({max_dd*100:.1f}%)",
        f"- Win rate > 55%: {'✅' if win_rate > 55 else '❌'} ({win_rate:.0f}%)",
        "",
        "> Survivorship bias note: current Nifty 500 composition overstates CAGR by ~2-3pp.",
        "",
        "## Monthly Returns",
        "",
        "| Month | Port% | Net% | Bench% | Excess | Cost% | N_stocks |",
        "|---|---|---|---|---|---|---|",
    ]
    for rec in monthly_records:
        lines.append(
            f"| {rec['date']} | {rec['portfolio_ret']} | {rec['net_portfolio_ret']} "
            f"| {rec['universe_ret']} | {rec['excess_vs_universe']} "
            f"| {rec['cost_pct']} | {rec['n_portfolio']} |"
        )
    out.write_text("\n".join(lines), encoding='utf-8')
    logger.info("Report saved: %s", out)


if __name__ == "__main__":
    main()
