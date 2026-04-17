"""
MKUMARAN Trading OS — Statistical Backtest Validation

Three independent tests that answer whether a backtest's edge is real or
a lucky path through the market:

    monte_carlo_test()       Is the Sharpe ratio better than random reordering
                             of the same trades? p-value < 0.05 ⇒ real edge.

    bootstrap_sharpe_ci()    How stable is the Sharpe across resampled
                             return paths? Narrow CI not crossing 0 ⇒ robust.

    walk_forward_analysis()  Is the strategy profitable across sequential
                             time windows? High consistency rate ⇒ durable.

Adapted from HKUDS/Vibe-Trading's `agent/backtest/validation.py` (MIT-licensed)
to work against our own `backtester.run_backtest` output shape instead of
Vibe's TradeRecord dataclass. Accepts plain dicts/lists to stay decoupled
from the backtester's internals.

Usage:

    from mcp_server.backtester import run_backtest
    from mcp_server.backtest_validation import run_full_validation

    bt = run_backtest("NSE:RELIANCE", strategy="rrms", days=1095)
    validation = run_full_validation(bt)
    # {
    #   'monte_carlo':  {'p_value_sharpe': 0.03, ...},
    #   'bootstrap':    {'ci_lower': 0.4, 'ci_upper': 1.8, 'prob_positive': 0.98},
    #   'walk_forward': {'consistency_rate': 0.8, 'windows': [...]},
    # }
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ── Shared helpers ──────────────────────────────────────────────

def _sharpe(returns: np.ndarray, bars_per_year: int = 252) -> float:
    """Annualised Sharpe from a return series. Small epsilon guards /0."""
    if returns.size == 0:
        return 0.0
    std = returns.std()
    return float(returns.mean() / (std + 1e-10) * np.sqrt(bars_per_year))


def _path_metrics(pnls: np.ndarray, initial_capital: float) -> dict[str, float]:
    """Compute Sharpe and max drawdown from a cash-PnL sequence."""
    equity = initial_capital + np.cumsum(pnls)
    if equity.size <= 1:
        return {"sharpe": 0.0, "max_dd": 0.0}
    returns = np.diff(equity) / equity[:-1]
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / np.where(peak > 0, peak, 1.0)
    return {
        "sharpe": _sharpe(returns),
        "max_dd": float(dd.min()),
    }


def _extract_equity_series(equity_curve: Any) -> pd.Series | None:
    """Coerce backtest equity_curve into a DatetimeIndexed pd.Series.

    Accepts:
        - pd.Series (returned as-is if index is datetime-like)
        - list[dict] with {date, equity} keys (our backtester's sampled format)
        - list[float] or np.ndarray (index becomes RangeIndex)
    Returns None if the series is too short to analyse.
    """
    if isinstance(equity_curve, pd.Series):
        series = equity_curve
    elif isinstance(equity_curve, (list, tuple)) and equity_curve:
        first = equity_curve[0]
        if isinstance(first, dict) and "equity" in first:
            dates = [pd.to_datetime(row.get("date")) for row in equity_curve]
            values = [float(row["equity"]) for row in equity_curve]
            series = pd.Series(values, index=pd.DatetimeIndex(dates))
        else:
            series = pd.Series([float(v) for v in equity_curve])
    elif isinstance(equity_curve, np.ndarray):
        series = pd.Series(equity_curve.astype(float))
    else:
        return None

    if len(series) < 2:
        return None
    return series


def _extract_trade_pnls(trades: list[dict]) -> np.ndarray:
    """Pull pnl values out of our backtester's trade dicts."""
    pnls = []
    for trade in trades:
        value = trade.get("pnl")
        if value is None:
            continue
        try:
            pnls.append(float(value))
        except (TypeError, ValueError):
            continue
    return np.asarray(pnls, dtype=float)


def _extract_trade_timestamps(trades: list[dict]) -> list[pd.Timestamp | None]:
    """Pull entry timestamps so walk-forward can bucket trades by window."""
    stamps: list[pd.Timestamp | None] = []
    for trade in trades:
        raw = (
            trade.get("entry_time")
            or trade.get("entry_date")
            or trade.get("date")
        )
        if raw is None:
            stamps.append(None)
            continue
        try:
            stamps.append(pd.to_datetime(raw))
        except Exception:  # noqa: BLE001
            stamps.append(None)
    return stamps


# ── Monte Carlo permutation test ────────────────────────────────

def monte_carlo_test(
    trades: list[dict],
    initial_capital: float,
    n_simulations: int = 1000,
    seed: int = 42,
) -> dict[str, Any]:
    """Shuffle trade PnL order; ask how often a random ordering beats ours.

    Null hypothesis: the observed Sharpe is no better than a random
    permutation of the same trade PnLs. `p_value_sharpe` is the fraction
    of shuffles whose Sharpe ≥ the real Sharpe. Values below 0.05 are
    the conventional threshold for "strategy is significantly better
    than random ordering".
    """
    pnls = _extract_trade_pnls(trades)
    if pnls.size < 3:
        return {"error": "need at least 3 trades with pnl", "p_value_sharpe": 1.0}

    actual = _path_metrics(pnls, initial_capital)
    rng = np.random.default_rng(seed)
    sharpe_beats = 0
    dd_beats = 0
    sim_sharpes: list[float] = []

    for _ in range(n_simulations):
        shuffled = rng.permutation(pnls)
        sim = _path_metrics(shuffled, initial_capital)
        sim_sharpes.append(sim["sharpe"])
        if sim["sharpe"] >= actual["sharpe"]:
            sharpe_beats += 1
        if sim["max_dd"] >= actual["max_dd"]:  # less negative = "better"
            dd_beats += 1

    sim_arr = np.array(sim_sharpes)
    return {
        "actual_sharpe": round(actual["sharpe"], 4),
        "actual_max_dd": round(actual["max_dd"], 4),
        "p_value_sharpe": round(sharpe_beats / n_simulations, 4),
        "p_value_max_dd": round(dd_beats / n_simulations, 4),
        "simulated_sharpe_mean": round(float(sim_arr.mean()), 4),
        "simulated_sharpe_std": round(float(sim_arr.std()), 4),
        "simulated_sharpe_p5": round(float(np.percentile(sim_arr, 5)), 4),
        "simulated_sharpe_p95": round(float(np.percentile(sim_arr, 95)), 4),
        "n_simulations": n_simulations,
        "n_trades": int(pnls.size),
        "is_significant": (sharpe_beats / n_simulations) < 0.05,
    }


# ── Bootstrap Sharpe confidence interval ────────────────────────

def bootstrap_sharpe_ci(
    equity_curve: Any,
    n_bootstrap: int = 1000,
    confidence: float = 0.95,
    bars_per_year: int = 252,
    seed: int = 42,
) -> dict[str, Any]:
    """Resample daily returns to estimate a Sharpe confidence interval.

    Answers "if we had re-drawn similar return days, how wide is the
    Sharpe range?" A tight positive CI is what you want. If `ci_lower`
    crosses zero, your edge is not statistically distinguishable from
    no edge.
    """
    series = _extract_equity_series(equity_curve)
    if series is None:
        return {"error": "invalid equity curve"}
    returns = series.pct_change().dropna().values
    if returns.size < 5:
        return {"error": "need at least 5 return observations"}

    observed = _sharpe(returns, bars_per_year)
    rng = np.random.default_rng(seed)
    boot_sharpes = [
        _sharpe(rng.choice(returns, size=returns.size, replace=True), bars_per_year)
        for _ in range(n_bootstrap)
    ]

    arr = np.array(boot_sharpes)
    alpha = (1 - confidence) / 2
    lower = float(np.percentile(arr, alpha * 100))
    upper = float(np.percentile(arr, (1 - alpha) * 100))
    return {
        "observed_sharpe": round(observed, 4),
        "ci_lower": round(lower, 4),
        "ci_upper": round(upper, 4),
        "median_sharpe": round(float(np.median(arr)), 4),
        "prob_positive": round(float(np.mean(arr > 0)), 4),
        "confidence": confidence,
        "n_bootstrap": n_bootstrap,
        "ci_crosses_zero": lower < 0 < upper,
    }


# ── Walk-forward analysis ───────────────────────────────────────

def walk_forward_analysis(
    equity_curve: Any,
    trades: list[dict],
    n_windows: int = 5,
    bars_per_year: int = 252,
) -> dict[str, Any]:
    """Split the backtest into N sequential windows; check consistency.

    Each window is evaluated independently. A strategy that's profitable
    in 5/5 windows has durable edge; one profitable only in 2/5 likely
    has a regime dependency or got lucky in one stretch.
    """
    series = _extract_equity_series(equity_curve)
    if series is None:
        return {"error": "invalid equity curve"}
    if len(series) < n_windows * 2:
        return {
            "error": (
                f"need at least {n_windows * 2} bars for {n_windows} windows "
                f"(got {len(series)})"
            )
        }

    timestamps = _extract_trade_timestamps(trades)
    trade_pnls = _extract_trade_pnls(trades)
    idx = series.index
    window_size = len(idx) // n_windows
    windows: list[dict[str, Any]] = []

    for i in range(n_windows):
        start = i * window_size
        end = (i + 1) * window_size if i < n_windows - 1 else len(idx)
        win_eq = series.iloc[start:end]
        if win_eq.empty:
            continue

        win_start_ts = idx[start]
        win_end_ts = idx[end - 1]

        ret = (
            float(win_eq.iloc[-1] / win_eq.iloc[0] - 1)
            if win_eq.iloc[0] > 0 else 0.0
        )
        win_returns = win_eq.pct_change().dropna().values
        sharpe = _sharpe(win_returns, bars_per_year) if win_returns.size > 1 else 0.0
        peak = win_eq.cummax()
        dd = (win_eq - peak) / peak.replace(0, 1)
        max_dd = float(dd.min())

        in_window = [
            trade_pnls[j] for j, ts in enumerate(timestamps)
            if ts is not None and win_start_ts <= ts <= win_end_ts
        ]
        win_pnls = np.asarray(in_window, dtype=float)
        win_rate = (
            float((win_pnls > 0).sum() / win_pnls.size)
            if win_pnls.size else 0.0
        )

        windows.append({
            "window": i + 1,
            "start": str(win_start_ts.date()) if hasattr(win_start_ts, "date") else str(win_start_ts),
            "end": str(win_end_ts.date()) if hasattr(win_end_ts, "date") else str(win_end_ts),
            "return": round(ret, 6),
            "sharpe": round(sharpe, 4),
            "max_dd": round(max_dd, 6),
            "trades": int(win_pnls.size),
            "win_rate": round(win_rate, 4),
        })

    returns_list = [w["return"] for w in windows]
    sharpes_list = [w["sharpe"] for w in windows]
    profitable = sum(1 for r in returns_list if r > 0)
    return {
        "n_windows": len(windows),
        "windows": windows,
        "profitable_windows": profitable,
        "consistency_rate": round(profitable / max(len(windows), 1), 4),
        "return_mean": round(float(np.mean(returns_list)) if returns_list else 0.0, 6),
        "return_std": round(float(np.std(returns_list)) if returns_list else 0.0, 6),
        "sharpe_mean": round(float(np.mean(sharpes_list)) if sharpes_list else 0.0, 4),
        "sharpe_std": round(float(np.std(sharpes_list)) if sharpes_list else 0.0, 4),
    }


# ── High-level runner ──────────────────────────────────────────

def run_full_validation(
    backtest_result: dict[str, Any],
    initial_capital: float | None = None,
    monte_carlo_kwargs: dict[str, Any] | None = None,
    bootstrap_kwargs: dict[str, Any] | None = None,
    walk_forward_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run all three validations against a backtester.run_backtest() dict.

    Returns a dict keyed by validation name. Silently skips a given test
    if the input data can't support it (too few trades / bars) — the
    skipped test returns an `error` field instead of failing the whole run.
    """
    trades = backtest_result.get("trades") or []
    equity_curve = backtest_result.get("equity_curve") or []
    # Backtester defaults to 100_000 when capital isn't passed; use the
    # same default here so the Monte Carlo equity path starts at the
    # right base.
    if initial_capital is None:
        initial_capital = float(
            backtest_result.get("initial_capital")
            or backtest_result.get("capital")
            or 100_000
        )

    mc_kwargs = monte_carlo_kwargs or {}
    bs_kwargs = bootstrap_kwargs or {}
    wf_kwargs = walk_forward_kwargs or {}

    return {
        "monte_carlo": monte_carlo_test(trades, initial_capital, **mc_kwargs),
        "bootstrap": bootstrap_sharpe_ci(equity_curve, **bs_kwargs),
        "walk_forward": walk_forward_analysis(equity_curve, trades, **wf_kwargs),
        "meta": {
            "initial_capital": initial_capital,
            "n_trades": len(trades),
            "n_equity_points": len(equity_curve),
        },
    }


def summarise(validation: dict[str, Any]) -> str:
    """Render a short, human-readable verdict string. Useful for Telegram."""
    lines: list[str] = []

    mc = validation.get("monte_carlo") or {}
    if "p_value_sharpe" in mc:
        p = mc["p_value_sharpe"]
        verdict = "REAL EDGE" if p < 0.05 else "NOT SIGNIFICANT"
        lines.append(f"Monte Carlo: p={p:.3f} → {verdict}")
    elif mc.get("error"):
        lines.append(f"Monte Carlo: {mc['error']}")

    bs = validation.get("bootstrap") or {}
    if "ci_lower" in bs:
        crosses = bs.get("ci_crosses_zero")
        ci_note = "crosses 0 (weak)" if crosses else "positive CI (robust)"
        lines.append(
            f"Bootstrap Sharpe: {bs['ci_lower']:.2f}–{bs['ci_upper']:.2f} "
            f"@ {int(bs.get('confidence', 0.95) * 100)}% {ci_note}"
        )
    elif bs.get("error"):
        lines.append(f"Bootstrap: {bs['error']}")

    wf = validation.get("walk_forward") or {}
    if "consistency_rate" in wf:
        lines.append(
            f"Walk-Forward: {wf['profitable_windows']}/{wf['n_windows']} "
            f"profitable ({int(wf['consistency_rate'] * 100)}% consistency)"
        )
    elif wf.get("error"):
        lines.append(f"Walk-Forward: {wf['error']}")

    return "\n".join(lines) if lines else "No validation output"


__all__ = [
    "monte_carlo_test",
    "bootstrap_sharpe_ci",
    "walk_forward_analysis",
    "run_full_validation",
    "summarise",
]
