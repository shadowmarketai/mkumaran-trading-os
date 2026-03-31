"""
Tests for Backtest Comparison endpoint (Feature 3)

Validates:
- run_backtest_all_strategies returns correct structure
- All 6 strategies present in comparison
- Equity curves present in detail results
- best_strategy field populated
"""

from unittest.mock import patch
import pandas as pd
import numpy as np


# ── Helper: Generate mock OHLCV data ───────────────────────────


def _make_mock_data(bars: int = 200) -> pd.DataFrame:
    """Generate realistic-looking OHLCV data for testing."""
    dates = pd.date_range("2023-01-01", periods=bars, freq="B")
    np.random.seed(42)
    close = 2500 + np.cumsum(np.random.randn(bars) * 10)
    return pd.DataFrame(
        {
            "open": close - np.random.rand(bars) * 5,
            "high": close + np.random.rand(bars) * 10,
            "low": close - np.random.rand(bars) * 10,
            "close": close,
            "volume": np.random.randint(100000, 1000000, bars),
        },
        index=dates,
    )


# ── run_backtest_all_strategies ─────────────────────────────────


@patch("mcp_server.nse_scanner.get_stock_data")
def test_compare_returns_6_strategies(mock_get):
    """Comparison should include all 6 strategy keys."""
    mock_get.return_value = _make_mock_data(300)
    from mcp_server.backtester import run_backtest_all_strategies

    result = run_backtest_all_strategies("NSE:RELIANCE", days=180)
    assert "comparison" in result
    strategy_names = [s["strategy"] for s in result["comparison"]]
    assert "rrms" in strategy_names
    assert "smc" in strategy_names
    assert "wyckoff" in strategy_names
    assert "vsa" in strategy_names
    assert "harmonic" in strategy_names
    assert "confluence" in strategy_names


@patch("mcp_server.nse_scanner.get_stock_data")
def test_compare_has_best_strategy(mock_get):
    """Result should have best_strategy field."""
    mock_get.return_value = _make_mock_data(300)
    from mcp_server.backtester import run_backtest_all_strategies

    result = run_backtest_all_strategies("NSE:RELIANCE", days=180)
    assert "best_strategy" in result
    assert isinstance(result["best_strategy"], str)


@patch("mcp_server.nse_scanner.get_stock_data")
def test_compare_has_ticker(mock_get):
    """Result should include ticker."""
    mock_get.return_value = _make_mock_data(300)
    from mcp_server.backtester import run_backtest_all_strategies

    result = run_backtest_all_strategies("NSE:RELIANCE", days=180)
    assert result["ticker"] == "NSE:RELIANCE"


@patch("mcp_server.nse_scanner.get_stock_data")
def test_compare_has_period(mock_get):
    """Result should include period string."""
    mock_get.return_value = _make_mock_data(300)
    from mcp_server.backtester import run_backtest_all_strategies

    result = run_backtest_all_strategies("NSE:RELIANCE", days=180)
    assert "period" in result
    assert "180" in result["period"]


@patch("mcp_server.nse_scanner.get_stock_data")
def test_compare_details_have_equity_curve(mock_get):
    """Detail results should include equity_curve for each strategy."""
    mock_get.return_value = _make_mock_data(300)
    from mcp_server.backtester import run_backtest_all_strategies

    result = run_backtest_all_strategies("NSE:RELIANCE", days=180)
    details = result.get("details", {})
    for strat_name, detail in details.items():
        if "error" not in detail:
            assert "equity_curve" in detail, f"{strat_name} missing equity_curve"


@patch("mcp_server.nse_scanner.get_stock_data")
def test_compare_strategy_metrics(mock_get):
    """Each strategy in comparison should have standard metrics."""
    mock_get.return_value = _make_mock_data(300)
    from mcp_server.backtester import run_backtest_all_strategies

    result = run_backtest_all_strategies("NSE:RELIANCE", days=180)
    for s in result["comparison"]:
        assert "strategy" in s
        assert "trades" in s
        assert "win_rate" in s
        assert "profit_factor" in s
        assert "max_drawdown" in s
        assert "sharpe_ratio" in s
        assert "total_return" in s


@patch("mcp_server.nse_scanner.get_stock_data")
def test_compare_handles_insufficient_data(mock_get):
    """Should handle strategies that fail gracefully."""
    mock_get.return_value = _make_mock_data(30)  # Very short data
    from mcp_server.backtester import run_backtest_all_strategies

    # Should not raise — strategies may have 0 trades but still return
    result = run_backtest_all_strategies("NSE:RELIANCE", days=30)
    assert "comparison" in result


@patch("mcp_server.nse_scanner.get_stock_data")
def test_compare_comparison_length(mock_get):
    """Comparison array should have exactly 6 entries."""
    mock_get.return_value = _make_mock_data(300)
    from mcp_server.backtester import run_backtest_all_strategies

    result = run_backtest_all_strategies("NSE:RELIANCE", days=180)
    assert len(result["comparison"]) == 6
