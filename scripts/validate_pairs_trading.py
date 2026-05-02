"""
Pairs Trading Validation — Phase 1

Reads daily OHLCV from ohlcv_cache, runs cointegration + z-score
strategy on all 10 pairs in data/pairs_universe.csv, produces
walk-forward metrics, and issues tier verdicts per pre-committed
criteria in docs/strategy_validation/pairs_trading_criteria.md.

Methodology (pre-committed, do not change):
  - Engle-Granger cointegration (statsmodels coint)
  - OLS hedge ratio on training window
  - Z-score entry |z| > 2.0, exit |z| < 0.5, stop |z| > 4.0
  - Walk-forward: 12-month train, 3-month test, 3-month roll
  - Full Indian equity cost model (brokerage + STT + exchange + GST + stamp + borrow)

Usage:
    python scripts/validate_pairs_trading.py
    python scripts/validate_pairs_trading.py --from 2021-01-01 --mc-runs 5000
    python scripts/validate_pairs_trading.py --pair HDFCBANK,ICICIBANK
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import os
import random
import statistics
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pairs_val")


# ── Strategy constants (pre-committed) ─────────────────────────────────────

Z_ENTRY  = 2.0    # |z| > Z_ENTRY  → open position
Z_EXIT   = 0.5    # |z| < Z_EXIT   → close for profit
Z_STOP   = 4.0    # |z| > Z_STOP   → stop loss (cointegration break)
COOLDOWN_DAYS = 30  # skip pair N days after stop trigger

WF_TRAIN_MONTHS = 12
WF_TEST_MONTHS  =  3

# Cost model (equity delivery, per criteria doc)
BROKERAGE       = 20.0      # ₹20 flat per order
STT_SELL_PCT    = 0.00025   # 0.025% on sell (intraday/SLB model)
EXCHANGE_PCT    = 0.0000345 # 0.00345% per side
GST_PCT         = 0.18      # 18% on (brokerage + exchange)
STAMP_DUTY_PCT  = 0.00015   # 0.015% on buy side
BORROW_COST_DAY = 0.0004    # 0.04% per day on short-leg notional

# Slippage tiers (all pairs are Nifty 50 or Nifty 100 components)
SLIPPAGE_NIFTY50  = 0.0005  # 0.05%
SLIPPAGE_NIFTY100 = 0.0010  # 0.10%

NIFTY50_SYMBOLS = {
    "HDFCBANK", "ICICIBANK", "TCS", "INFY", "RELIANCE",
    "MARUTI", "AXISBANK", "KOTAKBANK", "M&M", "NTPC",
}

# Tier thresholds (from pairs_trading_criteria.md)
TIER1_WF_SHARPE    = 1.0
TIER1_MAX_DD       = 0.15   # 15%
TIER1_MIN_TRADES   = 30
TIER1_COINT_PCT    = 0.80   # ≥ 80% of WF windows must pass coint test

TIER2_WF_SHARPE_LO = 0.6
TIER2_WF_SHARPE_HI = 1.0
TIER2_MAX_DD       = 0.25   # 25%
TIER2_MIN_TRADES   = 30

SUSPICIOUS_SHARPE  = 3.0    # flag for look-ahead investigation


# ── Cost model ───────────────────────────────────────────────────────────────

def _slippage(symbol: str) -> float:
    return SLIPPAGE_NIFTY50 if symbol in NIFTY50_SYMBOLS else SLIPPAGE_NIFTY100


def _cost_open(symbol_long: str, symbol_short: str, price_long: float, price_short: float) -> float:
    """All-in cost to OPEN one unit of the pairs position."""
    # Long leg: buy at ask = price * (1 + slippage)
    notional_long  = price_long  * (1 + _slippage(symbol_long))
    cost_long  = BROKERAGE + notional_long * EXCHANGE_PCT + notional_long * STAMP_DUTY_PCT
    cost_long += (BROKERAGE + notional_long * EXCHANGE_PCT) * GST_PCT

    # Short leg: sell at bid = price * (1 - slippage)
    notional_short = price_short * (1 - _slippage(symbol_short))
    cost_short = BROKERAGE + notional_short * EXCHANGE_PCT + notional_short * STT_SELL_PCT
    cost_short += (BROKERAGE + notional_short * EXCHANGE_PCT) * GST_PCT

    return cost_long + cost_short


def _cost_close(symbol_long: str, symbol_short: str, price_long: float, price_short: float) -> float:
    """All-in cost to CLOSE one unit of the pairs position."""
    # Long leg: sell at bid
    notional_long = price_long * (1 - _slippage(symbol_long))
    cost_long  = BROKERAGE + notional_long * EXCHANGE_PCT + notional_long * STT_SELL_PCT
    cost_long += (BROKERAGE + notional_long * EXCHANGE_PCT) * GST_PCT

    # Short leg: buy to cover at ask
    notional_short = price_short * (1 + _slippage(symbol_short))
    cost_short = BROKERAGE + notional_short * EXCHANGE_PCT + notional_short * STAMP_DUTY_PCT
    cost_short += (BROKERAGE + notional_short * EXCHANGE_PCT) * GST_PCT

    return cost_long + cost_short


def _borrow_cost(price_short: float, holding_days: int) -> float:
    return price_short * BORROW_COST_DAY * holding_days


# ── Data loading ──────────────────────────────────────────────────────────────

def _load_prices(session, symbol: str, start: date, end: date) -> dict[date, float]:
    from sqlalchemy import text
    rows = session.execute(text("""
        SELECT bar_date, close
        FROM ohlcv_cache
        WHERE ticker = :sym AND interval = '1d'
          AND bar_date BETWEEN :s AND :e
          AND close IS NOT NULL AND close > 0
        ORDER BY bar_date
    """), {"sym": symbol, "s": start.isoformat(), "e": end.isoformat()}).fetchall()
    return {r.bar_date: float(r.close) for r in rows}


def _aligned_series(prices_a: dict, prices_b: dict) -> tuple[list[date], list[float], list[float]]:
    """Return dates present in both series, aligned."""
    common = sorted(set(prices_a) & set(prices_b))
    pa = [prices_a[d] for d in common]
    pb = [prices_b[d] for d in common]
    return common, pa, pb


# ── Cointegration & OLS ───────────────────────────────────────────────────────

def _engle_granger_pvalue(y: list[float], x: list[float]) -> float:
    """Engle-Granger cointegration p-value. y = leg_a, x = leg_b."""
    try:
        from statsmodels.tsa.stattools import coint
        import numpy as np
        _, pvalue, _ = coint(np.array(y), np.array(x))
        return float(pvalue)
    except Exception as e:
        logger.warning("Cointegration test failed: %s", e)
        return 1.0


def _ols_hedge_ratio(y: list[float], x: list[float]) -> float:
    """OLS regression coefficient (β): y = α + β·x + ε. Returns β."""
    try:
        import numpy as np
        x_arr = np.array(x)
        y_arr = np.array(y)
        X = np.column_stack([np.ones(len(x_arr)), x_arr])
        beta = np.linalg.lstsq(X, y_arr, rcond=None)[0]
        return float(beta[1])
    except Exception as e:
        logger.warning("OLS failed: %s", e)
        return 1.0


def _build_spread(pa: list[float], pb: list[float], hedge: float) -> list[float]:
    return [a - hedge * b for a, b in zip(pa, pb)]


def _zscore_series(spread: list[float], mean: float, std: float) -> list[float]:
    if std <= 0:
        return [0.0] * len(spread)
    return [(s - mean) / std for s in spread]


# ── Single-window simulation ──────────────────────────────────────────────────

def _simulate_window(
    dates: list[date],
    z_series: list[float],
    prices_a: list[float],
    prices_b: list[float],
    hedge_ratio: float,
    sym_a: str,
    sym_b: str,
) -> list[dict]:
    """
    Simulate pairs strategy on one test window.

    Position states:
      FLAT: no position
      LONG_SPREAD: long A, short B  (entered when z < -Z_ENTRY, spread too low)
      SHORT_SPREAD: short A, long B (entered when z > +Z_ENTRY, spread too high)

    Returns list of closed trade dicts.
    """
    trades: list[dict] = []
    position = "FLAT"
    entry_date: date | None = None
    entry_z:    float = 0.0
    entry_pa:   float = 0.0
    entry_pb:   float = 0.0
    cooldown_until: date | None = None

    for i, (d, z, pa, pb) in enumerate(zip(dates, z_series, prices_a, prices_b)):
        # Respect cooldown after stop
        if cooldown_until and d <= cooldown_until:
            continue

        if position == "FLAT":
            if z > Z_ENTRY:
                # Spread too wide: short A, long B
                position   = "SHORT_SPREAD"
                entry_date = d
                entry_z    = z
                entry_pa   = pa
                entry_pb   = pb

            elif z < -Z_ENTRY:
                # Spread too narrow: long A, short B
                position   = "LONG_SPREAD"
                entry_date = d
                entry_z    = z
                entry_pa   = pa
                entry_pb   = pb

        else:
            holding_days = (d - entry_date).days

            # Stop: cointegration break (z exceeded Z_STOP)
            abs_z = abs(z)
            if abs_z > Z_STOP:
                pnl = _calc_pnl(position, entry_pa, entry_pb, pa, pb,
                                sym_a, sym_b, hedge_ratio, holding_days)
                trades.append({
                    "entry_date":   entry_date, "exit_date": d,
                    "holding_days": holding_days, "position": position,
                    "entry_z": round(entry_z, 3), "exit_z": round(z, 3),
                    "pnl": round(pnl, 2), "exit_reason": "stop",
                })
                position = "FLAT"
                cooldown_until = d + timedelta(days=COOLDOWN_DAYS)
                continue

            # Exit: mean reversion (|z| < Z_EXIT)
            exit_signal = (
                (position == "SHORT_SPREAD" and z < Z_EXIT) or
                (position == "LONG_SPREAD"  and z > -Z_EXIT)
            )
            if exit_signal:
                pnl = _calc_pnl(position, entry_pa, entry_pb, pa, pb,
                                sym_a, sym_b, hedge_ratio, holding_days)
                trades.append({
                    "entry_date":   entry_date, "exit_date": d,
                    "holding_days": holding_days, "position": position,
                    "entry_z": round(entry_z, 3), "exit_z": round(z, 3),
                    "pnl": round(pnl, 2), "exit_reason": "reversion",
                })
                position = "FLAT"

    return trades


def _calc_pnl(
    position: str,
    entry_pa: float, entry_pb: float,
    exit_pa: float,  exit_pb: float,
    sym_a: str, sym_b: str,
    hedge_ratio: float,
    holding_days: int,
) -> float:
    """
    P&L for one closed trade (1 unit: 1 share of A vs hedge_ratio shares of B).
    Positive = profit.
    """
    if position == "LONG_SPREAD":
        # Long A, short (hedge_ratio × B)
        pnl_a = exit_pa - entry_pa
        pnl_b = -(exit_pb - entry_pb) * hedge_ratio
        open_cost  = _cost_open(sym_a, sym_b, entry_pa, entry_pb * hedge_ratio)
        close_cost = _cost_close(sym_a, sym_b, exit_pa, exit_pb * hedge_ratio)
        borrow     = _borrow_cost(entry_pb * hedge_ratio, holding_days)

    else:  # SHORT_SPREAD
        # Short A, long (hedge_ratio × B)
        pnl_a = -(exit_pa - entry_pa)
        pnl_b = (exit_pb - entry_pb) * hedge_ratio
        open_cost  = _cost_open(sym_b, sym_a, entry_pb * hedge_ratio, entry_pa)
        close_cost = _cost_close(sym_b, sym_a, exit_pb * hedge_ratio, exit_pa)
        borrow     = _borrow_cost(entry_pa, holding_days)

    return pnl_a + pnl_b - open_cost - close_cost - borrow


# ── Walk-forward ──────────────────────────────────────────────────────────────

def _add_months(d: date, m: int) -> date:
    month = d.month + m
    year  = d.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    return d.replace(year=year, month=month, day=1)


def _sharpe(pnl_list: list[float], span_days: float = 0.0) -> float:
    if len(pnl_list) < 2:
        return 0.0
    mean = statistics.mean(pnl_list)
    std  = statistics.stdev(pnl_list)
    if std == 0:
        return 0.0
    if span_days > 0:
        tpy = len(pnl_list) * 365.0 / span_days
        return mean / std * math.sqrt(tpy)
    return mean / std * math.sqrt(252)


def walk_forward_pair(
    pair: dict,
    dates: list[date],
    prices_a: list[float],
    prices_b: list[float],
) -> dict:
    """Run walk-forward validation on one pair."""
    sym_a = pair["leg_a_symbol"]
    sym_b = pair["leg_b_symbol"]

    if len(dates) < WF_TRAIN_MONTHS * 20:
        return {"error": f"insufficient data: {len(dates)} bars"}

    start_date = dates[0]
    end_date   = dates[-1]
    date_to_idx = {d: i for i, d in enumerate(dates)}

    windows: list[dict] = []
    months_elapsed = 0

    while True:
        train_start = _add_months(start_date, months_elapsed)
        train_end   = _add_months(start_date, months_elapsed + WF_TRAIN_MONTHS)
        test_start  = train_end
        test_end    = _add_months(start_date, months_elapsed + WF_TRAIN_MONTHS + WF_TEST_MONTHS)

        if test_end > end_date + timedelta(days=31):
            break

        # Slice indices
        train_idx = [i for i, d in enumerate(dates) if train_start <= d < train_end]
        test_idx  = [i for i, d in enumerate(dates) if test_start  <= d < test_end]

        if len(train_idx) < 60 or len(test_idx) < 10:
            months_elapsed += WF_TEST_MONTHS
            continue

        pa_train = [prices_a[i] for i in train_idx]
        pb_train = [prices_b[i] for i in train_idx]
        pa_test  = [prices_a[i] for i in test_idx]
        pb_test  = [prices_b[i] for i in test_idx]
        d_test   = [dates[i]    for i in test_idx]

        # Cointegration test on TRAINING window only
        coint_pval = _engle_granger_pvalue(pa_train, pb_train)

        # Hedge ratio from training window only (no look-ahead)
        hedge = _ols_hedge_ratio(pa_train, pb_train)

        # Z-score parameters from training spread (no look-ahead)
        spread_train = _build_spread(pa_train, pb_train, hedge)
        train_mean = statistics.mean(spread_train)
        train_std  = statistics.stdev(spread_train) if len(spread_train) > 1 else 1.0

        # Apply to test window
        spread_test = _build_spread(pa_test, pb_test, hedge)
        z_test = _zscore_series(spread_test, train_mean, train_std)

        # Simulate
        trades = _simulate_window(d_test, z_test, pa_test, pb_test,
                                  hedge, sym_a, sym_b)

        pnl_list = [t["pnl"] for t in trades]
        total_pnl = sum(pnl_list)
        span = (d_test[-1] - d_test[0]).days if len(d_test) > 1 else 91

        windows.append({
            "train_start": train_start.isoformat(),
            "train_end":   train_end.isoformat(),
            "test_start":  test_start.isoformat(),
            "test_end":    test_end.isoformat(),
            "coint_pval":  round(coint_pval, 4),
            "hedge_ratio": round(hedge, 4),
            "n_trades":    len(trades),
            "total_pnl":   round(total_pnl, 2),
            "sharpe":      round(_sharpe(pnl_list, float(span)), 3),
            "profitable":  total_pnl > 0,
            "trades":      trades,
        })

        months_elapsed += WF_TEST_MONTHS
        if months_elapsed > 120:
            break

    if not windows:
        return {"error": "no walk-forward windows produced"}

    # Aggregate across windows
    all_oos_pnl = []
    all_oos_dates: list[date] = []
    for w in windows:
        for t in w.get("trades", []):
            all_oos_pnl.append(t["pnl"])
            all_oos_dates.append(t["exit_date"])

    if not all_oos_pnl:
        return {"error": "no trades in any walk-forward window"}

    all_oos_pnl_sorted = [p for _, p in sorted(zip(all_oos_dates, all_oos_pnl))]
    oos_span = (max(all_oos_dates) - min(all_oos_dates)).days if len(all_oos_dates) > 1 else 365

    # Equity curve + max drawdown
    equity   = 0.0
    peak     = 0.0
    max_dd   = 0.0
    max_dd_basis = max(sum(all_oos_pnl), 1.0)  # relative to total gain
    for p in all_oos_pnl_sorted:
        equity += p
        if equity > peak:
            peak = equity
        if peak > 0:
            dd = (peak - equity) / peak
            if dd > max_dd:
                max_dd = dd

    win_count = sum(1 for p in all_oos_pnl if p > 0)
    coint_pass = sum(1 for w in windows if w["coint_pval"] < 0.05)
    coint_pct  = coint_pass / len(windows) if windows else 0.0

    profitable_windows = sum(1 for w in windows if w["profitable"])

    return {
        "n_windows":          len(windows),
        "profitable_windows": profitable_windows,
        "wf_consistency":     round(profitable_windows / len(windows), 3),
        "n_trades":           len(all_oos_pnl),
        "total_pnl":          round(sum(all_oos_pnl), 2),
        "wf_sharpe":          round(_sharpe(all_oos_pnl_sorted, float(oos_span)), 3),
        "max_drawdown":       round(max_dd, 4),
        "win_rate":           round(win_count / len(all_oos_pnl), 3),
        "coint_pass_pct":     round(coint_pct, 3),
        "windows":            windows,
    }


# ── Monte Carlo on OOS trade sequence ────────────────────────────────────────

def _monte_carlo(pnl_list: list[float], n: int = 5000) -> dict:
    if len(pnl_list) < 5:
        return {}
    max_dds = []
    for _ in range(n):
        perm = random.sample(pnl_list, len(pnl_list))
        eq = pk = max_dd = 0.0
        for p in perm:
            eq += p
            if eq > pk:
                pk = eq
            if pk > 0:
                dd = (pk - eq) / pk
                if dd > max_dd:
                    max_dd = dd
        max_dds.append(max_dd)
    max_dds.sort()
    n_mc = len(max_dds)
    return {
        "p50": round(max_dds[int(0.50 * n_mc)], 4),
        "p75": round(max_dds[int(0.75 * n_mc)], 4),
        "p95": round(max_dds[int(0.95 * n_mc)], 4),
        "p99": round(max_dds[int(0.99 * n_mc)], 4),
    }


# ── Full cointegration on the entire window ───────────────────────────────────

def _full_coint(prices_a: list[float], prices_b: list[float]) -> dict:
    pval = _engle_granger_pvalue(prices_a, prices_b)
    return {
        "engle_granger_pval": round(pval, 4),
        "cointegrated_5pct":  pval < 0.05,
    }


# ── Tier verdict ──────────────────────────────────────────────────────────────

def _tier_verdict(wf: dict) -> str:
    if wf.get("error"):
        return "ERROR"

    n_trades   = wf.get("n_trades", 0)
    wf_sharpe  = wf.get("wf_sharpe", 0)
    max_dd     = wf.get("max_drawdown", 1.0)
    coint_pct  = wf.get("coint_pass_pct", 0)

    if wf_sharpe > SUSPICIOUS_SHARPE:
        return f"SUSPICIOUS (Sharpe {wf_sharpe:.1f} > {SUSPICIOUS_SHARPE} — check for look-ahead)"

    if n_trades < TIER1_MIN_TRADES:
        return f"OVERRIDE (trade count {n_trades} < {TIER1_MIN_TRADES})"

    if (wf_sharpe >= TIER1_WF_SHARPE and
            max_dd <= TIER1_MAX_DD and
            n_trades >= TIER1_MIN_TRADES and
            coint_pct >= TIER1_COINT_PCT):
        return "TIER_1: Strong validation"

    if (TIER2_WF_SHARPE_LO <= wf_sharpe < TIER2_WF_SHARPE_HI and
            max_dd <= TIER2_MAX_DD and
            n_trades >= TIER2_MIN_TRADES):
        return "TIER_2: Marginal — one iteration permitted"

    return "TIER_3: Failed"


# ── Markdown report ───────────────────────────────────────────────────────────

def _md_table(headers: list[str], rows: list[list]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, c in enumerate(row):
            widths[i] = max(widths[i], len(str(c)))
    def fmt(cells):
        return "| " + " | ".join(str(c).ljust(widths[i]) for i, c in enumerate(cells)) + " |"
    sep = "| " + " | ".join("-" * w for w in widths) + " |"
    return "\n".join([fmt(headers), sep] + [fmt(r) for r in rows])


def write_report(pair_results: list[dict], output_path: Path) -> None:
    lines = [
        "# Pairs Trading Validation Report",
        f"\n**Run date:** {date.today()}",
        "**Criteria:** docs/strategy_validation/pairs_trading_criteria.md",
        "",
        "---",
        "",
        "## Summary",
        "",
    ]

    summary_rows = []
    tier1_count = 0
    tier2_count = 0

    for pr in pair_results:
        pair = pr["pair"]
        wf   = pr.get("walk_forward", {})
        verdict = pr.get("tier_verdict", "—")
        if "TIER_1" in verdict:
            tier1_count += 1
        elif "TIER_2" in verdict:
            tier2_count += 1
        summary_rows.append([
            f"{pair['leg_a_symbol']}/{pair['leg_b_symbol']}",
            pair["sector"],
            wf.get("n_trades", "—"),
            f"{wf.get('wf_sharpe', 0):.3f}" if not wf.get("error") else "—",
            f"{wf.get('max_drawdown', 0)*100:.1f}%" if not wf.get("error") else "—",
            f"{wf.get('coint_pass_pct', 0):.0%}" if not wf.get("error") else "—",
            verdict.split(":")[0],
        ])

    lines.append(_md_table(
        ["Pair", "Sector", "Trades", "WF Sharpe", "Max DD", "Coint %", "Verdict"],
        summary_rows,
    ))
    lines.append("")

    # Universe decision
    lines += [
        "## Universe-level decision",
        "",
    ]
    if tier1_count >= 3:
        lines.append(f"**{tier1_count} pairs at Tier 1 → DEPLOY as multi-pair portfolio (paper trading first)**")
    elif tier1_count >= 1:
        lines.append(f"**{tier1_count} pairs at Tier 1 → Run OOS confirmation on 2018–2022 before deploy**")
    else:
        lines.append("**0 pairs at Tier 1 → Hypothesis disproven. Move to next path.**")
    lines.append("")

    # Per-pair detail
    lines += ["---", "", "## Per-pair detail", ""]

    for pr in pair_results:
        pair    = pr["pair"]
        wf      = pr.get("walk_forward", {})
        coint_f = pr.get("full_coint", {})
        mc      = pr.get("monte_carlo", {})
        verdict = pr.get("tier_verdict", "—")

        lines += [
            f"### {pair['leg_a_symbol']} / {pair['leg_b_symbol']} — {pair['sector']}",
            "",
            f"*{pair['structural_rationale']}*",
            "",
            f"**Verdict: {verdict}**",
            "",
        ]

        if wf.get("error"):
            lines += [f"Error: {wf['error']}", ""]
            continue

        lines += [
            _md_table(
                ["Metric", "Value", "Threshold"],
                [
                    ["Trades (OOS total)", wf.get("n_trades", "—"), "≥ 30"],
                    ["WF Sharpe", f"{wf.get('wf_sharpe', 0):.3f}", "> 1.0 (T1) / 0.6–1.0 (T2)"],
                    ["Max drawdown", f"{wf.get('max_drawdown', 0)*100:.1f}%", "< 15% (T1) / < 25% (T2)"],
                    ["Win rate", f"{wf.get('win_rate', 0):.1%}", "—"],
                    ["WF consistency", f"{wf.get('wf_consistency', 0):.0%}", "—"],
                    ["Coint windows (p<0.05)", f"{wf.get('coint_pass_pct', 0):.0%}", "≥ 80% (T1)"],
                    ["Full-data coint p-val", f"{coint_f.get('engle_granger_pval', '—')}", "< 0.05"],
                    ["MC P95 max DD", f"{mc.get('p95', 0)*100:.1f}%" if mc else "—", "—"],
                ],
            ),
            "",
        ]

        # Walk-forward window table
        if wf.get("windows"):
            lines += ["**Walk-forward windows:**", ""]
            wf_rows = [
                [
                    w["test_start"][:7], w["test_end"][:7],
                    w["n_trades"],
                    f"₹{w['total_pnl']:,.0f}",
                    f"{w['coint_pval']:.3f}",
                    "✓" if w["profitable"] else "✗",
                ]
                for w in wf["windows"]
            ]
            lines += [
                _md_table(["Test start", "Test end", "N", "P&L", "Coint p", "Profit?"], wf_rows),
                "",
            ]

    lines += [
        "---",
        "",
        "## Pre-committed criteria reference",
        "",
        _md_table(
            ["Tier", "WF Sharpe", "Max DD", "Coint %", "Min trades"],
            [
                ["Tier 1", "> 1.0", "< 15%", "≥ 80%", "≥ 30"],
                ["Tier 2", "0.6–1.0", "< 25%", "—", "≥ 30"],
                ["Tier 3", "< 0.6", "> 25%", "—", "—"],
            ],
        ),
        "",
        "_Criteria committed 2026-05-02, before any backtest run._",
    ]

    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Report written: %s", output_path)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Pairs trading validation")
    parser.add_argument("--from",      dest="from_date", default="2021-01-01")
    parser.add_argument("--to",        dest="to_date",   default=None)
    parser.add_argument("--mc-runs",   type=int,         default=5000)
    parser.add_argument("--pair",      default=None,     help="Single pair to test, e.g. HDFCBANK,ICICIBANK")
    parser.add_argument("--output-dir",default="reports")
    args = parser.parse_args()

    from_date = date.fromisoformat(args.from_date)
    to_date   = date.fromisoformat(args.to_date) if args.to_date else date.today()

    # Load pairs universe
    universe_path = Path("data/pairs_universe.csv")
    pairs: list[dict] = []
    with universe_path.open() as f:
        for row in csv.DictReader(f):
            if args.pair:
                syms = set(args.pair.upper().split(","))
                if not {row["leg_a_symbol"], row["leg_b_symbol"]} == syms:
                    continue
            pairs.append(row)

    if not pairs:
        logger.error("No pairs matched. Check --pair argument or pairs_universe.csv.")
        sys.exit(1)

    logger.info("=== Pairs Trading Validation ===")
    logger.info("Period: %s → %s | Pairs: %d | MC runs: %d",
                from_date, to_date, len(pairs), args.mc_runs)

    from mcp_server.db import SessionLocal
    session = SessionLocal()

    pair_results = []
    try:
        for pair in pairs:
            sym_a = pair["leg_a_symbol"]
            sym_b = pair["leg_b_symbol"]
            label = f"{sym_a}/{sym_b}"

            logger.info("── %s ──", label)

            # Load prices
            pa_dict = _load_prices(session, sym_a, from_date, to_date)
            pb_dict = _load_prices(session, sym_b, from_date, to_date)

            if len(pa_dict) < 100 or len(pb_dict) < 100:
                logger.warning("%s: insufficient price data (%d/%d bars)", label, len(pa_dict), len(pb_dict))
                pair_results.append({
                    "pair": pair,
                    "walk_forward": {"error": f"insufficient price data ({len(pa_dict)}/{len(pb_dict)} bars)"},
                    "tier_verdict": "ERROR",
                })
                continue

            dates, pa, pb = _aligned_series(pa_dict, pb_dict)
            logger.info("%s: %d aligned bars (%s → %s)", label, len(dates), dates[0], dates[-1])

            # Full-window cointegration (informational)
            coint_full = _full_coint(pa, pb)
            logger.info("%s: full coint p=%.4f (%s)", label,
                        coint_full["engle_granger_pval"],
                        "PASS" if coint_full["cointegrated_5pct"] else "fail")

            # Walk-forward
            wf = walk_forward_pair(pair, dates, pa, pb)

            if wf.get("error"):
                logger.warning("%s: WF error — %s", label, wf["error"])
                pair_results.append({
                    "pair": pair, "full_coint": coint_full,
                    "walk_forward": wf, "tier_verdict": "ERROR",
                })
                continue

            # Monte Carlo on OOS sequence
            oos_pnl = []
            for w in wf.get("windows", []):
                oos_pnl.extend(t["pnl"] for t in w.get("trades", []))
            mc = _monte_carlo(oos_pnl, args.mc_runs) if oos_pnl else {}

            verdict = _tier_verdict(wf)
            logger.info(
                "%s: trades=%d  WF_sharpe=%.3f  maxDD=%.1f%%  coint=%d/%d  → %s",
                label,
                wf["n_trades"], wf["wf_sharpe"],
                wf["max_drawdown"] * 100,
                int(wf["coint_pass_pct"] * wf["n_windows"]), wf["n_windows"],
                verdict.split(":")[0],
            )

            pair_results.append({
                "pair":         pair,
                "full_coint":   coint_full,
                "walk_forward": wf,
                "monte_carlo":  mc,
                "tier_verdict": verdict,
            })

    finally:
        session.close()

    # Universe decision
    tier1 = sum(1 for r in pair_results if "TIER_1" in r.get("tier_verdict", ""))
    tier2 = sum(1 for r in pair_results if "TIER_2" in r.get("tier_verdict", ""))

    print("\n" + "=" * 60)
    print("PAIRS TRADING VALIDATION — UNIVERSE SUMMARY")
    print("=" * 60)
    for r in pair_results:
        p = r["pair"]
        wf = r.get("walk_forward", {})
        print(f"  {p['leg_a_symbol']}/{p['leg_b_symbol']:<20} {r.get('tier_verdict','').split(':')[0]}")
    print()
    print(f"Tier 1: {tier1}   Tier 2: {tier2}   Other: {len(pair_results)-tier1-tier2}")
    print()
    if tier1 >= 3:
        print("UNIVERSE DECISION: DEPLOY (3+ Tier 1 pairs)")
    elif tier1 >= 1:
        print("UNIVERSE DECISION: OOS CONFIRM before deploy")
    else:
        print("UNIVERSE DECISION: HYPOTHESIS DISPROVEN → Path C")
    print("=" * 60)

    # Write outputs
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True)
    run_date = date.today().isoformat()

    json_path = output_dir / f"pairs_validation_{run_date}.json"
    md_path   = output_dir / f"pairs_validation_{run_date}.md"

    # Serialize (convert date objects)
    def _serial(obj):
        if isinstance(obj, date):
            return obj.isoformat()
        raise TypeError(f"not serializable: {type(obj)}")

    json_path.write_text(json.dumps(pair_results, indent=2, default=_serial), encoding="utf-8")
    logger.info("JSON written: %s", json_path)

    write_report(pair_results, md_path)


if __name__ == "__main__":
    main()
