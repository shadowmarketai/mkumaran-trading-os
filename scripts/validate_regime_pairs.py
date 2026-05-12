"""
Regime-Filtered Pairs Trading Validation

Tests RELIANCE/IOC and AXISBANK/COALINDIA with a two-gate regime filter:
  1. Rolling 60-day Engle-Granger cointegration must hold (p < 0.10) at entry
  2. Nifty 50 must NOT be in a strong directional trend at entry

Entry z-score relaxed to 1.5 (from 2.0 in prior runs) to compensate for
entries blocked by the regime filter.

Pre-committed decision criteria:
  docs/strategy_validation/regime_pairs_criteria.md

If this run OVERRIDEs: pairs trading chapter is permanently closed.

Usage:
    python scripts/validate_regime_pairs.py
    python scripts/validate_regime_pairs.py --from 2021-01-01
    python scripts/validate_regime_pairs.py --z-entry 1.5 --coint-p 0.10
    python scripts/validate_regime_pairs.py --nifty-threshold 0.15
"""
from __future__ import annotations

import argparse
import logging
import math
import os
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("regime_pairs")


# ── Strategy constants (must match criteria doc) ────────────────────────────

PAIRS = [
    ("RELIANCE", "IOC"),
    ("AXISBANK", "COALINDIA"),
]

Z_ENTRY = 1.5       # relaxed from 2.0
Z_EXIT  = 0.5
Z_STOP  = 4.0
COOLDOWN_DAYS = 30

WF_TRAIN_MONTHS = 12
WF_TEST_MONTHS  =  3

REGIME_COINT_DAYS   = 60     # rolling window for coint check
REGIME_COINT_P      = 0.10   # p-value threshold for recent coint
NIFTY_SLOPE_DAYS    = 60     # window for Nifty trend check
NIFTY_THRESHOLD     = 0.15   # |directional move / price| over window

POSITION_SIZE_PER_LEG = 50_000.0

BROKERAGE       = 20.0
STT_SELL_PCT    = 0.00025
EXCHANGE_PCT    = 0.0000345
GST_PCT         = 0.18
STAMP_DUTY_PCT  = 0.00015
BORROW_COST_DAY = 0.0004
SLIPPAGE        = 0.0005

# Tier thresholds (criteria doc)
TIER1_SHARPE     = 0.8
TIER1_MAX_DD     = 0.20
TIER1_MIN_TRADES = 15
TIER1_WIN_RATE   = 0.55

TIER2_SHARPE_LO  = 0.4
TIER2_SHARPE_HI  = 0.8
TIER2_MAX_DD     = 0.30
TIER2_MIN_TRADES = 10
TIER2_WIN_RATE   = 0.50


# ── Data loading ─────────────────────────────────────────────────────────────

def _load_prices(session, symbol: str, start: date, end: date) -> dict[date, float]:
    from sqlalchemy import text
    rows = session.execute(text("""
        SELECT bar_date, close FROM ohlcv_cache
        WHERE ticker = :sym AND interval = '1d'
          AND bar_date BETWEEN :s AND :e
          AND close IS NOT NULL AND close > 0
        ORDER BY bar_date
    """), {"sym": symbol, "s": start.isoformat(), "e": end.isoformat()}).fetchall()
    if rows:
        return {r.bar_date: float(r.close) for r in rows}

    # yfinance fallback
    try:
        import yfinance as yf
        df = yf.download(
            symbol + ".NS",
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=True,
            progress=False,
        )
        if not df.empty:
            closes = df["Close"]
            if hasattr(getattr(closes, "columns", None), "__iter__"):
                closes = closes.iloc[:, 0]
            return {d.date(): float(c) for d, c in closes.items()}
    except Exception as e:
        logger.warning("yfinance %s: %s", symbol, e)
    return {}


def _load_nifty(start: date, end: date) -> dict[date, float]:
    try:
        import yfinance as yf
        df = yf.download(
            "^NSEI",
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=True,
            progress=False,
        )
        if not df.empty:
            closes = df["Close"]
            if hasattr(getattr(closes, "columns", None), "__iter__"):
                closes = closes.iloc[:, 0]
            return {d.date(): float(c) for d, c in closes.items()}
    except Exception as e:
        logger.warning("Nifty fetch failed: %s", e)
    return {}


def _aligned(prices_a: dict, prices_b: dict) -> tuple[list[date], list[float], list[float]]:
    common = sorted(set(prices_a) & set(prices_b))
    return common, [prices_a[d] for d in common], [prices_b[d] for d in common]


# ── Statistics ───────────────────────────────────────────────────────────────

def _eg_coint_p(y: list[float], x: list[float]) -> float:
    try:
        import numpy as np
        from statsmodels.tsa.stattools import coint
        _, p, _ = coint(np.array(y), np.array(x))
        return float(p)
    except Exception:
        return 1.0


def _ols_beta(y: list[float], x: list[float]) -> float:
    try:
        import numpy as np
        X = np.column_stack([np.ones(len(x)), np.array(x)])
        beta = np.linalg.lstsq(X, np.array(y), rcond=None)[0]
        return float(beta[1])
    except Exception:
        return 1.0


def _linreg_slope(values: list[float]) -> float:
    """Linear regression slope over equally-spaced indices."""
    n = len(values)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2
    num = sum((i - x_mean) * v for i, v in enumerate(values))
    den = sum((i - x_mean) ** 2 for i in range(n))
    return num / den if den > 0 else 0.0


def _sharpe(pnl_list: list[float], span_days: float = 252) -> float:
    if len(pnl_list) < 2:
        return 0.0
    mean = statistics.mean(pnl_list)
    std  = statistics.stdev(pnl_list)
    if std == 0:
        return 0.0
    tpy = len(pnl_list) * 365.0 / span_days if span_days > 0 else 252
    return mean / std * math.sqrt(tpy)


def _max_drawdown(pnl_list: list[float]) -> float:
    equity = 0.0
    peak   = 0.0
    max_dd = 0.0
    for p in pnl_list:
        equity += p
        peak = max(peak, equity)
        dd = peak - equity
        max_dd = max(max_dd, dd)
    return max_dd


# ── Regime pre-computation ───────────────────────────────────────────────────

def _precompute_regime(
    dates: list[date],
    prices_a: list[float],
    prices_b: list[float],
    nifty: dict[date, float],
    coint_days: int,
    coint_p: float,
    nifty_days: int,
    nifty_threshold: float,
) -> dict[date, bool]:
    """
    Pre-compute regime pass/fail for every date in the series.

    Both conditions must pass for regime_ok=True:
      1. Rolling 60-day EG cointegration p < coint_p
      2. Nifty 60-day directional move ≤ nifty_threshold
    """
    nifty_dates = sorted(nifty.keys())
    regime: dict[date, bool] = {}

    for i, d in enumerate(dates):
        if i < coint_days:
            regime[d] = False  # insufficient lookback
            continue

        # Filter 1: rolling cointegration
        pa_win = prices_a[i - coint_days : i]
        pb_win = prices_b[i - coint_days : i]
        coint_ok = _eg_coint_p(pa_win, pb_win) < coint_p

        # Filter 2: Nifty trend
        nifty_ok = True
        recent_nifty = [nifty[nd] for nd in nifty_dates if nd <= d]
        if len(recent_nifty) >= nifty_days:
            nifty_win = recent_nifty[-nifty_days:]
            slope = _linreg_slope(nifty_win)
            current = nifty_win[-1]
            directional_move = abs(slope * nifty_days / current) if current > 0 else 0.0
            nifty_ok = directional_move <= nifty_threshold

        regime[d] = coint_ok and nifty_ok

    n_ok = sum(1 for v in regime.values() if v)
    logger.debug("Regime pass rate: %d/%d (%.0f%%)", n_ok, len(dates), n_ok / len(dates) * 100)
    return regime


# ── Cost model ───────────────────────────────────────────────────────────────

def _cost_open(p_long: float, p_short: float) -> float:
    nl = p_long  * (1 + SLIPPAGE)
    ns = p_short * (1 - SLIPPAGE)
    c  = BROKERAGE * 2
    c += nl * (EXCHANGE_PCT + STAMP_DUTY_PCT) + ns * (EXCHANGE_PCT + STT_SELL_PCT)
    c += (BROKERAGE + nl * EXCHANGE_PCT + ns * EXCHANGE_PCT) * GST_PCT
    return c


def _cost_close(p_long: float, p_short: float) -> float:
    nl = p_long  * (1 - SLIPPAGE)
    ns = p_short * (1 + SLIPPAGE)
    c  = BROKERAGE * 2
    c += nl * (EXCHANGE_PCT + STT_SELL_PCT) + ns * (EXCHANGE_PCT + STAMP_DUTY_PCT)
    c += (BROKERAGE + nl * EXCHANGE_PCT + ns * EXCHANGE_PCT) * GST_PCT
    return c


# ── Simulation ───────────────────────────────────────────────────────────────

def _simulate(
    test_dates:   list[date],
    test_z:       list[float],
    test_pa:      list[float],
    test_pb:      list[float],
    hedge_ratio:  float,
    regime:       dict[date, bool],
    sym_a: str,
    sym_b: str,
    z_entry: float,
) -> list[dict]:
    """Simulate pairs strategy on one test window with regime gate at entry."""
    trades: list[dict] = []
    pos       = "FLAT"
    e_date    = None
    e_z = e_pa = e_pb = 0.0
    cooldown_until: date | None = None

    for d, z, pa, pb in zip(test_dates, test_z, test_pa, test_pb):
        if cooldown_until and d <= cooldown_until:
            continue

        if pos == "FLAT":
            if abs(z) <= z_entry:
                continue
            # Regime gate — only enter when market is cointegrated + non-trending
            if not regime.get(d, False):
                continue

            pos   = "SHORT_SPREAD" if z > z_entry else "LONG_SPREAD"
            e_date, e_z, e_pa, e_pb = d, z, pa, pb

        else:
            holding = (d - e_date).days

            # Stop
            if abs(z) > Z_STOP:
                trades.append(_close_trade(pos, e_date, d, holding, e_z, z,
                                           e_pa, e_pb, pa, pb, hedge_ratio, "stop"))
                pos = "FLAT"
                cooldown_until = d + timedelta(days=COOLDOWN_DAYS)
                continue

            # Exit
            exiting = (pos == "SHORT_SPREAD" and z < Z_EXIT) or \
                      (pos == "LONG_SPREAD"  and z > -Z_EXIT)
            if exiting:
                trades.append(_close_trade(pos, e_date, d, holding, e_z, z,
                                           e_pa, e_pb, pa, pb, hedge_ratio, "reversion"))
                pos = "FLAT"

    return trades


def _close_trade(
    pos: str, e_date: date, x_date: date, holding: int,
    e_z: float, x_z: float,
    e_pa: float, e_pb: float, x_pa: float, x_pb: float,
    hedge: float, reason: str,
) -> dict:
    n = POSITION_SIZE_PER_LEG / e_pa if e_pa > 0 else 1.0
    if pos == "LONG_SPREAD":
        gross = (x_pa - e_pa) * n - (x_pb - e_pb) * hedge * n
        cost  = _cost_open(e_pa * n, e_pb * hedge * n) + \
                _cost_close(x_pa * n, x_pb * hedge * n) + \
                e_pb * hedge * n * BORROW_COST_DAY * holding
    else:
        gross = -(x_pa - e_pa) * n + (x_pb - e_pb) * hedge * n
        cost  = _cost_open(e_pb * hedge * n, e_pa * n) + \
                _cost_close(x_pb * hedge * n, x_pa * n) + \
                e_pa * n * BORROW_COST_DAY * holding
    return {
        "entry_date": e_date, "exit_date": x_date, "holding_days": holding,
        "position": pos, "entry_z": round(e_z, 3), "exit_z": round(x_z, 3),
        "pnl": round(gross - cost, 2), "exit_reason": reason,
    }


# ── Walk-forward ─────────────────────────────────────────────────────────────

def _add_months(d: date, m: int) -> date:
    month = d.month + m
    year  = d.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    return d.replace(year=year, month=month, day=1)


def walk_forward(
    sym_a: str, sym_b: str,
    dates: list[date], prices_a: list[float], prices_b: list[float],
    regime: dict[date, bool],
    z_entry: float,
) -> dict:
    """12m train / 3m test walk-forward with regime filter."""
    if len(dates) < WF_TRAIN_MONTHS * 20:
        return {"error": f"insufficient data: {len(dates)} bars"}

    start_date = dates[0]
    end_date   = dates[-1]
    windows: list[dict] = []
    months_elapsed = 0

    while True:
        train_start = _add_months(start_date, months_elapsed)
        train_end   = _add_months(start_date, months_elapsed + WF_TRAIN_MONTHS)
        test_start  = train_end
        test_end    = _add_months(start_date, months_elapsed + WF_TRAIN_MONTHS + WF_TEST_MONTHS)

        if test_end > end_date + timedelta(days=31):
            break

        train_idx = [i for i, d in enumerate(dates) if train_start <= d < train_end]
        test_idx  = [i for i, d in enumerate(dates) if test_start  <= d < test_end]

        if len(train_idx) < 60 or len(test_idx) < 10:
            months_elapsed += WF_TEST_MONTHS
            continue

        pa_tr = [prices_a[i] for i in train_idx]
        pb_tr = [prices_b[i] for i in train_idx]
        pa_te = [prices_a[i] for i in test_idx]
        pb_te = [prices_b[i] for i in test_idx]
        d_te  = [dates[i]    for i in test_idx]

        # Training window: coint p-value + OLS hedge
        coint_p = _eg_coint_p(pa_tr, pb_tr)
        hedge   = _ols_beta(pa_tr, pb_tr)

        # Z-score from training spread statistics
        spread_tr = [a - hedge * b for a, b in zip(pa_tr, pb_tr)]
        tr_mean   = statistics.mean(spread_tr)
        tr_std    = statistics.stdev(spread_tr) if len(spread_tr) > 1 else 1.0

        # Test period z-scores
        spread_te = [a - hedge * b for a, b in zip(pa_te, pb_te)]
        z_te      = [(s - tr_mean) / tr_std for s in spread_te] if tr_std > 0 else [0.0] * len(spread_te)

        trades = _simulate(d_te, z_te, pa_te, pb_te, hedge, regime, sym_a, sym_b, z_entry)

        pnl_list  = [t["pnl"] for t in trades]
        total_pnl = sum(pnl_list)
        span      = (d_te[-1] - d_te[0]).days if len(d_te) > 1 else 91

        windows.append({
            "train_start":  train_start.isoformat(),
            "train_end":    train_end.isoformat(),
            "test_start":   test_start.isoformat(),
            "test_end":     test_end.isoformat(),
            "coint_pval":   round(coint_p, 4),
            "hedge_ratio":  round(hedge, 4),
            "n_trades":     len(trades),
            "total_pnl":    round(total_pnl, 2),
            "sharpe":       round(_sharpe(pnl_list, float(span)), 3),
            "profitable":   total_pnl > 0,
            "trades":       trades,
        })

        months_elapsed += WF_TEST_MONTHS
        if months_elapsed > 120:
            break

    if not windows:
        return {"error": "no walk-forward windows produced"}

    all_trades  = [t for w in windows for t in w["trades"]]
    all_pnl     = [t["pnl"] for t in all_trades]
    total_span  = (dates[-1] - dates[0]).days

    profitable_trades = sum(1 for t in all_trades if t["pnl"] > 0)
    win_rate = profitable_trades / len(all_trades) if all_trades else 0.0

    coint_pass_count = sum(1 for w in windows if w["coint_pval"] < 0.05)
    coint_pass_pct   = coint_pass_count / len(windows) * 100 if windows else 0

    return {
        "sym_a": sym_a, "sym_b": sym_b,
        "n_windows": len(windows),
        "coint_pass_pct": round(coint_pass_pct, 1),
        "n_trades": len(all_trades),
        "total_pnl": round(sum(all_pnl), 2),
        "wf_sharpe": round(_sharpe(all_pnl, float(total_span)), 3),
        "max_drawdown": round(_max_drawdown(all_pnl), 2),
        "max_drawdown_pct": round(_max_drawdown(all_pnl) / POSITION_SIZE_PER_LEG, 4),
        "win_rate": round(win_rate, 3),
        "wins": profitable_trades,
        "losses": len(all_trades) - profitable_trades,
        "windows": windows,
    }


# ── Tier verdict ─────────────────────────────────────────────────────────────

def _tier_verdict(result: dict) -> str:
    if "error" in result:
        return "OVERRIDE"
    n      = result["n_trades"]
    sharpe = result["wf_sharpe"]
    dd_pct = result["max_drawdown_pct"]
    wr     = result["win_rate"]

    if n >= TIER1_MIN_TRADES and sharpe >= TIER1_SHARPE and dd_pct <= TIER1_MAX_DD and wr >= TIER1_WIN_RATE:
        return "TIER_1"
    if n >= TIER2_MIN_TRADES and sharpe >= TIER2_SHARPE_LO and dd_pct <= TIER2_MAX_DD and wr >= TIER2_WIN_RATE:
        return "TIER_2"
    return "OVERRIDE"


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Regime-filtered pairs validation")
    parser.add_argument("--from", dest="start", default="2021-01-01")
    parser.add_argument("--to",   dest="end",   default=str(date.today()))
    parser.add_argument("--z-entry",         type=float, default=Z_ENTRY)
    parser.add_argument("--coint-p",         type=float, default=REGIME_COINT_P)
    parser.add_argument("--nifty-threshold", type=float, default=NIFTY_THRESHOLD)
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end   = date.fromisoformat(args.end)
    # Extend start for regime lookback
    data_start = date(start.year - 1, start.month, 1)

    from mcp_server.db import SessionLocal
    session = SessionLocal()

    # Load Nifty 50
    logger.info("Loading Nifty 50 for slope filter...")
    nifty = _load_nifty(data_start, end)
    logger.info("Nifty: %d bars", len(nifty))

    pair_results: list[dict] = []

    for sym_a, sym_b in PAIRS:
        logger.info("─── %s / %s ───", sym_a, sym_b)

        pa_all = _load_prices(session, sym_a, data_start, end)
        pb_all = _load_prices(session, sym_b, data_start, end)

        if len(pa_all) < 100 or len(pb_all) < 100:
            logger.warning("%s/%s: insufficient price data", sym_a, sym_b)
            pair_results.append({"sym_a": sym_a, "sym_b": sym_b, "error": "insufficient data"})
            continue

        dates, prices_a, prices_b = _aligned(pa_all, pb_all)
        logger.info("%s/%s: %d aligned bars (%s → %s)", sym_a, sym_b, len(dates), dates[0], dates[-1])

        # Pre-compute regime filter for every date
        logger.info("Pre-computing regime filter (rolling %d-day coint + Nifty slope)...",
                    args.coint_p)
        regime = _precompute_regime(
            dates, prices_a, prices_b, nifty,
            REGIME_COINT_DAYS, args.coint_p,
            NIFTY_SLOPE_DAYS, args.nifty_threshold,
        )
        n_pass = sum(1 for v in regime.values() if v)
        logger.info("Regime: %d/%d dates pass (%.0f%%)", n_pass, len(dates), n_pass / len(dates) * 100)

        # Slice to backtest window
        bt_dates   = [d for d in dates   if start <= d <= end]
        bt_idx     = [dates.index(d)     for d in bt_dates]
        bt_prices_a = [prices_a[i] for i in bt_idx]
        bt_prices_b = [prices_b[i] for i in bt_idx]

        if len(bt_dates) < 200:
            logger.warning("%s/%s: only %d bars in backtest window", sym_a, sym_b, len(bt_dates))
            pair_results.append({"sym_a": sym_a, "sym_b": sym_b, "error": "insufficient backtest data"})
            continue

        result = walk_forward(sym_a, sym_b, bt_dates, bt_prices_a, bt_prices_b, regime, args.z_entry)
        tier   = _tier_verdict(result)
        result["tier"] = tier
        pair_results.append(result)

        if "error" in result:
            logger.warning("%s/%s: %s", sym_a, sym_b, result["error"])
            continue

        logger.info(
            "%s/%s RESULT: tier=%s trades=%d sharpe=%.2f maxdd=%.0f%% win_rate=%.0f%%",
            sym_a, sym_b, tier,
            result["n_trades"], result["wf_sharpe"],
            result["max_drawdown_pct"] * 100, result["win_rate"] * 100,
        )

    session.close()

    # ── Universe verdict ────────────────────────────────────────────────────

    tiers = [r.get("tier", "OVERRIDE") for r in pair_results]
    n_t1 = tiers.count("TIER_1")
    n_t2 = tiers.count("TIER_2")

    if n_t1 >= 1:
        universe_verdict = "PROCEED"
        universe_action  = "Extend regime filter to all 6 screener pairs"
    elif n_t2 >= 1 and n_t1 == 0:
        universe_verdict = "PROCEED_WITH_CAUTION"
        universe_action  = "Paper trade 3 months; may extend to all 6 pairs if positive"
    else:
        universe_verdict = "OVERRIDE — PAIRS CHAPTER PERMANENTLY CLOSED"
        universe_action  = "No further pairs iterations. Proceed to momentum + RSI strategies."

    # ── Print results ────────────────────────────────────────────────────────

    sep = "=" * 72
    print()
    print(sep)
    print(f"REGIME-FILTERED PAIRS VALIDATION  |  z={args.z_entry}  |  {args.start} → {args.end}")
    print(f"Regime: rolling {REGIME_COINT_DAYS}-day coint p<{args.coint_p} + Nifty slope≤{args.nifty_threshold}")
    print(sep)
    print()
    print(f"{'Pair':<20} {'Tier':<12} {'Trades':>7}  {'Sharpe':>7}  {'MaxDD':>7}  {'WinRate':>8}  {'TotalPnL':>10}")
    print("-" * 72)

    for r in pair_results:
        pair = f"{r['sym_a']}/{r['sym_b']}"
        if "error" in r:
            print(f"{pair:<20} {'ERROR':<12}  — {r['error']}")
            continue
        print(
            f"{pair:<20} {r['tier']:<12} {r['n_trades']:>7}  "
            f"{r['wf_sharpe']:>7.2f}  {r['max_drawdown_pct']*100:>6.1f}%  "
            f"{r['win_rate']*100:>7.0f}%  ₹{r['total_pnl']:>9,.0f}"
        )

    print()
    print(sep)
    print(f"UNIVERSE VERDICT: {universe_verdict}")
    print(f"ACTION: {universe_action}")
    print(sep)

    print()
    print("TIER THRESHOLDS:")
    print(f"  TIER_1:  trades≥{TIER1_MIN_TRADES}, Sharpe≥{TIER1_SHARPE}, MaxDD≤{TIER1_MAX_DD*100:.0f}%, WinRate≥{TIER1_WIN_RATE*100:.0f}%")
    print(f"  TIER_2:  trades≥{TIER2_MIN_TRADES}, Sharpe≥{TIER2_SHARPE_LO}, MaxDD≤{TIER2_MAX_DD*100:.0f}%, WinRate≥{TIER2_WIN_RATE*100:.0f}%")
    print("  OVERRIDE: any of those conditions missed")

    # Per-pair window detail
    for r in pair_results:
        if "error" in r or not r.get("windows"):
            continue
        pair = f"{r['sym_a']}/{r['sym_b']}"
        print(f"\n{pair} — walk-forward windows ({r['n_windows']} total, "
              f"coint pass {r['coint_pass_pct']:.0f}%)")
        print(f"{'Period':<24} {'p-val':>6}  {'Trades':>7}  {'PnL':>10}  {'Sharpe':>8}")
        print("-" * 62)
        for w in r["windows"]:
            period = f"{w['test_start'][:7]}→{w['test_end'][:7]}"
            print(
                f"{period:<24} {w['coint_pval']:>6.3f}  {w['n_trades']:>7}  "
                f"₹{w['total_pnl']:>9,.0f}  {w['sharpe']:>8.2f}"
            )

    # ── Save report ──────────────────────────────────────────────────────────

    out = Path("reports") / f"regime_pairs_{date.today()}.md"
    out.parent.mkdir(exist_ok=True)
    lines = [
        f"# Regime-Filtered Pairs Validation — {date.today()}",
        f"z_entry={args.z_entry} | coint_p<{args.coint_p} | nifty_threshold={args.nifty_threshold}",
        f"Period: {args.start} → {args.end}",
        "",
        "## Results",
        "",
        "| Pair | Tier | Trades | Sharpe | MaxDD | WinRate | TotalPnL |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in pair_results:
        if "error" in r:
            lines.append(f"| {r['sym_a']}/{r['sym_b']} | ERROR | — | — | — | — | — |")
        else:
            lines.append(
                f"| {r['sym_a']}/{r['sym_b']} | {r['tier']} | {r['n_trades']} "
                f"| {r['wf_sharpe']:.2f} | {r['max_drawdown_pct']*100:.1f}% "
                f"| {r['win_rate']*100:.0f}% | ₹{r['total_pnl']:,.0f} |"
            )
    lines += [
        "",
        f"## Universe Verdict: **{universe_verdict}**",
        f"**Action:** {universe_action}",
    ]
    out.write_text("\n".join(lines))
    logger.info("Report saved: %s", out)


if __name__ == "__main__":
    main()
