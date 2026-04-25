"""Tests for mcp_server.pos_five_ema — POS 5 EMA setup + trigger detection."""

from decimal import Decimal

import pandas as pd

from mcp_server.pos_five_ema import (
    FiveEMAGenerator,
    FiveEMASignal,
    generate_signals_for_backtest,
)


# ── Fixtures ────────────────────────────────────────────────


def _frame_from_closes(closes: list[float], vol: list[int] | None = None) -> pd.DataFrame:
    """Build a deterministic OHLCV from a closes list. open=close, high=close+0.2, low=close-0.2.

    Caller can override individual rows after constructing.
    """
    n = len(closes)
    if vol is None:
        vol = [100_000] * n
    return pd.DataFrame({
        "open":   closes.copy(),
        "high":   [c + 0.2 for c in closes],
        "low":    [c - 0.2 for c in closes],
        "close":  closes.copy(),
        "volume": vol,
    })


def _long_setup_frame() -> pd.DataFrame:
    """Frame engineered so EMA50 is well below price (passes LONG trend filter)
    AND EMA5 is well above the setup candle (passes range_below_ema5 filter).

    Pattern:
      - 50 bars flat at 100 → builds EMA50 ≈ 100 and vol_avg = 100k.
      - 25 bars rising 100 → 118.75 → pulls EMA5 way above EMA50.
      - Setup bar at index 75: small pullback to ~110 (below EMA5 ~117,
        above EMA50 ~104), high volume.
      - Trigger bar at index 76: breaks the setup high.
    """
    closes = [100.0] * 50 + [100.0 + i * 0.75 for i in range(1, 26)]
    vol = [100_000] * len(closes)
    df = _frame_from_closes(closes, vol)

    # Setup candle: pullback below EMA5 but above EMA50, big volume
    setup_idx = len(df)
    setup_close = 110.0
    df.loc[setup_idx, "open"] = setup_close
    df.loc[setup_idx, "close"] = setup_close
    df.loc[setup_idx, "high"] = setup_close + 0.5   # 110.5 — entry
    df.loc[setup_idx, "low"] = setup_close - 1.0    # 109.0 — stop
    df.loc[setup_idx, "volume"] = 500_000           # 5x avg

    # Trigger candle: high breaks 110.5
    trig_idx = len(df)
    df.loc[trig_idx, "open"] = 110.6
    df.loc[trig_idx, "high"] = 112.0
    df.loc[trig_idx, "low"] = 110.4
    df.loc[trig_idx, "close"] = 111.5
    df.loc[trig_idx, "volume"] = 200_000

    df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": int})
    return df


def _short_setup_frame() -> pd.DataFrame:
    """Mirror of _long_setup_frame for SHORT setups."""
    closes = [200.0] * 50 + [200.0 - i * 0.75 for i in range(1, 26)]
    vol = [100_000] * len(closes)
    df = _frame_from_closes(closes, vol)

    # Setup candle: bounce above EMA5 but below EMA50
    setup_idx = len(df)
    setup_close = 190.0
    df.loc[setup_idx, "open"] = setup_close
    df.loc[setup_idx, "close"] = setup_close
    df.loc[setup_idx, "high"] = setup_close + 1.0   # 191.0 — stop
    df.loc[setup_idx, "low"] = setup_close - 0.5    # 189.5 — entry (must be > EMA5)
    df.loc[setup_idx, "volume"] = 500_000

    # Trigger candle: low breaks 189.5
    trig_idx = len(df)
    df.loc[trig_idx, "open"] = 189.4
    df.loc[trig_idx, "high"] = 189.6
    df.loc[trig_idx, "low"] = 188.0
    df.loc[trig_idx, "close"] = 188.5
    df.loc[trig_idx, "volume"] = 200_000

    df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": int})
    return df


# ── Frame validity ──────────────────────────────────────────


def test_returns_none_on_short_frame():
    gen = FiveEMAGenerator()
    short = _frame_from_closes([100, 101, 102])
    assert gen.detect_latest(short, "TEST") is None


def test_returns_none_on_missing_columns():
    gen = FiveEMAGenerator()
    bad = pd.DataFrame({"close": [1] * 80})
    assert gen.detect_latest(bad, "TEST") is None


# ── Long setup ──────────────────────────────────────────────


def test_long_setup_with_below_ema_and_breakout():
    """LONG: setup candle's high < EMA5 AND current bar's high > setup high."""
    df = _long_setup_frame()
    sig = FiveEMAGenerator().detect_latest(df, "TEST")
    assert sig is not None
    assert isinstance(sig, FiveEMASignal)
    assert sig.direction == "LONG"
    assert sig.entry == Decimal("110.50"), f"Entry must be setup high, got {sig.entry}"
    assert sig.stop_loss == Decimal("109.00"), f"Stop must be setup low, got {sig.stop_loss}"
    # Risk = 1.50; target = entry + 2*risk = 113.50
    assert sig.target == Decimal("113.50")
    # Filters — value comes back as numpy.bool_; check truthiness, not identity
    assert sig.filters_passed["range_below_ema5"]
    assert sig.filters_passed["trend_filter"]
    assert sig.filters_passed["volume_filter"]
    assert sig.filters_passed["trigger_fired"]


def test_long_blocked_when_no_trigger():
    df = _long_setup_frame()
    # Override the trigger candle so its high stays below the setup high.
    trig_idx = len(df) - 1
    df.loc[trig_idx, "high"] = 110.4
    df.loc[trig_idx, "low"] = 109.5
    df.loc[trig_idx, "open"] = 110.0
    df.loc[trig_idx, "close"] = 110.0

    sig = FiveEMAGenerator().detect_latest(df, "TEST")
    assert sig is None


def test_long_blocked_when_volume_below_avg():
    df = _long_setup_frame()
    setup_idx = len(df) - 2
    df.loc[setup_idx, "volume"] = 50_000  # half of avg → fails 1.2x ratio
    sig = FiveEMAGenerator().detect_latest(df, "TEST")
    assert sig is None


# ── Short setup ─────────────────────────────────────────────


def test_short_setup_with_above_ema_and_breakdown():
    """SHORT: setup candle's low > EMA5 AND current bar's low < setup low."""
    df = _short_setup_frame()
    sig = FiveEMAGenerator().detect_latest(df, "TEST")
    assert sig is not None
    assert sig.direction == "SHORT"
    # Entry = setup_low = 189.5; stop = setup_high = 191.0; risk = 1.50
    assert sig.entry == Decimal("189.50")
    assert sig.stop_loss == Decimal("191.00")
    assert sig.target == Decimal("186.50")  # 189.50 - 2*1.50 = 186.50


# ── Backtester adapter ──────────────────────────────────────


def test_backtester_adapter_returns_dict_shape():
    df = _long_setup_frame()
    out = generate_signals_for_backtest(df, "TEST", capital=100_000)
    assert len(out) >= 1
    sig = out[-1]
    # Shape parity with _generate_rrms_signals — backtester._simulate_trades
    # needs these exact keys.
    for k in ("bar_idx", "direction", "entry", "stop_loss", "target", "qty",
              "source", "confidence"):
        assert k in sig
    # Money fields are float at the boundary so float-slippage math doesn't error
    for k in ("entry", "stop_loss", "target"):
        assert isinstance(sig[k], float)
    assert sig["source"] == "pos_5ema"
    assert sig["qty"] >= 1


def test_backtester_adapter_position_size_respects_1pct_risk():
    df = _long_setup_frame()  # setup risk per share = 1.50 (110.50 → 109.00)
    capital = 100_000
    out = generate_signals_for_backtest(df, "TEST", capital=capital)
    assert out, "Adapter should produce at least one signal here"
    # 1% of 100k = 1000 risk-rupees. Per-share risk = 1.50. Qty ≈ 666.
    assert out[-1]["qty"] in range(600, 700)


# ── End-to-end via run_backtest ─────────────────────────────


def test_run_backtest_accepts_pos_5ema_strategy():
    from mcp_server.backtester import run_backtest

    result = run_backtest("RELIANCE", strategy="pos_5ema", days=30)
    assert isinstance(result, dict)
    assert result["strategy"] == "pos_5ema"


def test_run_backtest_all_strategies_includes_pos_5ema():
    from mcp_server.backtester import run_backtest_all_strategies

    result = run_backtest_all_strategies("RELIANCE", days=30)
    strats = [s.get("strategy") for s in result.get("comparison", [])]
    assert "pos_5ema" in strats


# ── Confidence scoring ─────────────────────────────────────


def test_confidence_in_unit_interval():
    df = _long_setup_frame()
    sig = FiveEMAGenerator().detect_latest(df, "TEST")
    assert sig is not None
    assert 0.0 < sig.confidence <= 1.0
