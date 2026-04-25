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
    # Open sits between low and high, biased toward previous close — enough
    # realism to exercise the gap-through-SL path without dominating it.
    open_ = np.concatenate([[close[0]], close[:-1]]) + rng.uniform(-0.3, 0.3, size=bars)
    open_ = np.clip(open_, low, high)
    return pd.DataFrame(
        {
            "open": open_,
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
        "open":   [100.0, 100.2, 104.0, 100.8],
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
    assert trades[0]["exit_reason"] == "TARGET"
    assert costs > 0


# ── Hygiene tests (Phase 2 audit) ─────────────────────────────────


def test_stt_delivery_vs_intraday_rates():
    # Delivery sell STT is 0.025%, intraday sell STT is 0.0125%.
    # Prior constant STT_PCT = 0.001 (0.1%) over-charged by 4x.
    from mcp_server.backtester import (
        STT_DELIVERY_SELL,
        STT_INTRADAY_SELL,
        _calculate_transaction_cost,
    )

    assert STT_DELIVERY_SELL == 0.00025, "Delivery STT must be 0.025% per 2025 rates"
    assert STT_INTRADAY_SELL == 0.000125, "Intraday STT must be 0.0125% per 2025 rates"

    # Same turnover, sell side — intraday must cost less than delivery.
    turnover_price, qty = 1000.0, 10
    cost_delivery = _calculate_transaction_cost(turnover_price, qty, is_sell=True, is_intraday=False)
    cost_intraday = _calculate_transaction_cost(turnover_price, qty, is_sell=True, is_intraday=True)
    assert cost_intraday < cost_delivery, "Intraday STT is half of delivery; total cost must be lower"

    # STT delta between them should be exactly (0.00025 - 0.000125) * turnover.
    expected_delta = (STT_DELIVERY_SELL - STT_INTRADAY_SELL) * turnover_price * qty
    assert abs((cost_delivery - cost_intraday) - expected_delta) < 1e-9


def test_slippage_tiers_are_ordered():
    from mcp_server.backtester import (
        LARGE_CAP_SLIPPAGE,
        MID_CAP_SLIPPAGE,
        SMALL_CAP_SLIPPAGE,
    )

    assert LARGE_CAP_SLIPPAGE < MID_CAP_SLIPPAGE < SMALL_CAP_SLIPPAGE, (
        "Slippage tiers must ascend with illiquidity risk"
    )
    # Large-cap (Nifty 50) is ~5bps; anything above 10bps is wrong for that tier.
    assert LARGE_CAP_SLIPPAGE <= 0.001


def test_gap_through_stop_exits_at_open_not_stop():
    # Long at 100, stop at 95. Next bar gaps down to open=90 — real fill is 90,
    # not 95. Loss must be markedly larger than a clean stop-out.
    df = pd.DataFrame({
        "open":   [100.0, 90.0, 88.0, 87.0],   # bar 1 gaps through stop
        "close":  [100.0, 89.0, 88.0, 87.0],
        "high":   [100.5, 91.0, 89.0, 88.0],
        "low":    [99.5, 87.0, 86.0, 86.0],
        "volume": [100000, 120000, 80000, 95000],
    })
    signals = [{
        "bar_idx": 0,
        "direction": "LONG",
        "entry": 100.0,
        "stop_loss": 95.0,
        "target": 110.0,
        "qty": 10,
        "source": "rrms",
        "confidence": 70,
    }]
    trades, _, _ = _simulate_trades(df, signals, capital=100_000)
    assert len(trades) == 1
    t = trades[0]
    assert t["outcome"] == "LOSS"
    assert t["exit_reason"] == "GAP_SL"
    # Exit should be near the gap-open price (90), not near the stop (95).
    # Slippage is applied, so we compare inequalities rather than equality.
    assert t["exit"] < 92.0, f"Gap-through fill must be near open, got {t['exit']}"
    # Per-unit loss must exceed the clean-stop loss of ~5 rupees.
    per_unit_loss = (100.0 - t["exit"])
    assert per_unit_loss > 7.0, f"Gap loss {per_unit_loss} must be worse than clean stop (~5)"


def test_gap_through_target_exits_at_open_not_target():
    # Short at 100, target at 90, stop at 105. Next bar gaps down to 85 —
    # favorable gap, fill at open, better than target.
    df = pd.DataFrame({
        "open":   [100.0, 85.0, 86.0, 87.0],   # bar 1 gaps through target
        "close":  [100.0, 86.0, 86.0, 87.0],
        "high":   [100.5, 87.0, 88.0, 88.0],
        "low":    [99.5, 84.0, 85.0, 86.0],
        "volume": [100000, 120000, 80000, 95000],
    })
    signals = [{
        "bar_idx": 0,
        "direction": "SHORT",
        "entry": 100.0,
        "stop_loss": 105.0,
        "target": 90.0,
        "qty": 10,
        "source": "rrms",
        "confidence": 70,
    }]
    trades, _, _ = _simulate_trades(df, signals, capital=100_000)
    assert len(trades) == 1
    t = trades[0]
    assert t["outcome"] == "WIN"
    assert t["exit_reason"] == "GAP_TGT"
    # Short-side favorable gap — exit near open (85), better than target (90).
    assert t["exit"] < 88.0, f"Gap-through-target fill should be near open, got {t['exit']}"
