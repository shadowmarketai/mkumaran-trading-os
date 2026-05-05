"""
BankNifty Short Strangle Validation — Weekend 2

Reads daily option OHLCV from options_chain_cache (NSE bhavcopy backfill)
and evaluates the pre-committed strategy specification from:
  docs/strategy_validation/banknifty_strangle_criteria.md

Strategy spec (pre-committed, DO NOT change):
  - Underlying: BankNifty weekly expiry
  - Structure: short strangle (naked)
  - Target delta: 0.15 per leg at entry
  - Entry: Monday close (first trading day of the expiry week)
  - Exit — profit: 50% of initial credit
  - Exit — stop: 2× initial credit (net debit)
  - Exit — time: expiry-day close
  - IV gate: skip if VIX percentile < 30th or > 80th (rolling 1-year)
  - Margin basis: ₹1,50,000 per strangle (SPAN + exposure estimate)
  - Lot size: 15 shares (BankNifty = 15)

Walk-forward: 12-month rolling train / 3-month test
Monte Carlo:  10,000 permutations of trade sequence
Regime:       VIX level bucket (low/mid/high) + BankNifty trend (above/below 200-EMA)

Usage:
    python scripts/validate_banknifty_strangle.py
    python scripts/validate_banknifty_strangle.py --from 2023-01-01 --mc-runs 5000
    python scripts/validate_banknifty_strangle.py --no-vix-gate
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_server.options_greeks import calculate_greeks  # shared BS implementation

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("strangle_val")


# ── Strategy constants (pre-committed — do not change) ─────────────────────

TARGET_DELTA       = 0.15
PROFIT_TARGET_PCT  = 0.50   # 50% of initial credit
STOP_LOSS_MULT     = 2.0    # 2× initial credit
LOT_SIZE           = 15     # BankNifty lot size
SPAN_MARGIN        = 150_000.0  # ₹1.5L per strangle (SPAN + exposure)
RFR                = 0.065  # RBI repo rate
BANKNIFTY_VOL_MULT = 1.30   # BankNifty vol ≈ 1.3× India VIX

# VIX gate thresholds (percentile, rolling 252 trading days)
VIX_LOW_PCT   = 0.30
VIX_HIGH_PCT  = 0.80

# Walk-forward parameters
WF_TRAIN_MONTHS = 12
WF_TEST_MONTHS  = 3

# Monthly variant — entry & exit timing
MONTHLY_ENTRY_DAYS_BEFORE = 25   # target entry DTE for monthly strangles
MONTHLY_TIME_EXIT_DTE     = 5    # exit when DTE ≤ this (avoids expiry gamma)

# Tier thresholds per expiry type
# (from pre-committed criteria docs in docs/strategy_validation/)
TIER_THRESHOLDS = {
    "weekly": {
        "t1_return": 25, "t1_sharpe": 1.0, "t1_dd": 35, "t1_consistency": 0.60, "t1_wr": 0.60,
        "t2_return_lo": 15, "t2_return_hi": 25, "t2_sharpe_lo": 0.5, "t2_sharpe_hi": 1.0,
        "t2_dd": 50, "t2_consistency": 0.50,
        "t3_return_lo": 5, "t3_return_hi": 15, "t3_sharpe_hi": 0.5,
        "min_trades": 50,
    },
    "monthly": {
        "t1_return": 18, "t1_sharpe": 0.9, "t1_dd": 30, "t1_consistency": 0.60, "t1_wr": 0.65,
        "t2_return_lo": 10, "t2_return_hi": 18, "t2_sharpe_lo": 0.5, "t2_sharpe_hi": 0.9,
        "t2_dd": 40, "t2_consistency": 0.50,
        "t3_return_lo": 5, "t3_return_hi": 10, "t3_sharpe_hi": 0.5,
        "min_trades": 30,
    },
}

# Cost model (from test_plan — matches backtester.py)
BROKERAGE_PER_ORDER = 20.0       # ₹20 flat per order (each leg each direction)
STT_SELL_PCT        = 0.000125   # 0.0125% on sell premium (securities transaction tax)
EXCHANGE_PCT        = 0.0005     # 0.05% of premium
GST_PCT             = 0.18       # 18% on (brokerage + exchange charges)
STAMP_DUTY_PCT      = 0.00003    # 0.003% on buy premium
SLIPPAGE_ATM_PCT    = 0.005      # 0.5% for ATM (within 1% moneyness)
SLIPPAGE_OTM_PCT    = 0.010      # 1.0% for OTM (1–3% moneyness)
SLIPPAGE_FAR_PCT    = 0.020      # 2.0% for far OTM (>3% moneyness)


# _norm_cdf and _bs_delta removed — using mcp_server.options_greeks.calculate_greeks


# ── Bid-ask spread model ────────────────────────────────────────────────────

def _spread_pct(strike: float, spot: float) -> float:
    moneyness = abs(strike - spot) / spot
    if moneyness < 0.01:
        return SLIPPAGE_ATM_PCT
    elif moneyness < 0.03:
        return SLIPPAGE_OTM_PCT
    else:
        return SLIPPAGE_FAR_PCT


def _sell_price(mid: float, strike: float, spot: float) -> float:
    """Effective sell (entry) price = mid - half_spread (selling at bid)."""
    sp = _spread_pct(strike, spot)
    return mid * (1.0 - sp / 2.0)


def _buy_price(mid: float, strike: float, spot: float) -> float:
    """Effective buy (exit) price = mid + half_spread (buying at ask)."""
    sp = _spread_pct(strike, spot)
    return mid * (1.0 + sp / 2.0)


# ── Cost model ──────────────────────────────────────────────────────────────

def _costs_sell(premium: float) -> float:
    """All-in costs for one SELL order (one leg of strangle, 1 lot = 15 shares)."""
    notional = premium * LOT_SIZE
    exchange = notional * EXCHANGE_PCT
    gst = (BROKERAGE_PER_ORDER + exchange) * GST_PCT
    stt = notional * STT_SELL_PCT
    return BROKERAGE_PER_ORDER + exchange + gst + stt


def _costs_buy(premium: float) -> float:
    """All-in costs for one BUY order (closing one leg)."""
    notional = premium * LOT_SIZE
    exchange = notional * EXCHANGE_PCT
    gst = (BROKERAGE_PER_ORDER + exchange) * GST_PCT
    stamp = notional * STAMP_DUTY_PCT
    return BROKERAGE_PER_ORDER + exchange + gst + stamp


# ── Strike selection ────────────────────────────────────────────────────────

def _find_target_delta_strike(
    spot: float,
    opt_type: str,       # "CE" or "PE"
    target_delta: float,
    dte: int,
    iv_annual: float,
    available_strikes: list[float],
) -> float | None:
    """
    Find the strike with BS delta closest to target_delta.
    For CE: delta in (0, 1). For PE: delta in (-1, 0); target_delta given as positive.
    """
    best_strike = None
    best_diff = float("inf")

    for K in available_strikes:
        delta = abs(calculate_greeks(spot, K, max(dte, 1), RFR, iv_annual, opt_type).delta)
        diff = abs(delta - target_delta)
        if diff < best_diff:
            best_diff = diff
            best_strike = K

    # Sanity: don't accept a strike with delta way off (> 2× target)
    if best_diff > target_delta:
        return None
    return best_strike


# ── Data loading ────────────────────────────────────────────────────────────

def _load_options_data(session, from_date: date, to_date: date) -> dict:
    """
    Load BankNifty options daily OHLCV from options_chain_cache.

    Returns:
        {
          expiry_date: {
            (strike, option_type): {bar_date: close_price}
          }
        }
    """
    from sqlalchemy import text

    sql = text("""
        SELECT expiry_date, strike, option_type,
               bar_time::date AS bar_date, close
        FROM options_chain_cache
        WHERE underlying = 'BANKNIFTY'
          AND bar_time::date BETWEEN :from_d AND :to_d
          AND close IS NOT NULL AND close > 0
        ORDER BY expiry_date, strike, option_type, bar_time
    """)
    rows = session.execute(sql, {"from_d": from_date.isoformat(), "to_d": to_date.isoformat()}).fetchall()

    data: dict = defaultdict(lambda: defaultdict(dict))
    for row in rows:
        exp = row.expiry_date
        key = (float(row.strike), row.option_type)
        bdate = row.bar_date
        data[exp][key][bdate] = float(row.close)

    logger.info("Loaded %d option price points for %d expiries", len(rows), len(data))
    return dict(data)


def _load_spot_from_db(session, from_date: date, to_date: date) -> dict[date, float]:
    """Load BankNifty spot close from ohlcv_cache."""
    from sqlalchemy import text

    sql = text("""
        SELECT bar_date, close
        FROM ohlcv_cache
        WHERE ticker ILIKE '%BANKNIFTY%'
          AND interval = '1d'
          AND bar_date BETWEEN :from_d AND :to_d
          AND close IS NOT NULL
        ORDER BY bar_date
    """)
    rows = session.execute(sql, {"from_d": from_date.isoformat(), "to_d": to_date.isoformat()}).fetchall()
    result = {row.bar_date: float(row.close) for row in rows}
    logger.info("Loaded %d BankNifty spot bars from ohlcv_cache", len(result))
    return result


def _load_spot_from_yfinance(from_date: date, to_date: date) -> dict[date, float]:
    """Fallback: load BankNifty spot from yfinance."""
    try:
        import yfinance as yf
        df = yf.download(
            "^NSEBANK", start=from_date.isoformat(), end=(to_date + timedelta(days=1)).isoformat(),
            interval="1d", auto_adjust=True, progress=False,
        )
        result: dict[date, float] = {}
        for ts, row in df.iterrows():
            d = ts.date() if hasattr(ts, "date") else ts
            result[d] = float(row["Close"])
        logger.info("Loaded %d BankNifty spot bars from yfinance", len(result))
        return result
    except Exception as e:
        logger.warning("yfinance BankNifty spot failed: %s", e)
        return {}


def _load_vix_data(from_date: date, to_date: date) -> dict[date, float]:
    """Load India VIX daily close from yfinance."""
    try:
        import yfinance as yf
        # Extend window 1 year back for percentile calculation
        extended_from = date(from_date.year - 1, from_date.month, from_date.day)
        df = yf.download(
            "^INDIAVIX", start=extended_from.isoformat(),
            end=(to_date + timedelta(days=1)).isoformat(),
            interval="1d", auto_adjust=True, progress=False,
        )
        result: dict[date, float] = {}
        for ts, row in df.iterrows():
            d = ts.date() if hasattr(ts, "date") else ts
            result[d] = float(row["Close"])
        logger.info("Loaded %d India VIX bars", len(result))
        return result
    except Exception as e:
        logger.warning("yfinance VIX failed: %s", e)
        return {}


# ── VIX percentile ──────────────────────────────────────────────────────────

def _build_vix_percentiles(vix_series: dict[date, float]) -> dict[date, float]:
    """Rolling 252-day VIX percentile for each date."""
    if not vix_series:
        return {}
    sorted_dates = sorted(vix_series.keys())
    pct_map: dict[date, float] = {}
    lookback = 252
    vals = [vix_series[d] for d in sorted_dates]

    for i, d in enumerate(sorted_dates):
        window = vals[max(0, i - lookback + 1): i + 1]
        current = vals[i]
        pct = sum(1 for v in window if v <= current) / len(window)
        pct_map[d] = pct

    return pct_map


# ── Monthly expiry selection ────────────────────────────────────────────────

def _select_monthly_expiries(all_expiry_dates: list[date]) -> list[date]:
    """
    From a list of expiry dates (which may include weekly + monthly), return
    only the LAST expiry of each calendar month — this is the monthly contract.
    """
    by_month: dict[tuple[int, int], date] = {}
    for exp in sorted(all_expiry_dates):
        key = (exp.year, exp.month)
        by_month[key] = exp  # last expiry in month wins
    return sorted(by_month.values())


# ── Single trade simulation ─────────────────────────────────────────────────

def simulate_trade(
    entry_date: date,
    expiry_date: date,
    expiry_chain: dict,          # {(strike, opt_type): {bar_date: close}}
    spot_series: dict[date, float],
    vix_series: dict[date, float],
    vix_pct_series: dict[date, float],
    use_vix_gate: bool = True,
    time_exit_dte: int = 0,      # 0 = exit on expiry day; >0 = exit when DTE <= this
) -> dict | None:
    """
    Simulate one strangle cycle.

    Returns trade record dict, or None if setup fails.
    Sets 'skipped': True if the VIX gate filters this trade.
    """
    # ── Entry date: find closest available date >= entry_date ──────────
    all_bar_dates = set()
    for bars in expiry_chain.values():
        all_bar_dates.update(bars.keys())

    # Entry must be before or on expiry, and exist in option data
    valid_entry_dates = sorted(d for d in all_bar_dates if entry_date <= d < expiry_date)
    if not valid_entry_dates:
        logger.debug("No valid entry dates for expiry %s", expiry_date)
        return None

    actual_entry = valid_entry_dates[0]

    # ── Spot price ─────────────────────────────────────────────────────
    spot = spot_series.get(actual_entry)
    if spot is None:
        # Try adjacent days
        for adj in (1, -1, 2, -2):
            spot = spot_series.get(actual_entry + timedelta(days=adj))
            if spot:
                break
    if spot is None:
        logger.debug("No spot for entry %s", actual_entry)
        return None

    # ── VIX gate ───────────────────────────────────────────────────────
    vix = vix_series.get(actual_entry)
    vix_pct = vix_pct_series.get(actual_entry)

    if use_vix_gate and vix_pct is not None:
        if vix_pct < VIX_LOW_PCT or vix_pct > VIX_HIGH_PCT:
            return {
                "entry_date": actual_entry,
                "expiry_date": expiry_date,
                "skipped": True,
                "skip_reason": f"VIX gate: {vix:.1f} ({vix_pct:.0%} pct)",
                "vix": vix,
                "vix_pct": vix_pct,
            }

    # ── Available strikes on entry date ───────────────────────────────
    available_ce = [k for (k, t) in expiry_chain if t == "CE" and actual_entry in expiry_chain[(k, t)]]
    available_pe = [k for (k, t) in expiry_chain if t == "PE" and actual_entry in expiry_chain[(k, t)]]

    if not available_ce or not available_pe:
        logger.debug("No strikes available on entry %s", actual_entry)
        return None

    # ── Select strikes via BS delta ────────────────────────────────────
    dte = (expiry_date - actual_entry).days
    iv_proxy = (vix / 100.0 * BANKNIFTY_VOL_MULT) if (vix and vix > 0) else 0.20

    ce_strike = _find_target_delta_strike(spot, "CE", TARGET_DELTA, dte, iv_proxy, available_ce)
    pe_strike = _find_target_delta_strike(spot, "PE", TARGET_DELTA, dte, iv_proxy, available_pe)

    if not ce_strike or not pe_strike:
        logger.debug("Strike selection failed for entry %s (spot=%s, DTE=%s)", actual_entry, spot, dte)
        return None

    # ── Entry premiums ─────────────────────────────────────────────────
    ce_mid = expiry_chain.get((ce_strike, "CE"), {}).get(actual_entry)
    pe_mid = expiry_chain.get((pe_strike, "PE"), {}).get(actual_entry)

    if not ce_mid or not pe_mid or ce_mid <= 0 or pe_mid <= 0:
        logger.debug("Zero/missing entry premium on %s (CE=%s, PE=%s)", actual_entry, ce_mid, pe_mid)
        return None

    ce_entry = _sell_price(ce_mid, ce_strike, spot)
    pe_entry = _sell_price(pe_mid, pe_strike, spot)
    initial_credit = (ce_entry + pe_entry) * LOT_SIZE

    # Minimum credit filter: reject if costs eat the trade
    MIN_CREDIT = 0.005 * SPAN_MARGIN  # ~₹750
    if initial_credit < MIN_CREDIT:
        return {
            "entry_date": actual_entry,
            "expiry_date": expiry_date,
            "skipped": True,
            "skip_reason": f"credit too low: ₹{initial_credit:.0f} < ₹{MIN_CREDIT:.0f}",
            "vix": round(vix, 2) if vix else None,
            "vix_pct": round(vix_pct, 3) if vix_pct else None,
        }

    entry_costs = _costs_sell(ce_entry) + _costs_sell(pe_entry)

    profit_target  = PROFIT_TARGET_PCT * initial_credit
    stop_threshold = -STOP_LOSS_MULT * initial_credit

    # ── Day-by-day simulation ──────────────────────────────────────────
    sim_dates = sorted(d for d in all_bar_dates if actual_entry < d <= expiry_date)

    for sim_date in sim_dates:
        ce_mid_now = expiry_chain.get((ce_strike, "CE"), {}).get(sim_date)
        pe_mid_now = expiry_chain.get((pe_strike, "PE"), {}).get(sim_date)

        if ce_mid_now is None or pe_mid_now is None:
            continue  # missing bar — check next day

        dte_now = (expiry_date - sim_date).days
        is_time_exit = (sim_date == expiry_date) if time_exit_dte == 0 else (dte_now <= time_exit_dte)

        # Gross P&L on the open position (sold at entry, current mark-to-market)
        gross_pnl = ((ce_entry - ce_mid_now) + (pe_entry - pe_mid_now)) * LOT_SIZE

        # Adjustment rules (simplified for daily bars — conservative: close both legs)
        # Rule 2: tested strike within 0.5% of spot → close all (tested leg imminent)
        spot_now = spot_series.get(sim_date, spot)
        ce_dist = abs(ce_strike - spot_now) / spot_now if spot_now else 1.0
        pe_dist = abs(pe_strike - spot_now) / spot_now if spot_now else 1.0
        strike_imminent = ce_dist < 0.005 or pe_dist < 0.005

        # Rule 3: delta of either leg > 0.30 → close all
        dte_now = max((expiry_date - sim_date).days, 1)
        vix_now = vix_series.get(sim_date, vix or 15.0)
        iv_now = (vix_now / 100.0 * BANKNIFTY_VOL_MULT) if vix_now > 0 else 0.20
        ce_delta_now = abs(calculate_greeks(spot_now, ce_strike, dte_now, RFR, iv_now, "CE").delta)
        pe_delta_now = abs(calculate_greeks(spot_now, pe_strike, dte_now, RFR, iv_now, "PE").delta)
        delta_breach = ce_delta_now > 0.30 or pe_delta_now > 0.30

        adjustment_exit = (strike_imminent or delta_breach) and not is_time_exit

        if gross_pnl >= profit_target or gross_pnl <= stop_threshold or is_time_exit or adjustment_exit:
            # Determine exit reason (priority order)
            if gross_pnl >= profit_target:
                exit_reason = "profit"
            elif gross_pnl <= stop_threshold:
                exit_reason = "stop"
            elif adjustment_exit:
                exit_reason = "adjustment"  # Rule 2 or Rule 3 triggered
            else:
                exit_reason = "time"    # time_exit_dte or expiry day

            spot_exit = spot_series.get(sim_date, spot)
            ce_exit = _buy_price(ce_mid_now, ce_strike, spot_exit)
            pe_exit = _buy_price(pe_mid_now, pe_strike, spot_exit)

            exit_pnl = ((ce_entry - ce_exit) + (pe_entry - pe_exit)) * LOT_SIZE
            exit_costs = _costs_buy(ce_exit) + _costs_buy(pe_exit)
            net_pnl = exit_pnl - entry_costs - exit_costs

            holding_days = (sim_date - actual_entry).days

            return {
                "entry_date": actual_entry,
                "exit_date": sim_date,
                "expiry_date": expiry_date,
                "ce_strike": ce_strike,
                "pe_strike": pe_strike,
                "spot_entry": spot,
                "initial_credit": round(initial_credit, 2),
                "ce_entry_prem": round(ce_entry, 2),
                "pe_entry_prem": round(pe_entry, 2),
                "ce_exit_prem": round(ce_exit, 2),
                "pe_exit_prem": round(pe_exit, 2),
                "gross_pnl": round(gross_pnl, 2),
                "net_pnl": round(net_pnl, 2),
                "entry_costs": round(entry_costs, 2),
                "exit_costs": round(exit_costs, 2),
                "holding_days": holding_days,
                "exit_reason": exit_reason,
                "vix": round(vix, 2) if vix else None,
                "vix_pct": round(vix_pct, 3) if vix_pct else None,
                "skipped": False,
            }

    # No exit found — shouldn't happen with time exit
    logger.warning("No exit triggered for expiry %s (expiry bar missing?)", expiry_date)
    return None


# ── Walk-forward ────────────────────────────────────────────────────────────

def _sharpe(pnl_list: list[float], span_days: float = 0.0) -> float:
    """
    Annualized Sharpe on trade P&L sequence.
    If span_days provided, annualize using actual trade frequency
    (n_trades * 365 / span_days). Otherwise defaults to 52 trades/year.
    """
    if len(pnl_list) < 2:
        return 0.0
    mean = statistics.mean(pnl_list)
    std = statistics.stdev(pnl_list)
    if std == 0:
        return 0.0
    if span_days > 0 and len(pnl_list) > 0:
        trades_per_year = len(pnl_list) * 365.0 / span_days
        return mean / std * math.sqrt(trades_per_year)
    return mean / std * math.sqrt(52)


def _add_months(d: date, m: int) -> date:
    month = d.month + m
    year = d.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    return d.replace(year=year, month=month, day=1)


def walk_forward(
    trades: list[dict],
    train_months: int = WF_TRAIN_MONTHS,
    test_months: int = WF_TEST_MONTHS,
) -> dict:
    live_trades = [t for t in trades if not t.get("skipped")]
    if not live_trades:
        return {"error": "no live trades"}

    dates = sorted(t["entry_date"] for t in live_trades)
    start_date = dates[0]
    end_date   = dates[-1]

    windows = []
    months_elapsed = 0

    while True:
        test_start = _add_months(start_date, train_months + months_elapsed)
        test_end   = _add_months(start_date, train_months + months_elapsed + test_months)

        if test_end > end_date + timedelta(days=31):
            break

        window_trades = [
            t for t in live_trades
            if test_start <= t["entry_date"] < test_end
        ]

        if window_trades:
            total_pnl = sum(t["net_pnl"] for t in window_trades)
            pnl_list  = [t["net_pnl"] for t in window_trades]
            win_count = sum(1 for p in pnl_list if p > 0)
            ann_return_on_margin = (total_pnl / SPAN_MARGIN) * (12.0 / test_months)

            # Per-window max drawdown on margin
            eq = 0.0
            pk = 0.0
            win_max_dd = 0.0
            for p in pnl_list:
                eq += p
                if eq > pk:
                    pk = eq
                dd = (pk - eq) / SPAN_MARGIN if pk > 0 else 0.0
                if dd > win_max_dd:
                    win_max_dd = dd

            span = (test_end - test_start).days
            windows.append({
                "test_start": test_start.isoformat(),
                "test_end":   test_end.isoformat(),
                "n_trades":   len(window_trades),
                "total_pnl":  round(total_pnl, 2),
                "ann_return_on_margin": round(ann_return_on_margin, 4),
                "sharpe": round(_sharpe(pnl_list, float(span)), 3),
                "win_rate": round(win_count / len(window_trades), 3),
                "max_dd_pct": round(win_max_dd * 100, 2),
                "profitable": total_pnl > 0,
            })

        months_elapsed += test_months
        if months_elapsed > 60:  # safety cap
            break

    if not windows:
        return {"error": "no test windows with trades"}

    profitable_windows = [w for w in windows if w["profitable"]]
    consistency = len(profitable_windows) / len(windows)
    avg_ann_return = statistics.mean(w["ann_return_on_margin"] for w in windows)

    # Correct WF Sharpe: single Sharpe on the full chronological out-of-sample
    # trade sequence. DO NOT average per-window Sharpes — small all-win windows
    # have near-zero std, making per-window Sharpe → ∞ and the average meaningless.
    first_test_start = _add_months(start_date, train_months)
    wf_test_trades = sorted(
        [t for t in live_trades if t["entry_date"] >= first_test_start],
        key=lambda t: t["entry_date"],
    )
    wf_pnl_list = [t["net_pnl"] for t in wf_test_trades]
    if len(wf_pnl_list) >= 2:
        wf_span = max((wf_test_trades[-1]["entry_date"] - wf_test_trades[0]["entry_date"]).days, 1)
        wf_overall_sharpe = _sharpe(wf_pnl_list, float(wf_span))
    else:
        wf_overall_sharpe = 0.0

    return {
        "n_windows": len(windows),
        "profitable_windows": len(profitable_windows),
        "consistency": round(consistency, 3),
        "avg_ann_return_on_margin": round(avg_ann_return, 4),
        "avg_sharpe": round(wf_overall_sharpe, 3),   # chronological OOS Sharpe
        "windows": windows,
    }


# ── Monte Carlo ─────────────────────────────────────────────────────────────

def monte_carlo(trades: list[dict], n_iterations: int = 10_000) -> dict:
    pnl_values = [t["net_pnl"] for t in trades if not t.get("skipped")]
    if len(pnl_values) < 5:
        return {"error": "insufficient trades for Monte Carlo"}

    max_dds_pct = []
    for _ in range(n_iterations):
        perm = random.sample(pnl_values, len(pnl_values))
        equity = 0.0
        peak   = 0.0
        max_dd = 0.0
        for pnl in perm:
            equity += pnl
            if equity > peak:
                peak = equity
            dd_pct = (peak - equity) / SPAN_MARGIN if peak > 0 else 0.0
            if dd_pct > max_dd:
                max_dd = dd_pct
        max_dds_pct.append(max_dd)

    max_dds_pct.sort()
    n = len(max_dds_pct)
    return {
        "iterations": n_iterations,
        "p25": round(max_dds_pct[int(0.25 * n)], 4),
        "p50": round(max_dds_pct[int(0.50 * n)], 4),
        "p75": round(max_dds_pct[int(0.75 * n)], 4),
        "p95": round(max_dds_pct[int(0.95 * n)], 4),
        "p99": round(max_dds_pct[int(0.99 * n)], 4),
    }


# ── Bootstrap Sharpe CI ─────────────────────────────────────────────────────

def bootstrap_sharpe(trades: list[dict], n_boot: int = 5000) -> dict:
    pnl_values = [t["net_pnl"] for t in trades if not t.get("skipped")]
    if len(pnl_values) < 5:
        return {}

    boot_sharpes = []
    for _ in range(n_boot):
        sample = random.choices(pnl_values, k=len(pnl_values))
        boot_sharpes.append(_sharpe(sample))

    boot_sharpes.sort()
    n = len(boot_sharpes)
    return {
        "point_estimate": round(_sharpe(pnl_values), 3),
        "ci_95_low":  round(boot_sharpes[int(0.025 * n)], 3),
        "ci_95_high": round(boot_sharpes[int(0.975 * n)], 3),
    }


# ── Regime breakdown ────────────────────────────────────────────────────────

def _ema(prices: list[float], period: int) -> list[float | None]:
    """Simple EMA calculation."""
    if not prices:
        return []
    k = 2.0 / (period + 1)
    result: list[float | None] = [None] * len(prices)
    # Find first valid entry
    start = period - 1
    if start >= len(prices):
        return result
    result[start] = statistics.mean(prices[:period])
    for i in range(start + 1, len(prices)):
        result[i] = prices[i] * k + result[i - 1] * (1.0 - k)  # type: ignore[operator]
    return result


def regime_breakdown(
    trades: list[dict],
    spot_series: dict[date, float],
    vix_series: dict[date, float],
    vix_pct_series: dict[date, float],
) -> dict:
    live_trades = [t for t in trades if not t.get("skipped")]

    # ── 200-day EMA for trend classification ───────────────────────────
    sorted_dates = sorted(spot_series.keys())
    spot_vals    = [spot_series[d] for d in sorted_dates]
    ema_vals     = _ema(spot_vals, 200)
    ema_map: dict[date, float | None] = dict(zip(sorted_dates, ema_vals))

    def _regime_label(t: dict) -> tuple[str, str]:
        ed = t["entry_date"]
        vp = t.get("vix_pct")
        sp = spot_series.get(ed, 0)
        em = ema_map.get(ed)

        # VIX bucket
        if vp is None:
            vix_bucket = "unknown"
        elif vp < 0.40:
            vix_bucket = "low_vix"
        elif vp < 0.65:
            vix_bucket = "mid_vix"
        else:
            vix_bucket = "high_vix"

        # Trend bucket
        if em is None or sp == 0:
            trend_bucket = "unknown"
        elif sp > em * 1.01:
            trend_bucket = "trending_up"
        elif sp < em * 0.99:
            trend_bucket = "trending_down"
        else:
            trend_bucket = "ranging"

        return vix_bucket, trend_bucket

    buckets: dict[str, list[float]] = defaultdict(list)
    for t in live_trades:
        vix_b, trend_b = _regime_label(t)
        buckets[f"vix:{vix_b}"].append(t["net_pnl"])
        buckets[f"trend:{trend_b}"].append(t["net_pnl"])
        buckets[f"{vix_b}+{trend_b}"].append(t["net_pnl"])

    result = {}
    for label, pnl_list in sorted(buckets.items()):
        if not pnl_list:
            continue
        win_rate = sum(1 for p in pnl_list if p > 0) / len(pnl_list)
        result[label] = {
            "n_trades":   len(pnl_list),
            "total_pnl":  round(sum(pnl_list), 2),
            "avg_pnl":    round(statistics.mean(pnl_list), 2),
            "win_rate":   round(win_rate, 3),
            "ann_return_on_margin": round(
                sum(pnl_list) / SPAN_MARGIN * (52 / len(pnl_list)) if pnl_list else 0, 4
            ),
        }

    return result


# ── Aggregate metrics ───────────────────────────────────────────────────────

def aggregate_metrics(trades: list[dict]) -> dict:
    live = [t for t in trades if not t.get("skipped")]
    if not live:
        return {"error": "no live trades"}

    pnl_list = [t["net_pnl"] for t in live]
    total_pnl = sum(pnl_list)
    win_count = sum(1 for p in pnl_list if p > 0)
    n = len(live)

    # Equity curve
    equity = 0.0
    peak   = 0.0
    max_dd_pct = 0.0
    for p in pnl_list:
        equity += p
        if equity > peak:
            peak = equity
        if peak > 0:
            dd = (peak - equity) / SPAN_MARGIN
            if dd > max_dd_pct:
                max_dd_pct = dd

    # Holding period stats
    holding_days = [t["holding_days"] for t in live]
    avg_hold = statistics.mean(holding_days) if holding_days else 0

    # Credit collected
    credits = [t["initial_credit"] for t in live]

    # Annualized return on margin (approx: total P&L / margin × 52/avg_weekly_trades)
    # Estimate: data span in years
    first_date = min(t["entry_date"] for t in live)
    last_date  = max(t["entry_date"] for t in live)
    span_days = max((last_date - first_date).days, 1)
    years = max(span_days / 365.0, 0.01)
    ann_return_on_margin = (total_pnl / SPAN_MARGIN) / years

    # Profit factor
    wins  = [p for p in pnl_list if p > 0]
    losses = [p for p in pnl_list if p <= 0]
    pf = (sum(wins) / abs(sum(losses))) if losses else float("inf")

    # Exit reasons
    exit_counts: dict[str, int] = defaultdict(int)
    for t in live:
        exit_counts[t.get("exit_reason", "unknown")] += 1

    return {
        "n_trades": n,
        "n_skipped": sum(1 for t in trades if t.get("skipped")),
        "total_pnl": round(total_pnl, 2),
        "win_rate": round(win_count / n, 3),
        "profit_factor": round(pf, 3),
        "avg_pnl_per_trade": round(statistics.mean(pnl_list), 2),
        "median_pnl": round(statistics.median(pnl_list), 2),
        "std_pnl": round(statistics.stdev(pnl_list) if n > 1 else 0, 2),
        "sharpe_annualized": round(_sharpe(pnl_list, span_days), 3),
        "max_drawdown_on_margin_pct": round(max_dd_pct * 100, 2),
        "ann_return_on_margin_pct": round(ann_return_on_margin * 100, 2),
        "avg_holding_days": round(avg_hold, 1),
        "avg_initial_credit": round(statistics.mean(credits), 2),
        "exit_reasons": dict(exit_counts),
        "data_span": f"{first_date} → {last_date}",
    }


# ── Override conditions check ───────────────────────────────────────────────

def check_override_conditions(
    agg: dict,
    mc: dict,
    wf: dict,
    expiry_type: str = "weekly",
) -> list[str]:
    """
    Check override conditions from pre-committed criteria docs.
    Returns list of triggered overrides (empty = no override).
    """
    thr = TIER_THRESHOLDS.get(expiry_type, TIER_THRESHOLDS["weekly"])
    overrides = []

    if mc and "p95" in mc:
        if mc["p95"] * 100 > 60:
            overrides.append(f"MC P95 max drawdown {mc['p95']*100:.1f}% > 60% → no deploy")

    if wf and "consistency" in wf:
        if wf["consistency"] < 0.40:
            overrides.append(f"WF consistency {wf['consistency']:.0%} < 40% → no deploy")

    if agg and "n_trades" in agg:
        min_t = thr["min_trades"]
        if agg["n_trades"] < min_t:
            overrides.append(f"Trade count {agg['n_trades']} < {min_t} → insufficient statistical mass")

    if wf and "windows" in wf:
        for w in wf["windows"]:
            if w.get("max_dd_pct", 0) > 50:
                overrides.append(
                    f"WF window {w['test_start']}–{w['test_end']}: "
                    f"max DD {w['max_dd_pct']:.1f}% > 50% → regime sensitivity"
                )

    return overrides


# ── Tier verdict ────────────────────────────────────────────────────────────

def determine_tier(agg: dict, wf: dict, mc: dict, overrides: list[str], expiry_type: str = "weekly") -> str:
    if overrides:
        return "OVERRIDE (check triggers)"

    thr = TIER_THRESHOLDS.get(expiry_type, TIER_THRESHOLDS["weekly"])
    wf_return   = wf.get("avg_ann_return_on_margin", 0) * 100
    wf_sharpe   = wf.get("avg_sharpe", 0)
    mc_p95_dd   = mc.get("p95", 1.0) * 100
    consistency = wf.get("consistency", 0)
    win_rate    = agg.get("win_rate", 0)

    # Tier 1
    if (wf_return > thr["t1_return"] and wf_sharpe > thr["t1_sharpe"] and
            mc_p95_dd < thr["t1_dd"] and consistency >= thr["t1_consistency"] and
            win_rate >= thr["t1_wr"]):
        return "TIER_1: Strong validation → plan deployment"

    # Tier 2
    if (thr["t2_return_lo"] <= wf_return <= thr["t2_return_hi"] and
            thr["t2_sharpe_lo"] <= wf_sharpe <= thr["t2_sharpe_hi"] and
            mc_p95_dd < thr["t2_dd"] and consistency >= thr["t2_consistency"]):
        return "TIER_2: Marginal → one iteration permitted"

    # Tier 3
    if thr["t3_return_lo"] <= wf_return <= thr["t3_return_hi"] and 0 <= wf_sharpe <= thr["t3_sharpe_hi"]:
        return "TIER_3: Edge exists but too thin → move on"

    # Tier 4
    if wf_return < 5 or wf_sharpe < 0:
        return "TIER_4: Hypothesis disproven → no iteration"

    return "TIER_UNKNOWN: metrics outside all tiers"


# ── Markdown report ─────────────────────────────────────────────────────────

def _md_table(headers: list[str], rows: list[list]) -> str:
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))

    def fmt_row(cells):
        return "| " + " | ".join(str(c).ljust(col_widths[i]) for i, c in enumerate(cells)) + " |"

    separator = "| " + " | ".join("-" * w for w in col_widths) + " |"
    lines = [fmt_row(headers), separator] + [fmt_row(r) for r in rows]
    return "\n".join(lines)


def write_markdown_report(
    results: dict,
    output_path: Path,
) -> None:
    agg = results["aggregate"]
    wf  = results["walk_forward"]
    mc  = results["monte_carlo"]
    shp = results.get("bootstrap_sharpe", {})
    reg = results.get("regime_breakdown", {})
    tier = results["tier"]
    overrides = results["override_conditions"]

    lines = [
        "# BankNifty Short Strangle Validation Report",
        f"\n**Run date:** {date.today()}",
        f"**Data span:** {agg.get('data_span', 'unknown')}",
        f"**Criteria doc:** docs/strategy_validation/banknifty_strangle_criteria.md",
        "",
        "---",
        "",
        "## Methodology note",
        "",
        "Data source: NSE F&O bhavcopy (daily OHLCV, not intraday 15-min bars).",
        "Adjustment rules (Rules 2 and 3 from adjustment_engine.py) are implemented as",
        "**full-position close** when triggered (conservative vs. the live strategy",
        "which would close/roll only the threatened leg). A Tier 3 or 4 result here",
        "may improve with leg-level adjustments — test the live-management variant",
        "before final disposition.",
        "",
        "---",
        "",
        f"## Verdict: {tier}",
        "",
    ]

    if overrides:
        lines += ["### Override conditions triggered", ""]
        for o in overrides:
            lines.append(f"- {o}")
        lines.append("")

    # Aggregate metrics
    lines += [
        "## Aggregate performance (full dataset)",
        "",
        _md_table(
            ["Metric", "Value"],
            [
                ["Total trades", agg.get("n_trades", "—")],
                ["Skipped (VIX gate)", agg.get("n_skipped", "—")],
                ["Win rate", f"{agg.get('win_rate', 0):.1%}"],
                ["Profit factor", f"{agg.get('profit_factor', 0):.3f}"],
                ["Net P&L (₹)", f"₹{agg.get('total_pnl', 0):,.0f}"],
                ["Avg P&L per trade (₹)", f"₹{agg.get('avg_pnl_per_trade', 0):,.0f}"],
                ["Sharpe (annualized)", f"{agg.get('sharpe_annualized', 0):.3f}"],
                ["Annual return on margin", f"{agg.get('ann_return_on_margin_pct', 0):.1f}%"],
                ["Max drawdown on margin", f"{agg.get('max_drawdown_on_margin_pct', 0):.1f}%"],
                ["Avg holding days", agg.get("avg_holding_days", "—")],
                ["Avg initial credit (₹)", f"₹{agg.get('avg_initial_credit', 0):,.0f}"],
            ],
        ),
        "",
    ]

    # Bootstrap Sharpe CI
    if shp:
        lines += [
            f"**Bootstrap Sharpe 95% CI:** [{shp.get('ci_95_low', '—')}, {shp.get('ci_95_high', '—')}]  ",
            f"(point estimate: {shp.get('point_estimate', '—')})",
            "",
        ]

    # Exit reason breakdown
    exits = agg.get("exit_reasons", {})
    if exits:
        lines += [
            "### Exit reasons",
            "",
            _md_table(
                ["Reason", "Count", "Pct"],
                [
                    [r, c, f"{c/agg['n_trades']:.1%}"]
                    for r, c in sorted(exits.items(), key=lambda x: -x[1])
                ],
            ),
            "",
        ]

    # Walk-forward
    if wf and "n_windows" in wf:
        lines += [
            "## Walk-forward analysis (12-month train / 3-month test)",
            "",
            _md_table(
                ["WF Metric", "Value", "Threshold"],
                [
                    ["Windows tested", wf.get("n_windows", "—"), "—"],
                    ["Profitable windows", wf.get("profitable_windows", "—"), f"≥{wf.get('n_windows',1)*0.5:.0f} (50%)"],
                    ["Consistency", f"{wf.get('consistency', 0):.0%}", "≥ 60% (Tier 1) / ≥ 50% (Tier 2)"],
                    ["Avg WF annual return on margin", f"{wf.get('avg_ann_return_on_margin', 0)*100:.1f}%", "> 25% (T1) / 15–25% (T2)"],
                    ["Avg WF Sharpe", f"{wf.get('avg_sharpe', 0):.3f}", "> 1.0 (T1) / 0.5–1.0 (T2)"],
                ],
            ),
            "",
            "### Per-window results",
            "",
        ]
        wf_rows = [
            [
                w["test_start"][:7],
                w["test_end"][:7],
                w["n_trades"],
                f"₹{w['total_pnl']:,.0f}",
                f"{w['ann_return_on_margin']*100:.1f}%",
                f"{w['sharpe']:.2f}",
                "✓" if w["profitable"] else "✗",
            ]
            for w in wf.get("windows", [])
        ]
        lines += [
            _md_table(
                ["Test start", "Test end", "N", "P&L", "Ann return", "Sharpe", "Profit?"],
                wf_rows,
            ),
            "",
        ]

    # Monte Carlo
    if mc and "p95" in mc:
        lines += [
            "## Monte Carlo max drawdown (10,000 permutations)",
            "",
            _md_table(
                ["Percentile", "Max DD on margin", "Threshold"],
                [
                    ["P50 (median)", f"{mc['p50']*100:.1f}%", "—"],
                    ["P75", f"{mc['p75']*100:.1f}%", "—"],
                    ["P95", f"{mc['p95']*100:.1f}%", "< 35% (T1) / < 50% (T2)"],
                    ["P99", f"{mc['p99']*100:.1f}%", "< 60% (override)"],
                ],
            ),
            "",
        ]

    # Regime breakdown
    if reg:
        lines += ["## Regime breakdown", ""]
        for label, stats in sorted(reg.items()):
            lines.append(
                f"**{label}** — {stats['n_trades']} trades, "
                f"win {stats['win_rate']:.0%}, avg ₹{stats['avg_pnl']:,.0f}, "
                f"ann {stats['ann_return_on_margin']*100:.1f}%"
            )
        lines.append("")

    # Pre-committed criteria reference
    lines += [
        "---",
        "",
        "## Pre-committed criteria (from banknifty_strangle_criteria.md)",
        "",
        _md_table(
            ["Tier", "WF return", "WF Sharpe", "P95 DD", "Consistency", "Win rate"],
            [
                ["Tier 1", "> 25%", "> 1.0", "< 35%", "≥ 60%", "≥ 60%"],
                ["Tier 2", "15–25%", "0.5–1.0", "< 50%", "≥ 50%", "—"],
                ["Tier 3", "5–15%", "0–0.5", "—", "—", "—"],
                ["Tier 4", "< 5%", "< 0", "—", "—", "—"],
            ],
        ),
        "",
        "_These criteria were committed on 2026-04-29 before any validation results were seen._",
    ]

    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Markdown report written: %s", output_path)


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="BankNifty strangle validation")
    parser.add_argument("--from", dest="from_date", default="2023-01-01",
                        help="Start date (YYYY-MM-DD)")
    parser.add_argument("--to", dest="to_date", default=None,
                        help="End date (YYYY-MM-DD), default today")
    parser.add_argument("--mc-runs", type=int, default=10_000,
                        help="Monte Carlo iterations")
    parser.add_argument("--no-vix-gate", action="store_true",
                        help="Disable VIX percentile gate (benchmark run)")
    parser.add_argument("--output-dir", default="reports",
                        help="Directory for output files")
    parser.add_argument("--debug-vix", action="store_true",
                        help="Print per-expiry VIX gate decision and stop (diagnostic only)")
    parser.add_argument("--expiry-type", choices=["weekly", "monthly"], default="weekly",
                        help="weekly: Monday entry, expiry-day exit; "
                             "monthly: 25-DTE entry, 5-DTE time exit")
    args = parser.parse_args()

    from_date    = date.fromisoformat(args.from_date)
    to_date      = date.fromisoformat(args.to_date) if args.to_date else date.today()
    use_vix_gate = not args.no_vix_gate
    debug_vix    = args.debug_vix
    expiry_type  = args.expiry_type
    time_exit_dte = MONTHLY_TIME_EXIT_DTE if expiry_type == "monthly" else 0

    logger.info("=== BankNifty Short Strangle Validation ===")
    logger.info("Period: %s → %s | Type: %s | VIX gate: %s | MC runs: %d",
                from_date, to_date, expiry_type.upper(), use_vix_gate, args.mc_runs)

    # ── Load data ──────────────────────────────────────────────────────
    from mcp_server.db import SessionLocal
    session = SessionLocal()

    try:
        options_data = _load_options_data(session, from_date, to_date)

        spot_series = _load_spot_from_db(session, from_date, to_date)
        if len(spot_series) < 10:
            logger.info("Insufficient DB spot data, falling back to yfinance...")
            spot_series = _load_spot_from_yfinance(from_date, to_date)
    finally:
        session.close()

    vix_series = _load_vix_data(from_date, to_date)
    vix_pct_series = _build_vix_percentiles(vix_series)

    if not spot_series:
        logger.error("No BankNifty spot data available. Cannot proceed.")
        sys.exit(1)

    # ── VIX gate diagnostic (--debug-vix) ─────────────────────────────
    if debug_vix:
        print(f"\n{'Expiry':<12} {'Entry':<12} {'VIX':>6} {'Pct':>6} {'Gate':>6}  Decision")
        print("-" * 65)
        expiry_dates_all = sorted(options_data.keys())
        for exp in expiry_dates_all:
            dow = exp.weekday()
            entry_monday = exp - timedelta(days=dow)
            # Find actual entry date
            all_dates: set = set()
            for bars in options_data[exp].values():
                all_dates.update(bars.keys())
            valid = sorted(d for d in all_dates if entry_monday <= d < exp)
            actual_entry = valid[0] if valid else entry_monday
            vix = vix_series.get(actual_entry)
            pct = vix_pct_series.get(actual_entry)
            if vix is None:
                decision = "SKIP (no VIX data)"
            elif pct is None:
                decision = "SKIP (no pct data)"
            elif pct < VIX_LOW_PCT:
                decision = f"REJECT (pct {pct:.2f} < {VIX_LOW_PCT} — low IV)"
            elif pct > VIX_HIGH_PCT:
                decision = f"REJECT (pct {pct:.2f} > {VIX_HIGH_PCT} — spike)"
            else:
                decision = f"ACCEPT (pct {pct:.2f})"
            pct_str = f"{pct:.2f}" if pct is not None else "—"
            vix_str = f"{vix:.1f}" if vix is not None else "—"
            print(f"{exp!s:<12} {actual_entry!s:<12} {vix_str:>6} {pct_str:>6}  {decision}")
        print(f"\nVIX range in data: [{min(vix_series.values()):.1f}, {max(vix_series.values()):.1f}]")
        vix_vals = sorted(vix_series.values())
        p30 = vix_vals[int(0.30 * len(vix_vals))]
        p80 = vix_vals[int(0.80 * len(vix_vals))]
        print(f"30th pct = {p30:.1f}, 80th pct = {p80:.1f} (global — rolling may differ)")
        sys.exit(0)

    # ── Expiry selection and simulation ────────────────────────────────
    all_expiry_dates = sorted(options_data.keys())

    if expiry_type == "monthly":
        # Monthly: last expiry of each calendar month
        expiry_dates = _select_monthly_expiries(all_expiry_dates)
        logger.info("Monthly mode: %d total → %d monthly expiries",
                    len(all_expiry_dates), len(expiry_dates))
    else:
        # Weekly: deduplicate same-expiry-week entries
        seen_entry_mondays: set[date] = set()
        expiry_dates = []
        for exp in all_expiry_dates:
            dow = exp.weekday()
            monday = exp - timedelta(days=dow)
            if monday not in seen_entry_mondays:
                seen_entry_mondays.add(monday)
                expiry_dates.append(exp)
        if len(expiry_dates) < len(all_expiry_dates):
            logger.info("Deduplicated same-week expiries: %d → %d unique expiry weeks",
                        len(all_expiry_dates), len(expiry_dates))

    logger.info("Found %d expiry dates to simulate", len(expiry_dates))

    trades: list[dict] = []
    for expiry_date in expiry_dates:
        expiry_chain = options_data[expiry_date]

        if expiry_type == "monthly":
            entry_target = expiry_date - timedelta(days=MONTHLY_ENTRY_DAYS_BEFORE)
        else:
            dow = expiry_date.weekday()
            entry_target = expiry_date - timedelta(days=dow)  # Monday of expiry week

        result = simulate_trade(
            entry_date=entry_target,
            expiry_date=expiry_date,
            expiry_chain=expiry_chain,
            spot_series=spot_series,
            vix_series=vix_series,
            vix_pct_series=vix_pct_series,
            use_vix_gate=use_vix_gate,
            time_exit_dte=time_exit_dte,
        )
        if result:
            trades.append(result)

    live_count   = sum(1 for t in trades if not t.get("skipped"))
    skip_count   = sum(1 for t in trades if t.get("skipped"))
    logger.info("Simulated %d expiries → %d live trades, %d skipped",
                len(expiry_dates), live_count, skip_count)

    if live_count < 10:
        logger.error("Only %d live trades — insufficient for analysis", live_count)
        sys.exit(1)

    # ── Compute metrics ────────────────────────────────────────────────
    logger.info("Computing aggregate metrics...")
    agg = aggregate_metrics(trades)

    logger.info("Running walk-forward analysis...")
    wf = walk_forward(trades, WF_TRAIN_MONTHS, WF_TEST_MONTHS)

    logger.info("Running Monte Carlo (%d iterations)...", args.mc_runs)
    mc = monte_carlo(trades, args.mc_runs)

    logger.info("Running bootstrap Sharpe CI...")
    shp = bootstrap_sharpe(trades)

    logger.info("Computing regime breakdown...")
    reg = regime_breakdown(trades, spot_series, vix_series, vix_pct_series)

    overrides = check_override_conditions(agg, mc, wf, expiry_type)
    tier = determine_tier(agg, wf, mc, overrides, expiry_type)

    # ── Assemble results ───────────────────────────────────────────────
    results = {
        "metadata": {
            "run_date": date.today().isoformat(),
            "expiry_type": expiry_type,
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat(),
            "vix_gate_active": use_vix_gate,
            "mc_runs": args.mc_runs,
            "strategy": {
                "target_delta": TARGET_DELTA,
                "profit_target_pct": PROFIT_TARGET_PCT,
                "stop_loss_mult": STOP_LOSS_MULT,
                "lot_size": LOT_SIZE,
                "span_margin": SPAN_MARGIN,
            },
        },
        "tier": tier,
        "override_conditions": overrides,
        "aggregate": agg,
        "walk_forward": wf,
        "monte_carlo": mc,
        "bootstrap_sharpe": shp,
        "regime_breakdown": reg,
        "trades": [
            {k: (v.isoformat() if isinstance(v, date) else v) for k, v in t.items()}
            for t in trades
        ],
    }

    # ── Write output ───────────────────────────────────────────────────
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True)
    run_date_str = date.today().isoformat()

    json_path = output_dir / f"banknifty_{expiry_type}_strangle_validation_{run_date_str}.json"
    md_path   = output_dir / f"banknifty_{expiry_type}_strangle_validation_{run_date_str}.md"

    json_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    logger.info("JSON results written: %s", json_path)

    write_markdown_report(results, md_path)

    # ── Print summary ──────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"VERDICT: {tier}")
    print("=" * 60)
    print(f"Trades: {live_count} live, {skip_count} VIX-gated")
    print(f"Win rate:          {agg.get('win_rate', 0):.1%}")
    print(f"Annual return:     {agg.get('ann_return_on_margin_pct', 0):.1f}% on margin")
    print(f"Max drawdown:      {agg.get('max_drawdown_on_margin_pct', 0):.1f}% on margin")
    print(f"Sharpe:            {agg.get('sharpe_annualized', 0):.3f}")
    print(f"WF return:         {wf.get('avg_ann_return_on_margin', 0)*100:.1f}%")
    print(f"WF Sharpe:         {wf.get('avg_sharpe', 0):.3f}")
    print(f"WF consistency:    {wf.get('consistency', 0):.0%} ({wf.get('profitable_windows', 0)}/{wf.get('n_windows', 0)} windows)")
    print(f"MC P95 max DD:     {mc.get('p95', 0)*100:.1f}%")
    if overrides:
        print(f"\nOVERRIDES: {len(overrides)} triggered")
        for o in overrides:
            print(f"  • {o}")
    print(f"\nFull report: {md_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
