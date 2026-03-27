from mcp_server.backtester import run_backtest


def test_run_backtest_returns_dict():
    result = run_backtest("RELIANCE", strategy="rrms", days=30)
    assert isinstance(result, dict)


def test_backtest_has_expected_keys():
    result = run_backtest("SBIN", strategy="rrms", days=30)
    expected_keys = ["ticker", "strategy"]
    for key in expected_keys:
        assert key in result, f"Missing key: {key}"
