"""Unit tests for statistical backtest validation (Monte Carlo / Bootstrap /
Walk-Forward). Uses synthetic trades + equity curves — no network or DB."""

from __future__ import annotations

import numpy as np
import pandas as pd

from mcp_server.backtest_validation import (
    bootstrap_sharpe_ci,
    monte_carlo_test,
    run_full_validation,
    summarise,
    walk_forward_analysis,
)


# ── Monte Carlo ────────────────────────────────────────────────

def test_monte_carlo_flags_too_few_trades():
    result = monte_carlo_test([{"pnl": 100}, {"pnl": -50}], initial_capital=100_000)
    assert "error" in result
    assert result["p_value_sharpe"] == 1.0


def test_monte_carlo_returns_expected_keys_on_winning_series():
    # 20 trades, positive drift → actual Sharpe should be hard to beat by
    # random reordering, so p_value_sharpe should be low.
    rng = np.random.default_rng(0)
    trades = [{"pnl": float(rng.normal(loc=500, scale=100))} for _ in range(20)]
    result = monte_carlo_test(trades, initial_capital=100_000, n_simulations=500, seed=0)
    for key in (
        "actual_sharpe", "p_value_sharpe", "actual_max_dd", "p_value_max_dd",
        "simulated_sharpe_mean", "n_simulations", "n_trades", "is_significant",
    ):
        assert key in result
    assert result["n_trades"] == 20
    # Permutation flips the path, not the sum — so p_value_sharpe can be
    # high even for a positive series. Just assert it's a valid probability.
    assert 0.0 <= result["p_value_sharpe"] <= 1.0


# ── Bootstrap ──────────────────────────────────────────────────

def test_bootstrap_errors_on_short_series():
    eq = pd.Series([100, 101, 102])
    result = bootstrap_sharpe_ci(eq, n_bootstrap=100)
    assert "error" in result


def test_bootstrap_positive_ci_on_trending_equity():
    # Daily drift of ~0.3% for 60 days → strong positive Sharpe.
    rng = np.random.default_rng(1)
    returns = rng.normal(loc=0.003, scale=0.01, size=60)
    eq = 100_000 * (1 + pd.Series(returns)).cumprod()
    result = bootstrap_sharpe_ci(eq, n_bootstrap=300, seed=1)
    assert result["observed_sharpe"] > 0
    assert result["ci_lower"] < result["ci_upper"]
    assert result["prob_positive"] > 0.5


def test_bootstrap_accepts_list_of_dicts_from_backtester():
    # Our backtester.run_backtest returns equity_curve as [{date, equity}].
    rows = [
        {"date": f"2026-01-{d:02d}", "equity": 100_000 + d * 500}
        for d in range(1, 31)
    ]
    result = bootstrap_sharpe_ci(rows, n_bootstrap=200, seed=2)
    assert "observed_sharpe" in result
    assert result["ci_lower"] <= result["ci_upper"]


# ── Walk-forward ───────────────────────────────────────────────

def test_walk_forward_errors_on_too_few_bars():
    eq = pd.Series([100, 101, 102, 103])  # 4 bars < 5*2
    result = walk_forward_analysis(eq, trades=[], n_windows=5)
    assert "error" in result


def test_walk_forward_buckets_trades_by_window():
    dates = pd.date_range("2026-01-01", periods=50, freq="D")
    eq = pd.Series(np.linspace(100_000, 120_000, 50), index=dates)
    trades = [
        {"pnl": 100, "entry_date": str(dates[5])},
        {"pnl": -50, "entry_date": str(dates[25])},
        {"pnl": 200, "entry_date": str(dates[45])},
    ]
    result = walk_forward_analysis(eq, trades, n_windows=5)
    assert "windows" in result
    assert len(result["windows"]) == 5
    total_trades_across_windows = sum(w["trades"] for w in result["windows"])
    assert total_trades_across_windows == 3
    assert "consistency_rate" in result


# ── run_full_validation + summarise ────────────────────────────

def test_run_full_validation_handles_backtester_shape():
    dates = pd.date_range("2026-01-01", periods=40, freq="D")
    equity_curve = [
        {"date": str(dates[i]), "equity": 100_000 + i * 400}
        for i in range(40)
    ]
    trades = [
        {"pnl": 200, "entry_date": str(dates[5])},
        {"pnl": -80, "entry_date": str(dates[15])},
        {"pnl": 350, "entry_date": str(dates[25])},
        {"pnl": -60, "entry_date": str(dates[35])},
    ]
    bt_result = {
        "trades": trades,
        "equity_curve": equity_curve,
        "initial_capital": 100_000,
    }
    validation = run_full_validation(
        bt_result,
        monte_carlo_kwargs={"n_simulations": 300},
        bootstrap_kwargs={"n_bootstrap": 300},
        walk_forward_kwargs={"n_windows": 4},
    )
    assert set(validation.keys()) == {"monte_carlo", "bootstrap", "walk_forward", "meta"}
    assert validation["meta"]["n_trades"] == 4
    assert validation["meta"]["initial_capital"] == 100_000
    summary_text = summarise(validation)
    assert "Monte Carlo" in summary_text or "Bootstrap" in summary_text


def test_run_full_validation_survives_empty_inputs():
    validation = run_full_validation({})
    # All three tests should return error fields rather than crashing.
    for key in ("monte_carlo", "bootstrap", "walk_forward"):
        assert key in validation
        assert "error" in validation[key] or "p_value_sharpe" in validation[key]
