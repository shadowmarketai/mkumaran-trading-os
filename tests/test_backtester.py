import numpy as np
import pandas as pd
import pytest

from mcp_server.backtester import _generate_rrms_signals, _simulate_trades, run_backtest


def test_run_backtest_returns_dict():
    result = run_backtest("RELIANCE", strategy="rrms", days=30)
    assert isinstance(result, dict)


def test_backtest_has_expected_keys():
    result = run_backtest("SBIN", strategy="rrms", days=30)
    expected_keys = ["ticker", "strategy"]
    for key in expected_keys:
        assert key in result, f"Missing key: {key}"


def _synth_ohlcv(bars: int = 80) -> pd.DataFrame:
    """Build a deterministic uptrending OHLCV frame to exercise RRMS entry zones."""
    rng = np.random.default_rng(seed=42)
    close = 100 + np.cumsum(rng.normal(0.2, 0.8, size=bars))
    high = close + rng.uniform(0.5, 1.5, size=bars)
    low = close - rng.uniform(0.5, 1.5, size=bars)
    return pd.DataFrame(
        {
            "close": close,
            "high": high,
            "low": low,
            "volume": rng.integers(100_000, 500_000, size=bars),
        }
    )


def test_generate_rrms_signals_returns_float_values():
    # RRMSResult fields are Decimal (Phase 2) but the backtester lives in the
    # analysis zone (pandas/numpy). The boundary cast must happen at signal
    # dict construction so _simulate_trades can multiply against float
    # slippage constants without Decimal×float TypeError.
    df = _synth_ohlcv()
    signals = _generate_rrms_signals(df, "NSE:TEST", capital=100_000)
    for sig in signals:
        for key in ("entry", "stop_loss", "target", "risk_per_share", "reward_per_share"):
            assert isinstance(sig[key], float), (
                f"signals[{key}] must be float for the backtester's "
                f"float-slippage math, got {type(sig[key]).__name__}"
            )


def test_simulate_trades_does_not_error_on_rrms_signals():
    # End-to-end smoke: generate → simulate. If the boundary cast is missing
    # this raises TypeError("unsupported operand type(s) for *: 'decimal.Decimal' and 'float'")
    # inside _apply_slippage.
    df = _synth_ohlcv()
    signals = _generate_rrms_signals(df, "NSE:TEST", capital=100_000)
    if not signals:
        pytest.skip("Synth data produced no valid RRMS entries; nothing to simulate")
    trades, equity, costs = _simulate_trades(df, signals, capital=100_000)
    assert isinstance(trades, list)
    assert isinstance(equity, list)
    assert isinstance(costs, float)


def test_simulate_trades_with_explicit_signal_hits_target():
    # Deterministic: craft a frame where the next bar hits the target so we
    # exercise the full _apply_slippage + _calculate_transaction_cost path.
    df = pd.DataFrame({
        "close":  [100.0, 100.0, 100.0, 100.0],
        "high":   [100.5, 110.0, 105.0, 101.0],  # bar 1 high=110 crosses target
        "low":    [99.5, 98.0, 95.0, 99.5],
        "volume": [100000, 120000, 80000, 95000],
    })
    signals = [{
        "bar_idx": 0,
        "direction": "LONG",
        "entry": 100.0,
        "stop_loss": 95.0,
        "target": 108.0,
        "qty": 10,
        "source": "rrms",
        "confidence": 70,
    }]
    trades, equity, costs = _simulate_trades(df, signals, capital=100_000)
    assert len(trades) == 1
    assert trades[0]["outcome"] == "WIN"
    assert costs > 0
