"""
Nifty 50 Monthly Short Strangle Validation

Reads daily option OHLCV from options_chain_cache (NSE bhavcopy backfill)
and evaluates the pre-committed strategy specification from:
  docs/strategy_validation/nifty_monthly_strangle_criteria.md

Strategy spec (pre-committed — do not change):
  - Underlying: Nifty 50 monthly expiry
  - Structure: short strangle (naked)
  - Target delta: 0.15 per leg at entry
  - Entry: ~25 DTE before monthly expiry (first trading day on or after expiry - 25 cal days)
  - Monthly expiry selection:
      Pre-Sept 1 2025: last Thursday of each calendar month (weekday=3)
      Post-Sept 1 2025: last Tuesday of each calendar month (weekday=1)
  - Exit — stop:       2× initial combined credit (most urgent — checked first)
  - Exit — profit:     50% of initial combined credit
  - Exit — adjustment: delta breach (|delta| > 0.30) or strike within 0.5% of spot
  - Exit — early_time: 5 DTE if current profit ≥ 25% of initial credit (gamma management)
  - Exit — time:       expiry-day close (last resort)
  - VIX gate: skip if VIX percentile < 30th or > 80th (rolling 252-day)
  - Margin basis: ₹1,50,000 per strangle
  - Lot size: 75 (current NSE Nifty 50 mandate)

Walk-forward: 12-month train / 3-month test
Monte Carlo:  10,000 permutations of trade sequence
Smoke test:   --smoke-test runs one Thursday-expiry (pre-Sept 2025) and one Tuesday-expiry
              (post-Sept 2025) monthly with verbose logging, then exits.

Usage:
    python scripts/validate_nifty_monthly_strangle.py
    python scripts/validate_nifty_monthly_strangle.py --from 2023-01-01 --mc-runs 5000
    python scripts/validate_nifty_monthly_strangle.py --no-vix-gate
    python scripts/validate_nifty_monthly_strangle.py --smoke-test
    python scripts/validate_nifty_monthly_strangle.py --debug-expiries
"""

from __future__ import annotations

import argparse
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
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows cp1252 fix

from mcp_server.options_greeks import calculate_greeks  # shared BS implementation

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("nifty_monthly_val")


# ── Strategy constants (pre-committed — do not change) ─────────────────────

UNDERLYING        = "NIFTY"
TARGET_DELTA      = 0.15
ENTRY_DTE         = 25        # calendar days before expiry
PROFIT_TARGET_PCT = 0.50      # 50% of initial combined credit
STOP_LOSS_MULT    = 2.0       # 2× initial combined credit
EARLY_TIME_DTE    = 5         # gamma management: exit early if profit threshold met
EARLY_TIME_MIN_PCT = 0.25     # 25% of initial credit qualifies for early_time exit
LOT_SIZE          = 75        # Nifty 50 current lot size
SPAN_MARGIN       = 150_000.0 # ₹1.5L per strangle
RFR               = 0.065
NIFTY_VOL_MULT    = 1.0       # India VIX tracks Nifty IV directly

# VIX gate (carried over unchanged from BankNifty — empirically load-bearing)
VIX_LOW_PCT  = 0.30
VIX_HIGH_PCT = 0.80

# Walk-forward parameters
WF_TRAIN_MONTHS = 12
WF_TEST_MONTHS  = 3

# Monthly expiry day transition (NSE, effective Sept 1 2025)
# Pre: Thursday (weekday=3) — last Thursday of each month
# Post: Tuesday (weekday=1) — last Tuesday of each month
EXPIRY_TRANSITION_DATE = date(2025, 9, 1)

# Tier thresholds (from nifty_monthly_strangle_criteria.md, committed 2026-05-07)
TIER_THRESHOLDS = {
    "t1_return":       18,    # Monthly: 18% (lower frequency than weekly)
    "t1_sharpe":       0.9,
    "t1_dd":           30,
    "t1_consistency":  0.60,
    "t1_wr":           0.65,
    "t2_return_lo":    10,
    "t2_return_hi":    18,
    "t2_sharpe_lo":    0.5,
    "t2_sharpe_hi":    0.9,
    "t2_dd":           40,
    "t2_consistency":  0.50,
    "t3_return_lo":    5,
    "t3_return_hi":    10,
    "t3_sharpe_hi":    0.5,
    "min_trades":      30,    # Monthly: 30 (not 50 as in weekly)
}

# Cost model (identical to weekly)
BROKERAGE_PER_ORDER = 20.0
STT_SELL_PCT        = 0.000125
EXCHANGE_PCT        = 0.0005
GST_PCT             = 0.18
STAMP_DUTY_PCT      = 0.00003
SLIPPAGE_ATM_PCT    = 0.005
SLIPPAGE_OTM_PCT    = 0.010
SLIPPAGE_FAR_PCT    = 0.020


# ── Slippage and cost helpers ───────────────────────────────────────────────

def _spread_pct(strike: float, spot: float) -> float:
    moneyness = abs(strike - spot) / spot
    if moneyness < 0.01:
        return SLIPPAGE_ATM_PCT
    elif moneyness < 0.03:
        return SLIPPAGE_OTM_PCT
    return SLIPPAGE_FAR_PCT


def _sell_price(mid: float, strike: float, spot: float) -> float:
    return mid * (1.0 - _spread_pct(strike, spot) / 2.0)


def _buy_price(mid: float, strike: float, spot: float) -> float:
    return mid * (1.0 + _spread_pct(strike, spot) / 2.0)


def _costs_sell(premium: float) -> float:
    notional = premium * LOT_SIZE
    exchange = notional * EXCHANGE_PCT
    gst = (BROKERAGE_PER_ORDER + exchange) * GST_PCT
    stt = notional * STT_SELL_PCT
    return BROKERAGE_PER_ORDER + exchange + gst + stt


def _costs_buy(premium: float) -> float:
    notional = premium * LOT_SIZE
    exchange = notional * EXCHANGE_PCT
    gst = (BROKERAGE_PER_ORDER + exchange) * GST_PCT
    stamp = notional * STAMP_DUTY_PCT
    return BROKERAGE_PER_ORDER + exchange + gst + stamp


# ── Strike selection ────────────────────────────────────────────────────────

def _find_target_delta_strike(
    spot: float,
    opt_type: str,
    target_delta: float,
    dte: int,
    iv_annual: float,
    available_strikes: list[float],
) -> float | None:
    best_strike = None
    best_diff = float("inf")
    for K in available_strikes:
        delta = abs(calculate_greeks(spot, K, max(dte, 1), RFR, iv_annual, opt_type).delta)
        diff = abs(delta - target_delta)
        if diff < best_diff:
            best_diff = diff
            best_strike = K
    if best_diff > target_delta:
        return None
    return best_strike


# ── Data loading ────────────────────────────────────────────────────────────

def _load_options_data(session, from_date: date, to_date: date) -> dict:
    from sqlalchemy import text
    sql = text("""
        SELECT expiry_date, strike, option_type,
               bar_time::date AS bar_date, close
        FROM options_chain_cache
        WHERE underlying = :underlying
          AND bar_time::date BETWEEN :from_d AND :to_d
          AND close IS NOT NULL AND close > 0
        ORDER BY expiry_date, strike, option_type, bar_time
    """)
    rows = session.execute(sql, {
        "underlying": UNDERLYING,
        "from_d": from_date.isoformat(),
        "to_d": to_date.isoformat(),
    }).fetchall()
    data: dict = defaultdict(lambda: defaultdict(dict))
    for row in rows:
        exp   = row.expiry_date
        key   = (float(row.strike), row.option_type)
        bdate = row.bar_date
        data[exp][key][bdate] = float(row.close)
    logger.info("Loaded %d option price points for %d expiries", len(rows), len(data))
    return dict(data)


def _load_spot_from_db(session, from_date: date, to_date: date) -> dict[date, float]:
    from sqlalchemy import text
    sql = text("""
        SELECT bar_date, close
        FROM ohlcv_cache
        WHERE ticker ILIKE '%NIFTY%'
          AND ticker NOT ILIKE '%BANK%'
          AND interval = '1d'
          AND bar_date BETWEEN :from_d AND :to_d
          AND close IS NOT NULL
        ORDER BY bar_date
    """)
    rows = session.execute(sql, {"from_d": from_date.isoformat(), "to_d": to_date.isoformat()}).fetchall()
    result = {row.bar_date: float(row.close) for row in rows}
    logger.info("Loaded %d Nifty spot bars from ohlcv_cache", len(result))
    return result


def _load_spot_from_yfinance(from_date: date, to_date: date) -> dict[date, float]:
    try:
        import yfinance as yf
        df = yf.download(
            "^NSEI", start=from_date.isoformat(),
            end=(to_date + timedelta(days=1)).isoformat(),
            interval="1d", auto_adjust=True, progress=False,
        )
        result: dict[date, float] = {}
        for ts, row in df.iterrows():
            d = ts.date() if hasattr(ts, "date") else ts
            close_val = row["Close"]
            result[d] = float(close_val.iloc[0]) if hasattr(close_val, "iloc") else float(close_val)
        logger.info("Loaded %d Nifty spot bars from yfinance (^NSEI)", len(result))
        return result
    except Exception as e:
        logger.warning("yfinance Nifty spot failed: %s", e)
        return {}


def _load_vix_data(from_date: date, to_date: date) -> dict[date, float]:
    try:
        import yfinance as yf
        extended_from = date(from_date.year - 1, from_date.month, from_date.day)
        df = yf.download(
            "^INDIAVIX", start=extended_from.isoformat(),
            end=(to_date + timedelta(days=1)).isoformat(),
            interval="1d", auto_adjust=True, progress=False,
        )
        result: dict[date, float] = {}
        for ts, row in df.iterrows():
            d = ts.date() if hasattr(ts, "date") else ts
            close_val = row["Close"]
            result[d] = float(close_val.iloc[0]) if hasattr(close_val, "iloc") else float(close_val)
        logger.info("Loaded %d India VIX bars", len(result))
        return result
    except Exception as e:
        logger.warning("yfinance VIX failed: %s", e)
        return {}


# ── VIX percentile ──────────────────────────────────────────────────────────

def _build_vix_percentiles(vix_series: dict[date, float]) -> dict[date, float]:
    if not vix_series:
        return {}
    sorted_dates = sorted(vix_series.keys())
    pct_map: dict[date, float] = {}
    vals = [vix_series[d] for d in sorted_dates]
    for i, d in enumerate(sorted_dates):
        window = vals[max(0, i - 252 + 1): i + 1]
        current = vals[i]
        pct_map[d] = sum(1 for v in window if v <= current) / len(window)
    return pct_map


# ── Monthly expiry selection ────────────────────────────────────────────────

def _select_monthly_expiries(all_expiry_dates: list[date], max_expiry: date | None = None) -> list[date]:
    """
    Return the last qualifying expiry of each calendar month up to max_expiry.
      Pre-Sept 1 2025: last Thursday (weekday=3) of each month
      Post-Sept 1 2025: last Tuesday (weekday=1) of each month

    The "last expiry per month" approach is insufficient because bhavcopy
    contains non-standard quarterly/annual contracts that produce Wednesdays
    or other days. This function filters by correct day-of-week first, then
    caps by max_expiry to exclude far-dated quarterly/annual contracts whose
    bars appear in the window but whose expiry is beyond the validation range.
    """
    by_month: dict[tuple[int, int], date] = {}
    for exp in sorted(all_expiry_dates):
        if max_expiry and exp > max_expiry:
            continue
        target_dow = 1 if exp >= EXPIRY_TRANSITION_DATE else 3  # Tuesday or Thursday
        if exp.weekday() == target_dow:
            key = (exp.year, exp.month)
            by_month[key] = exp  # last qualifying expiry in the month wins
    result = sorted(by_month.values())
    logger.info(
        "Selected %d monthly expiries (%d pre-transition, %d post-transition)",
        len(result),
        sum(1 for e in result if e < EXPIRY_TRANSITION_DATE),
        sum(1 for e in result if e >= EXPIRY_TRANSITION_DATE),
    )
    return result


def _entry_target_for_expiry(expiry_date: date) -> date:
    """
    Target entry = expiry_date minus 25 calendar days.
    The simulation loop advances to the first available trading day on or after
    this target. If actual entry deviates > 3 days from target, it is logged.
    """
    return expiry_date - timedelta(days=ENTRY_DTE)


# ── Single trade simulation ─────────────────────────────────────────────────

def simulate_trade(
    entry_date: date,
    expiry_date: date,
    expiry_chain: dict,
    spot_series: dict[date, float],
    vix_series: dict[date, float],
    vix_pct_series: dict[date, float],
    use_vix_gate: bool = True,
    verbose: bool = False,
) -> dict | None:
    all_bar_dates: set[date] = set()
    for bars in expiry_chain.values():
        all_bar_dates.update(bars.keys())

    valid_entry_dates = sorted(d for d in all_bar_dates if entry_date <= d < expiry_date)
    if not valid_entry_dates:
        logger.debug("No valid entry dates for expiry %s (target entry %s)", expiry_date, entry_date)
        return None

    actual_entry = valid_entry_dates[0]
    entry_deviation = (actual_entry - entry_date).days
    if entry_deviation > 3:
        logger.warning(
            "Entry deviation for expiry %s: target=%s actual=%s drift=%d days",
            expiry_date, entry_date, actual_entry, entry_deviation,
        )

    if verbose:
        logger.info(
            "[SMOKE] expiry=%s(%s) | target_entry=%s (-%dDTE) | actual_entry=%s | drift=%dd",
            expiry_date,
            ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][expiry_date.weekday()],
            entry_date, ENTRY_DTE, actual_entry, entry_deviation,
        )

    spot = spot_series.get(actual_entry)
    if spot is None:
        for adj in (1, -1, 2, -2):
            spot = spot_series.get(actual_entry + timedelta(days=adj))
            if spot:
                break
    if spot is None:
        logger.debug("No spot for entry %s", actual_entry)
        return None

    vix = vix_series.get(actual_entry)
    vix_pct = vix_pct_series.get(actual_entry)

    if use_vix_gate and vix_pct is not None:
        if vix_pct < VIX_LOW_PCT or vix_pct > VIX_HIGH_PCT:
            return {
                "entry_date":  actual_entry,
                "expiry_date": expiry_date,
                "skipped":     True,
                "skip_reason": f"VIX gate: {vix:.1f} ({vix_pct:.0%} pct)",
                "vix":         vix,
                "vix_pct":     vix_pct,
            }

    available_ce = [k for (k, t) in expiry_chain if t == "CE" and actual_entry in expiry_chain[(k, t)]]
    available_pe = [k for (k, t) in expiry_chain if t == "PE" and actual_entry in expiry_chain[(k, t)]]
    if not available_ce or not available_pe:
        logger.debug("No strikes on entry %s", actual_entry)
        return None

    dte = (expiry_date - actual_entry).days
    iv_proxy = (vix / 100.0 * NIFTY_VOL_MULT) if (vix and vix > 0) else 0.14

    ce_strike = _find_target_delta_strike(spot, "CE", TARGET_DELTA, dte, iv_proxy, available_ce)
    pe_strike = _find_target_delta_strike(spot, "PE", TARGET_DELTA, dte, iv_proxy, available_pe)
    if not ce_strike or not pe_strike:
        logger.debug("Strike selection failed entry=%s spot=%s DTE=%s", actual_entry, spot, dte)
        return None

    ce_mid = expiry_chain.get((ce_strike, "CE"), {}).get(actual_entry)
    pe_mid = expiry_chain.get((pe_strike, "PE"), {}).get(actual_entry)
    if not ce_mid or not pe_mid or ce_mid <= 0 or pe_mid <= 0:
        logger.debug("Zero/missing entry premium on %s", actual_entry)
        return None

    ce_entry      = _sell_price(ce_mid, ce_strike, spot)
    pe_entry      = _sell_price(pe_mid, pe_strike, spot)
    initial_credit = (ce_entry + pe_entry) * LOT_SIZE
    early_time_threshold = EARLY_TIME_MIN_PCT * initial_credit

    MIN_CREDIT = 0.005 * SPAN_MARGIN
    if initial_credit < MIN_CREDIT:
        return {
            "entry_date":  actual_entry,
            "expiry_date": expiry_date,
            "skipped":     True,
            "skip_reason": f"credit too low: ₹{initial_credit:.0f} < ₹{MIN_CREDIT:.0f}",
            "vix":         round(vix, 2) if vix else None,
            "vix_pct":     round(vix_pct, 3) if vix_pct else None,
        }

    entry_costs    = _costs_sell(ce_entry) + _costs_sell(pe_entry)
    profit_target  = PROFIT_TARGET_PCT * initial_credit
    stop_threshold = -STOP_LOSS_MULT * initial_credit

    if verbose:
        logger.info(
            "[SMOKE] entry=%s spot=%.0f CE_K=%.0f(prem=%.2f) PE_K=%.0f(prem=%.2f) "
            "credit=₹%.0f DTE=%d VIX=%.1f(%.0f%%)",
            actual_entry, spot,
            ce_strike, ce_entry, pe_strike, pe_entry,
            initial_credit, dte, vix or 0, (vix_pct or 0) * 100,
        )
        logger.info(
            "[SMOKE] targets: profit=₹%.0f(50%%) stop=-₹%.0f(2×) "
            "early_time=₹%.0f(25%%)@≤%dDTE",
            profit_target, abs(stop_threshold), early_time_threshold, EARLY_TIME_DTE,
        )
        entry_bkdwn = _costs_sell(ce_entry) + _costs_sell(pe_entry)
        logger.info("[SMOKE] entry_costs=₹%.2f (brokerage=₹%.0f×2, STT+exch+GST)",
                    entry_bkdwn, BROKERAGE_PER_ORDER)

    sim_dates = sorted(d for d in all_bar_dates if actual_entry < d <= expiry_date)

    for sim_date in sim_dates:
        ce_mid_now = expiry_chain.get((ce_strike, "CE"), {}).get(sim_date)
        pe_mid_now = expiry_chain.get((pe_strike, "PE"), {}).get(sim_date)
        if ce_mid_now is None or pe_mid_now is None:
            continue

        dte_now = (expiry_date - sim_date).days
        is_time_exit = sim_date == expiry_date

        gross_pnl = ((ce_entry - ce_mid_now) + (pe_entry - pe_mid_now)) * LOT_SIZE

        spot_now = spot_series.get(sim_date, spot)
        ce_dist = abs(ce_strike - spot_now) / spot_now if spot_now else 1.0
        pe_dist = abs(pe_strike - spot_now) / spot_now if spot_now else 1.0
        strike_imminent = ce_dist < 0.005 or pe_dist < 0.005

        vix_now  = vix_series.get(sim_date, vix or 15.0)
        iv_now   = (vix_now / 100.0 * NIFTY_VOL_MULT) if vix_now > 0 else 0.14
        ce_delta_now = abs(calculate_greeks(spot_now, ce_strike, max(dte_now, 1), RFR, iv_now, "CE").delta)
        pe_delta_now = abs(calculate_greeks(spot_now, pe_strike, max(dte_now, 1), RFR, iv_now, "PE").delta)
        delta_breach = ce_delta_now > 0.30 or pe_delta_now > 0.30

        # Exit priority: stop → profit → adjustment → early_time → time
        # Stop is checked before profit to catch cases where both trigger same day.
        if gross_pnl <= stop_threshold:
            exit_reason = "stop"
        elif gross_pnl >= profit_target:
            exit_reason = "profit"
        elif (strike_imminent or delta_breach) and not is_time_exit:
            exit_reason = "adjustment"
        elif dte_now <= EARLY_TIME_DTE and gross_pnl >= early_time_threshold and not is_time_exit:
            exit_reason = "early_time"
        elif is_time_exit:
            exit_reason = "time"
        else:
            continue

        spot_exit = spot_series.get(sim_date, spot)
        ce_exit   = _buy_price(ce_mid_now, ce_strike, spot_exit)
        pe_exit   = _buy_price(pe_mid_now, pe_strike, spot_exit)
        exit_pnl  = ((ce_entry - ce_exit) + (pe_entry - pe_exit)) * LOT_SIZE
        exit_costs = _costs_buy(ce_exit) + _costs_buy(pe_exit)
        net_pnl   = exit_pnl - entry_costs - exit_costs

        if verbose:
            logger.info(
                "[SMOKE] exit=%s reason=%s dte_now=%d | "
                "CE:%.2f→%.2f PE:%.2f→%.2f | "
                "gross=₹%.0f net=₹%.0f costs=₹%.0f",
                sim_date, exit_reason, dte_now,
                ce_entry, ce_exit, pe_entry, pe_exit,
                gross_pnl, net_pnl, entry_costs + exit_costs,
            )

        return {
            "entry_date":       actual_entry,
            "exit_date":        sim_date,
            "expiry_date":      expiry_date,
            "ce_strike":        ce_strike,
            "pe_strike":        pe_strike,
            "spot_entry":       spot,
            "initial_credit":   round(initial_credit, 2),
            "ce_entry_prem":    round(ce_entry, 2),
            "pe_entry_prem":    round(pe_entry, 2),
            "ce_exit_prem":     round(ce_exit, 2),
            "pe_exit_prem":     round(pe_exit, 2),
            "gross_pnl":        round(gross_pnl, 2),
            "net_pnl":          round(net_pnl, 2),
            "entry_costs":      round(entry_costs, 2),
            "exit_costs":       round(exit_costs, 2),
            "holding_days":     (sim_date - actual_entry).days,
            "exit_reason":      exit_reason,
            "dte_at_entry":     dte,
            "vix":              round(vix, 2) if vix else None,
            "vix_pct":          round(vix_pct, 3) if vix_pct else None,
            "skipped":          False,
        }

    logger.warning("No exit triggered for expiry %s (expiry bar missing?)", expiry_date)
    return None


# ── Walk-forward ────────────────────────────────────────────────────────────

def _sharpe(pnl_list: list[float], span_days: float = 0.0) -> float:
    if len(pnl_list) < 2:
        return 0.0
    mean = statistics.mean(pnl_list)
    std = statistics.stdev(pnl_list)
    if std == 0:
        return 0.0
    if span_days > 0 and len(pnl_list) > 0:
        trades_per_year = len(pnl_list) * 365.0 / span_days
        return mean / std * math.sqrt(trades_per_year)
    # Monthly: ~12 trades/year
    return mean / std * math.sqrt(12)


def _add_months(d: date, m: int) -> date:
    month = d.month + m
    year = d.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    return d.replace(year=year, month=month, day=1)


def walk_forward(trades: list[dict]) -> dict:
    live = [t for t in trades if not t.get("skipped")]
    if not live:
        return {"error": "no live trades"}

    dates = sorted(t["entry_date"] for t in live)
    start_date = dates[0]
    end_date   = dates[-1]

    windows = []
    months_elapsed = 0

    while True:
        test_start = _add_months(start_date, WF_TRAIN_MONTHS + months_elapsed)
        test_end   = _add_months(start_date, WF_TRAIN_MONTHS + months_elapsed + WF_TEST_MONTHS)
        if test_end > end_date + timedelta(days=31):
            break

        window_trades = [t for t in live if test_start <= t["entry_date"] < test_end]
        if window_trades:
            pnl_list  = [t["net_pnl"] for t in window_trades]
            total_pnl = sum(pnl_list)
            win_count = sum(1 for p in pnl_list if p > 0)
            ann_return = (total_pnl / SPAN_MARGIN) * (12.0 / WF_TEST_MONTHS)

            eq = pk = win_max_dd = 0.0
            for p in pnl_list:
                eq += p
                if eq > pk:
                    pk = eq
                dd = (pk - eq) / SPAN_MARGIN if pk > 0 else 0.0
                if dd > win_max_dd:
                    win_max_dd = dd

            span = (test_end - test_start).days
            windows.append({
                "test_start":           test_start.isoformat(),
                "test_end":             test_end.isoformat(),
                "n_trades":             len(window_trades),
                "total_pnl":            round(total_pnl, 2),
                "ann_return_on_margin": round(ann_return, 4),
                "sharpe":               round(_sharpe(pnl_list, float(span)), 3),
                "win_rate":             round(win_count / len(window_trades), 3),
                "max_dd_pct":           round(win_max_dd * 100, 2),
                "profitable":           total_pnl > 0,
            })

        months_elapsed += WF_TEST_MONTHS
        if months_elapsed > 60:
            break

    if not windows:
        return {"error": "no test windows with trades"}

    profitable_windows = [w for w in windows if w["profitable"]]
    consistency = len(profitable_windows) / len(windows)
    avg_ann_return = statistics.mean(w["ann_return_on_margin"] for w in windows)

    # Single Sharpe on full chronological OOS sequence — NOT average of per-window Sharpes
    first_test_start = _add_months(start_date, WF_TRAIN_MONTHS)
    wf_test_trades = sorted(
        [t for t in live if t["entry_date"] >= first_test_start],
        key=lambda t: t["entry_date"],
    )
    wf_pnl_list = [t["net_pnl"] for t in wf_test_trades]
    if len(wf_pnl_list) >= 2:
        wf_span = max((wf_test_trades[-1]["entry_date"] - wf_test_trades[0]["entry_date"]).days, 1)
        wf_overall_sharpe = _sharpe(wf_pnl_list, float(wf_span))
    else:
        wf_overall_sharpe = 0.0

    return {
        "n_windows":                 len(windows),
        "profitable_windows":        len(profitable_windows),
        "consistency":               round(consistency, 3),
        "avg_ann_return_on_margin":  round(avg_ann_return, 4),
        "avg_sharpe":                round(wf_overall_sharpe, 3),
        "windows":                   windows,
    }


# ── Monte Carlo ─────────────────────────────────────────────────────────────

def monte_carlo(trades: list[dict], n_iterations: int = 10_000) -> dict:
    pnl_values = [t["net_pnl"] for t in trades if not t.get("skipped")]
    if len(pnl_values) < 5:
        return {"error": "insufficient trades for Monte Carlo"}

    max_dds_pct = []
    for _ in range(n_iterations):
        perm  = random.sample(pnl_values, len(pnl_values))
        eq = pk = 0.0
        max_dd = 0.0
        for pnl in perm:
            eq += pnl
            if eq > pk:
                pk = eq
            dd_pct = (pk - eq) / SPAN_MARGIN if pk > 0 else 0.0
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
    boot_sharpes = sorted(_sharpe(random.choices(pnl_values, k=len(pnl_values))) for _ in range(n_boot))
    n = len(boot_sharpes)
    return {
        "point_estimate": round(_sharpe(pnl_values), 3),
        "ci_95_low":      round(boot_sharpes[int(0.025 * n)], 3),
        "ci_95_high":     round(boot_sharpes[int(0.975 * n)], 3),
    }


# ── Regime breakdown ────────────────────────────────────────────────────────

def _ema(prices: list[float], period: int) -> list[float | None]:
    if not prices or period > len(prices):
        return [None] * len(prices)
    k = 2.0 / (period + 1)
    result: list[float | None] = [None] * len(prices)
    result[period - 1] = statistics.mean(prices[:period])
    for i in range(period, len(prices)):
        result[i] = prices[i] * k + result[i - 1] * (1.0 - k)  # type: ignore[operator]
    return result


def regime_breakdown(
    trades: list[dict],
    spot_series: dict[date, float],
    vix_series: dict[date, float],
    vix_pct_series: dict[date, float],
) -> dict:
    live = [t for t in trades if not t.get("skipped")]
    sorted_dates = sorted(spot_series.keys())
    ema_vals = _ema([spot_series[d] for d in sorted_dates], 200)
    ema_map: dict[date, float | None] = dict(zip(sorted_dates, ema_vals))

    def _label(t: dict) -> tuple[str, str]:
        ed = t["entry_date"]
        vp = t.get("vix_pct")
        sp = spot_series.get(ed, 0)
        em = ema_map.get(ed)
        vix_bucket = ("low_vix" if vp is not None and vp < 0.40 else
                       "mid_vix" if vp is not None and vp < 0.65 else
                       "high_vix" if vp is not None else "unknown")
        trend_bucket = ("trending_up"   if em and sp > em * 1.01 else
                        "trending_down" if em and sp < em * 0.99 else
                        "ranging" if em else "unknown")
        return vix_bucket, trend_bucket

    buckets: dict[str, list[float]] = defaultdict(list)
    for t in live:
        vb, tb = _label(t)
        buckets[f"vix:{vb}"].append(t["net_pnl"])
        buckets[f"trend:{tb}"].append(t["net_pnl"])
        buckets[f"{vb}+{tb}"].append(t["net_pnl"])

    result = {}
    for label, pnl_list in sorted(buckets.items()):
        if not pnl_list:
            continue
        result[label] = {
            "n_trades":             len(pnl_list),
            "total_pnl":            round(sum(pnl_list), 2),
            "avg_pnl":              round(statistics.mean(pnl_list), 2),
            "win_rate":             round(sum(1 for p in pnl_list if p > 0) / len(pnl_list), 3),
            "ann_return_on_margin": round(
                sum(pnl_list) / SPAN_MARGIN * (12 / max(len(pnl_list), 1)), 4),
        }
    return result


# ── Aggregate metrics ───────────────────────────────────────────────────────

def aggregate_metrics(trades: list[dict]) -> dict:
    live = [t for t in trades if not t.get("skipped")]
    if not live:
        return {"error": "no live trades"}

    pnl_list  = [t["net_pnl"] for t in live]
    total_pnl = sum(pnl_list)
    win_count = sum(1 for p in pnl_list if p > 0)
    n = len(live)

    eq = pk = max_dd_pct = 0.0
    for p in pnl_list:
        eq += p
        if eq > pk:
            pk = eq
        if pk > 0:
            dd = (pk - eq) / SPAN_MARGIN
            if dd > max_dd_pct:
                max_dd_pct = dd

    first_date = min(t["entry_date"] for t in live)
    last_date  = max(t["entry_date"] for t in live)
    span_days  = max((last_date - first_date).days, 1)
    years      = max(span_days / 365.0, 0.01)

    wins   = [p for p in pnl_list if p > 0]
    losses = [p for p in pnl_list if p <= 0]
    pf = (sum(wins) / abs(sum(losses))) if losses else float("inf")

    exit_counts: dict[str, int] = defaultdict(int)
    for t in live:
        exit_counts[t.get("exit_reason", "unknown")] += 1

    avg_dte = statistics.mean(t.get("dte_at_entry", ENTRY_DTE) for t in live)

    return {
        "n_trades":                   n,
        "n_skipped":                  sum(1 for t in trades if t.get("skipped")),
        "total_pnl":                  round(total_pnl, 2),
        "win_rate":                   round(win_count / n, 3),
        "profit_factor":              round(pf, 3),
        "avg_pnl_per_trade":          round(statistics.mean(pnl_list), 2),
        "median_pnl":                 round(statistics.median(pnl_list), 2),
        "std_pnl":                    round(statistics.stdev(pnl_list) if n > 1 else 0, 2),
        "sharpe_annualized":          round(_sharpe(pnl_list, span_days), 3),
        "max_drawdown_on_margin_pct": round(max_dd_pct * 100, 2),
        "ann_return_on_margin_pct":   round((total_pnl / SPAN_MARGIN) / years * 100, 2),
        "avg_holding_days":           round(statistics.mean(t["holding_days"] for t in live), 1),
        "avg_dte_at_entry":           round(avg_dte, 1),
        "avg_initial_credit":         round(statistics.mean(t["initial_credit"] for t in live), 2),
        "exit_reasons":               dict(exit_counts),
        "data_span":                  f"{first_date} → {last_date}",
    }


# ── Override conditions and tier verdict ────────────────────────────────────

def check_override_conditions(agg: dict, mc: dict, wf: dict) -> list[str]:
    overrides = []
    if mc and "p95" in mc and mc["p95"] * 100 > 50:
        overrides.append(f"MC P95 max DD {mc['p95']*100:.1f}% > 50% → tail risk unacceptable")
    if wf and "consistency" in wf and wf["consistency"] < 0.40:
        overrides.append(f"WF consistency {wf['consistency']:.0%} < 40% → too regime-dependent")
    if agg and "n_trades" in agg and agg["n_trades"] < TIER_THRESHOLDS["min_trades"]:
        overrides.append(
            f"Trade count {agg['n_trades']} < {TIER_THRESHOLDS['min_trades']} → "
            "insufficient statistical mass (OVERRIDE — inconclusive, not failed)"
        )
    if wf and "windows" in wf:
        for w in wf["windows"]:
            if w.get("max_dd_pct", 0) > 50:
                overrides.append(
                    f"WF window {w['test_start'][:7]}–{w['test_end'][:7]}: "
                    f"max DD {w['max_dd_pct']:.1f}% > 50%"
                )
    return overrides


def determine_tier(agg: dict, wf: dict, mc: dict, overrides: list[str]) -> str:
    # OVERRIDE: trade count < 30 = inconclusive, NOT hypothesis disproven
    if overrides:
        is_sample_only = all("insufficient statistical mass" in o for o in overrides)
        if is_sample_only:
            return (
                f"OVERRIDE: Insufficient sample ({agg.get('n_trades',0)} trades < "
                f"{TIER_THRESHOLDS['min_trades']}) — inconclusive, not failed. "
                "Consider extending validation window to 2021-01-01."
            )
        return "OVERRIDE: Risk/quality condition triggered — do not deploy"

    t = TIER_THRESHOLDS
    wf_return   = wf.get("avg_ann_return_on_margin", 0) * 100
    wf_sharpe   = wf.get("avg_sharpe", 0)
    mc_p95_dd   = mc.get("p95", 1.0) * 100
    consistency = wf.get("consistency", 0)
    win_rate    = agg.get("win_rate", 0)

    if (wf_return > t["t1_return"] and wf_sharpe > t["t1_sharpe"] and
            mc_p95_dd < t["t1_dd"] and consistency >= t["t1_consistency"] and
            win_rate >= t["t1_wr"]):
        return "TIER_1: Strong validation → paper trade 30 days, 1 lot"

    if (t["t2_return_lo"] <= wf_return <= t["t2_return_hi"] and
            t["t2_sharpe_lo"] <= wf_sharpe <= t["t2_sharpe_hi"] and
            mc_p95_dd < t["t2_dd"] and consistency >= t["t2_consistency"]):
        return "TIER_2: Marginal → one iteration on exit parameters only (state structural reason first)"

    if (t["t3_return_lo"] <= wf_return <= t["t3_return_hi"] and
            0 <= wf_sharpe <= t["t3_sharpe_hi"]):
        return (
            "TIER_3: Edge too thin → two marginal results (weekly T2 + monthly T3) establishes "
            "Nifty short strangles are not commercially viable at these parameters. Move to Path C."
        )

    if wf_return < 5 or wf_sharpe < 0:
        return (
            "TIER_4: Hypothesis disproven for monthly Nifty strangles. "
            "Two results (weekly T2 + monthly T4) → options-selling on Nifty exhausted. Move on."
        )

    return "TIER_UNKNOWN: metrics outside all defined tiers — review manually"


# ── Markdown report ─────────────────────────────────────────────────────────

def _md_table(headers: list[str], rows: list[list]) -> str:
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))

    def fmt_row(cells):
        return "| " + " | ".join(str(c).ljust(col_widths[i]) for i, c in enumerate(cells)) + " |"

    sep = "| " + " | ".join("-" * w for w in col_widths) + " |"
    return "\n".join([fmt_row(headers), sep] + [fmt_row(r) for r in rows])


def write_markdown_report(results: dict, output_path: Path) -> None:
    agg  = results["aggregate"]
    wf   = results["walk_forward"]
    mc   = results["monte_carlo"]
    shp  = results.get("bootstrap_sharpe", {})
    reg  = results.get("regime_breakdown", {})
    tier = results["tier"]
    overrides = results["override_conditions"]

    lines = [
        "# Nifty Monthly Short Strangle Validation Report",
        f"\n**Run date:** {date.today()}",
        f"**Data span:** {agg.get('data_span', 'unknown')}",
        "**Criteria doc:** docs/strategy_validation/nifty_monthly_strangle_criteria.md",
        "**Criteria committed:** 2026-05-07 (before any monthly data was observed)",
        "",
        "---",
        "",
        "## Methodology note",
        "",
        "Data source: NSE F&O bhavcopy (daily OHLCV, not intraday).",
        f"Entry: ~{ENTRY_DTE} DTE before monthly expiry (first trading day on or after expiry - {ENTRY_DTE} cal days).",
        "Monthly expiry: last Thursday of month pre-Sept 2025; last Tuesday post-Sept 2025.",
        "Exit priority (checked in order): stop → profit → adjustment → early_time → time.",
        f"Early-time exit: triggered at ≤{EARLY_TIME_DTE} DTE when current profit ≥ {EARLY_TIME_MIN_PCT:.0%} of initial credit.",
        "Adjustment: full position close when |delta| > 0.30 or spot within 0.5% of either strike.",
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

    lines += [
        "## Aggregate performance",
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
                ["Avg DTE at entry", agg.get("avg_dte_at_entry", "—")],
                ["Avg initial credit (₹)", f"₹{agg.get('avg_initial_credit', 0):,.0f}"],
            ],
        ),
        "",
    ]

    if shp:
        lines += [
            f"**Bootstrap Sharpe 95% CI:** [{shp.get('ci_95_low','—')}, {shp.get('ci_95_high','—')}]  ",
            f"(point estimate: {shp.get('point_estimate','—')})",
            "",
        ]

    exits = agg.get("exit_reasons", {})
    if exits:
        n = agg.get("n_trades", 1)
        lines += [
            "### Exit reasons", "",
            _md_table(
                ["Reason", "Count", "Pct"],
                [[r, c, f"{c/n:.1%}"] for r, c in sorted(exits.items(), key=lambda x: -x[1])],
            ),
            "",
        ]

    if wf and "n_windows" in wf:
        lines += [
            "## Walk-forward analysis (12-month train / 3-month test)", "",
            _md_table(
                ["WF Metric", "Value", "Threshold"],
                [
                    ["Windows tested", wf.get("n_windows", "—"), "—"],
                    ["Profitable windows", wf.get("profitable_windows", "—"),
                     f"≥{wf.get('n_windows',1)*0.5:.0f} (50%)"],
                    ["Consistency", f"{wf.get('consistency', 0):.0%}", "≥ 60% (T1) / ≥ 50% (T2)"],
                    ["Avg WF return on margin", f"{wf.get('avg_ann_return_on_margin', 0)*100:.1f}%",
                     "> 18% (T1) / 10–18% (T2)"],
                    ["WF Sharpe (chronological OOS)", f"{wf.get('avg_sharpe', 0):.3f}",
                     "> 0.9 (T1) / 0.5–0.9 (T2)"],
                ],
            ),
            "",
            "### Per-window results", "",
            _md_table(
                ["Test start", "Test end", "N", "P&L", "Ann return", "Sharpe", "Profit?"],
                [
                    [w["test_start"][:7], w["test_end"][:7], w["n_trades"],
                     f"₹{w['total_pnl']:,.0f}", f"{w['ann_return_on_margin']*100:.1f}%",
                     f"{w['sharpe']:.2f}", "✓" if w["profitable"] else "✗"]
                    for w in wf.get("windows", [])
                ],
            ),
            "",
        ]

    if mc and "p95" in mc:
        lines += [
            "## Monte Carlo max drawdown (10,000 permutations)", "",
            _md_table(
                ["Percentile", "Max DD on margin", "Threshold"],
                [
                    ["P50 (median)", f"{mc['p50']*100:.1f}%", "—"],
                    ["P75", f"{mc['p75']*100:.1f}%", "—"],
                    ["P95", f"{mc['p95']*100:.1f}%", "< 30% (T1) / < 40% (T2)"],
                    ["P99", f"{mc['p99']*100:.1f}%", "< 50% (override)"],
                ],
            ),
            "",
        ]

    if reg:
        lines += ["## Regime breakdown", ""]
        for label, stats in sorted(reg.items()):
            lines.append(
                f"**{label}** — {stats['n_trades']} trades, "
                f"win {stats['win_rate']:.0%}, avg ₹{stats['avg_pnl']:,.0f}, "
                f"ann {stats['ann_return_on_margin']*100:.1f}%"
            )
        lines.append("")

    lines += [
        "---", "",
        "## Pre-committed criteria (nifty_monthly_strangle_criteria.md — committed 2026-05-07)", "",
        _md_table(
            ["Tier", "WF return", "WF Sharpe", "P95 DD", "Consistency", "Win rate", "Min trades"],
            [
                ["Tier 1", "> 18%", "> 0.9", "< 30%", "≥ 60%", "≥ 65%", "≥ 30"],
                ["Tier 2", "10–18%", "0.5–0.9", "< 40%", "≥ 50%", "—", "≥ 30"],
                ["Tier 3", "5–10%", "0–0.5", "—", "—", "—", "≥ 30"],
                ["Tier 4", "< 5%", "< 0", "—", "—", "—", "≥ 30"],
                ["OVERRIDE", "—", "—", "—", "—", "—", "< 30 → inconclusive"],
            ],
        ),
        "",
        "_Criteria committed 2026-05-07 before any Nifty monthly validation was run._",
        "_Context: BankNifty weekly OVERRIDE, BankNifty monthly OVERRIDE (10 trades), "
        "Pairs inconclusive, Nifty weekly TIER 2. Six prior tests, all accepted without iteration._",
    ]

    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Markdown report written: %s", output_path)


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Nifty monthly short strangle validation")
    parser.add_argument("--from", dest="from_date", default="2023-01-01")
    parser.add_argument("--to",   dest="to_date",   default=None)
    parser.add_argument("--mc-runs", type=int, default=10_000)
    parser.add_argument("--no-vix-gate", action="store_true")
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--debug-expiries", action="store_true",
                        help="Print all selected monthly expiries with day-of-week, then exit")
    parser.add_argument("--smoke-test", action="store_true",
                        help="Run one Thursday-expiry (May 2024) and one Tuesday-expiry "
                             "(March 2026) monthly trade with verbose logging, then exit.")
    args = parser.parse_args()

    from_date    = date.fromisoformat(args.from_date)
    to_date      = date.fromisoformat(args.to_date) if args.to_date else date.today()
    use_vix_gate = not args.no_vix_gate

    logger.info("=== Nifty Monthly Short Strangle Validation ===")
    logger.info("Period: %s → %s | VIX gate: %s | MC runs: %d",
                from_date, to_date, use_vix_gate, args.mc_runs)
    logger.info("Entry: ~%d DTE | Profit: %.0f%% | Stop: %.0f× | Early-time: %d DTE@%.0f%%",
                ENTRY_DTE, PROFIT_TARGET_PCT * 100, STOP_LOSS_MULT,
                EARLY_TIME_DTE, EARLY_TIME_MIN_PCT * 100)

    from mcp_server.db import SessionLocal
    session = SessionLocal()

    try:
        options_data = _load_options_data(session, from_date, to_date)
        spot_series  = _load_spot_from_db(session, from_date, to_date)
        if len(spot_series) < 500:
            logger.info("Sparse DB spot (%d bars), falling back to yfinance (^NSEI)...", len(spot_series))
            spot_series = _load_spot_from_yfinance(from_date, to_date)
    finally:
        session.close()

    vix_series     = _load_vix_data(from_date, to_date)
    vix_pct_series = _build_vix_percentiles(vix_series)

    if not spot_series:
        logger.error("No Nifty spot data. Cannot proceed.")
        sys.exit(1)

    all_expiry_dates = sorted(options_data.keys())
    monthly_expiries = _select_monthly_expiries(all_expiry_dates, max_expiry=to_date)

    # ── Expiry diagnostic ──────────────────────────────────────────────
    if args.debug_expiries:
        dow_names = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
        print(f"\n{'Month':<10} {'Expiry':<12} {'DOW':<10} {'Transition'}")
        print("-" * 50)
        for exp in monthly_expiries:
            side = "post" if exp >= EXPIRY_TRANSITION_DATE else "pre"
            print(f"{exp.strftime('%Y-%m'):<10} {exp!s:<12} "
                  f"{dow_names[exp.weekday()]:<10} {side}")
        print(f"\nTotal: {len(monthly_expiries)} monthly expiries")
        print(f"Pre-transition  (Thursday): {sum(1 for e in monthly_expiries if e < EXPIRY_TRANSITION_DATE)}")
        print(f"Post-transition (Tuesday):  {sum(1 for e in monthly_expiries if e >= EXPIRY_TRANSITION_DATE)}")
        sys.exit(0)

    # ── Smoke test ─────────────────────────────────────────────────────
    if args.smoke_test:
        print("\n=== SMOKE TEST: Nifty Monthly Strangle ===")
        print(f"Expiry selection: last Thursday pre-{EXPIRY_TRANSITION_DATE}, "
              f"last Tuesday post-{EXPIRY_TRANSITION_DATE}")
        print(f"Entry: ~{ENTRY_DTE} DTE | Early-time: ≤{EARLY_TIME_DTE} DTE + ≥{EARLY_TIME_MIN_PCT:.0%} profit\n")

        # Pre-transition: target May 2024 monthly (last Thursday = 2024-05-30)
        # Post-transition: target March 2026 monthly (last Tuesday = likely 2026-03-31)
        thursday_monthlies = [e for e in monthly_expiries if e < EXPIRY_TRANSITION_DATE]
        tuesday_monthlies  = [e for e in monthly_expiries if e >= EXPIRY_TRANSITION_DATE]

        smoke_pairs = []

        if thursday_monthlies:
            target = date(2024, 5, 1)
            best = min(thursday_monthlies, key=lambda d: abs((d - target).days))
            smoke_pairs.append(("PRE-TRANSITION Thursday monthly", best))
        else:
            print("WARNING: No Thursday monthly expiries found in loaded data range")

        if tuesday_monthlies:
            target = date(2026, 3, 1)
            best = min(tuesday_monthlies, key=lambda d: abs((d - target).days))
            smoke_pairs.append(("POST-TRANSITION Tuesday monthly", best))
        else:
            print("WARNING: No Tuesday monthly expiries found "
                  "(extend --to beyond 2025-09-01 or data not yet available)")

        for label, exp in smoke_pairs:
            dow = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][exp.weekday()]
            entry_target = _entry_target_for_expiry(exp)
            print(f"--- {label}: {exp} ({dow}) ---")
            print(f"    Target entry: {entry_target} "
                  f"({['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][entry_target.weekday()]}), "
                  f"~{(exp - entry_target).days} cal days DTE")

            if exp not in options_data:
                print(f"    WARNING: expiry {exp} not found in options_chain_cache — "
                      "bhavcopy may not cover this month\n")
                continue

            result = simulate_trade(
                entry_date=entry_target,
                expiry_date=exp,
                expiry_chain=options_data[exp],
                spot_series=spot_series,
                vix_series=vix_series,
                vix_pct_series=vix_pct_series,
                use_vix_gate=False,  # force simulate regardless of VIX gate
                verbose=True,
            )
            if result is None:
                print("    RESULT: None (data missing — check options_chain_cache coverage)\n")
            elif result.get("skipped"):
                print(f"    RESULT: Skipped — {result.get('skip_reason')}\n")
            else:
                print(
                    f"    RESULT: net_pnl=₹{result['net_pnl']:,.0f} "
                    f"exit_date={result['exit_date']} reason={result['exit_reason']} "
                    f"holding={result['holding_days']}d\n"
                )

        print("Smoke test complete.")
        print("Both trades should show Thursday/Tuesday expiry with ~25 DTE entry.")
        print("If both show sensible logs and plausible P&L, proceed to full validation.")
        sys.exit(0)

    # ── Full validation ────────────────────────────────────────────────
    logger.info("Found %d monthly expiries to simulate", len(monthly_expiries))

    trades: list[dict] = []
    for expiry_date in monthly_expiries:
        result = simulate_trade(
            entry_date=_entry_target_for_expiry(expiry_date),
            expiry_date=expiry_date,
            expiry_chain=options_data[expiry_date],
            spot_series=spot_series,
            vix_series=vix_series,
            vix_pct_series=vix_pct_series,
            use_vix_gate=use_vix_gate,
        )
        if result:
            trades.append(result)

    live_count = sum(1 for t in trades if not t.get("skipped"))
    skip_count = sum(1 for t in trades if t.get("skipped"))
    logger.info("Simulated %d monthly expiries → %d live trades, %d skipped",
                len(monthly_expiries), live_count, skip_count)

    if live_count < 5:
        logger.error(
            "Only %d live trades — insufficient for analysis. "
            "Check options_chain_cache for NIFTY monthly expiry data. "
            "If trade count < %d, result is OVERRIDE (inconclusive, not failed).",
            live_count, TIER_THRESHOLDS["min_trades"],
        )
        sys.exit(1)

    logger.info("Computing aggregate metrics...")
    agg = aggregate_metrics(trades)

    logger.info("Running walk-forward analysis...")
    wf = walk_forward(trades)

    logger.info("Running Monte Carlo (%d iterations)...", args.mc_runs)
    mc = monte_carlo(trades, args.mc_runs)

    logger.info("Running bootstrap Sharpe CI...")
    shp = bootstrap_sharpe(trades)

    logger.info("Computing regime breakdown...")
    reg = regime_breakdown(trades, spot_series, vix_series, vix_pct_series)

    overrides = check_override_conditions(agg, mc, wf)
    tier = determine_tier(agg, wf, mc, overrides)

    results = {
        "metadata": {
            "run_date":        date.today().isoformat(),
            "underlying":      UNDERLYING,
            "expiry_type":     "monthly",
            "from_date":       from_date.isoformat(),
            "to_date":         to_date.isoformat(),
            "vix_gate_active": use_vix_gate,
            "mc_runs":         args.mc_runs,
            "expiry_transition": EXPIRY_TRANSITION_DATE.isoformat(),
            "strategy": {
                "target_delta":         TARGET_DELTA,
                "entry_dte":            ENTRY_DTE,
                "profit_target_pct":    PROFIT_TARGET_PCT,
                "stop_loss_mult":       STOP_LOSS_MULT,
                "early_time_dte":       EARLY_TIME_DTE,
                "early_time_min_pct":   EARLY_TIME_MIN_PCT,
                "lot_size":             LOT_SIZE,
                "span_margin":          SPAN_MARGIN,
            },
        },
        "tier":                tier,
        "override_conditions": overrides,
        "aggregate":           agg,
        "walk_forward":        wf,
        "monte_carlo":         mc,
        "bootstrap_sharpe":    shp,
        "regime_breakdown":    reg,
        "trades": [
            {k: (v.isoformat() if isinstance(v, date) else v) for k, v in t.items()}
            for t in trades
        ],
    }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True)
    run_date_str = date.today().isoformat()
    json_path = output_dir / f"nifty_monthly_strangle_validation_{run_date_str}.json"
    md_path   = output_dir / f"nifty_monthly_strangle_validation_{run_date_str}.md"

    json_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    logger.info("JSON results: %s", json_path)
    write_markdown_report(results, md_path)

    print("\n" + "=" * 70)
    print(f"VERDICT: {tier}")
    print("=" * 70)
    print(f"Trades: {live_count} live, {skip_count} VIX-gated "
          f"({len(monthly_expiries)} total monthly expiries evaluated)")
    print(f"Win rate:        {agg.get('win_rate', 0):.1%}")
    print(f"Annual return:   {agg.get('ann_return_on_margin_pct', 0):.1f}% on margin")
    print(f"Max drawdown:    {agg.get('max_drawdown_on_margin_pct', 0):.1f}% on margin")
    print(f"Sharpe:          {agg.get('sharpe_annualized', 0):.3f}")
    print(f"WF return:       {wf.get('avg_ann_return_on_margin', 0)*100:.1f}%  "
          f"[T1: >18% | T2: 10–18%]")
    print(f"WF Sharpe:       {wf.get('avg_sharpe', 0):.3f}  "
          f"[T1: >0.9 | T2: 0.5–0.9]")
    print(f"WF consistency:  {wf.get('consistency', 0):.0%} "
          f"({wf.get('profitable_windows', 0)}/{wf.get('n_windows', 0)} windows)  "
          f"[T1: ≥60% | T2: ≥50%]")
    print(f"MC P95 max DD:   {mc.get('p95', 0)*100:.1f}%  "
          f"[T1: <30% | T2: <40%]")
    if shp:
        print(f"Sharpe 95% CI:   [{shp.get('ci_95_low','—')}, {shp.get('ci_95_high','—')}]")

    exit_reasons = agg.get("exit_reasons", {})
    if exit_reasons:
        print("\nExit breakdown:")
        for reason, count in sorted(exit_reasons.items(), key=lambda x: -x[1]):
            print(f"  {reason:<14} {count:>3}  ({count/live_count:.0%})")

    if overrides:
        print(f"\nOVERRIDES: {len(overrides)} triggered")
        for o in overrides:
            print(f"  • {o}")

    print(f"\nFull report: {md_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()
