"""Tests for mcp_server.regime_detector — ADX classification + strategy gates."""

import numpy as np
import pandas as pd

from mcp_server.regime_detector import (
    DEFAULT_ADX_TRENDING,
    DEFAULT_ATR_VOLATILE_PCT,
    STRATEGY_GATES,
    MarketRegime,
    classify,
    classify_from_df,
    gate_strategy,
)


# ── Frame builders ────────────────────────────────────────────


def _flat_frame(n: int = 80, price: float = 100.0) -> pd.DataFrame:
    """Completely flat price — ADX should be near zero (RANGING)."""
    return pd.DataFrame({
        "high":   [price + 0.1] * n,
        "low":    [price - 0.1] * n,
        "close":  [price] * n,
        "volume": [100_000] * n,
    })


def _trending_up_frame(n: int = 80, start: float = 100.0, step: float = 0.5) -> pd.DataFrame:
    """Steady uptrend — ADX should climb, +DI > −DI."""
    closes = [start + i * step for i in range(n)]
    return pd.DataFrame({
        "high":   [c + 0.3 for c in closes],
        "low":    [c - 0.3 for c in closes],
        "close":  closes,
        "volume": [100_000] * n,
    })


def _trending_down_frame(n: int = 80, start: float = 200.0, step: float = 0.5) -> pd.DataFrame:
    closes = [start - i * step for i in range(n)]
    return pd.DataFrame({
        "high":   [c + 0.3 for c in closes],
        "low":    [c - 0.3 for c in closes],
        "close":  closes,
        "volume": [100_000] * n,
    })


def _volatile_frame(n: int = 80, base: float = 100.0) -> pd.DataFrame:
    """Wide daily ranges — ATR% should breach the volatile threshold."""
    rng = np.random.default_rng(seed=99)
    closes = base + np.cumsum(rng.normal(0, 2, n))
    return pd.DataFrame({
        "high":   closes + rng.uniform(3.5, 5, n),   # ATR% ≈ 4–5%
        "low":    closes - rng.uniform(3.5, 5, n),
        "close":  closes,
        "volume": [200_000] * n,
    })


# ── classify() — numpy arrays ─────────────────────────────────


def test_flat_market_is_ranging():
    df = _flat_frame(80)
    regime = classify(
        df["high"].values, df["low"].values, df["close"].values,
    )
    assert regime.label == "RANGING"


def test_trending_up_detected():
    df = _trending_up_frame(80)
    regime = classify(
        df["high"].values, df["low"].values, df["close"].values,
    )
    assert regime.label == "TRENDING_UP"
    assert regime.plus_di >= regime.minus_di


def test_trending_down_detected():
    df = _trending_down_frame(80)
    regime = classify(
        df["high"].values, df["low"].values, df["close"].values,
    )
    assert regime.label == "TRENDING_DOWN"
    assert regime.minus_di >= regime.plus_di


def test_volatile_overrides_trending():
    df = _volatile_frame(80)
    regime = classify(
        df["high"].values, df["low"].values, df["close"].values,
        atr_volatile_pct=3.0,
    )
    assert regime.label == "VOLATILE"


def test_short_frame_returns_ranging():
    regime = classify(
        np.array([100.0, 101.0]),
        np.array([99.0, 100.0]),
        np.array([100.0, 100.5]),
    )
    assert regime.label == "RANGING"
    assert regime.bars_used == 2


# ── classify_from_df() — DataFrame API ───────────────────────


def test_classify_from_df_trending_up():
    df = _trending_up_frame(80)
    regime = classify_from_df(df)
    assert regime.label == "TRENDING_UP"


def test_classify_from_df_missing_columns():
    bad = pd.DataFrame({"close": [100] * 80})
    regime = classify_from_df(bad)
    assert regime.label == "RANGING"
    assert regime.bars_used == 0


def test_classify_from_df_respects_lookback():
    # Frame is long but only recent bars matter
    df = _flat_frame(200)
    regime = classify_from_df(df, lookback=50)
    assert regime.bars_used <= 50
    assert regime.label == "RANGING"


# ── MarketRegime helpers ──────────────────────────────────────


def test_is_trending_true_for_trending_labels():
    for label in ("TRENDING_UP", "TRENDING_DOWN"):
        r = MarketRegime(label=label, adx=30, plus_di=20, minus_di=10,
                         atr_pct=1.0, trend_strength="MODERATE", bars_used=60)
        assert r.is_trending() is True


def test_is_ranging():
    r = MarketRegime(label="RANGING", adx=15, plus_di=10, minus_di=12,
                     atr_pct=1.0, trend_strength="WEAK", bars_used=60)
    assert r.is_ranging() is True
    assert r.is_trending() is False


def test_is_volatile():
    r = MarketRegime(label="VOLATILE", adx=10, plus_di=8, minus_di=9,
                     atr_pct=4.5, trend_strength="VOLATILE", bars_used=60)
    assert r.is_volatile() is True


def test_as_dict_keys():
    df = _trending_up_frame(80)
    regime = classify_from_df(df)
    d = regime.as_dict()
    for k in ("regime", "adx", "plus_di", "minus_di", "atr_pct", "trend_strength", "bars_used"):
        assert k in d


# ── Strategy gate ─────────────────────────────────────────────


def test_pos_5ema_allowed_in_trending():
    df = _trending_up_frame(80)
    allowed, regime = gate_strategy(df, "pos_5ema")
    assert regime.label == "TRENDING_UP"
    assert allowed is True


def test_pos_5ema_blocked_in_ranging():
    df = _flat_frame(80)
    allowed, regime = gate_strategy(df, "pos_5ema")
    assert regime.label == "RANGING"
    assert allowed is False


def test_pos_5ema_blocked_in_volatile():
    df = _volatile_frame(80)
    allowed, regime = gate_strategy(df, "pos_5ema", atr_volatile_pct=3.0)
    assert regime.label == "VOLATILE"
    assert allowed is False


def test_options_seller_allowed_in_ranging():
    df = _flat_frame(80)
    allowed, _ = gate_strategy(df, "options_seller")
    assert allowed is True


def test_options_seller_blocked_in_trending():
    df = _trending_up_frame(80)
    allowed, _ = gate_strategy(df, "options_seller")
    assert allowed is False


def test_unknown_strategy_is_permissive():
    df = _volatile_frame(80)
    allowed, _ = gate_strategy(df, "some_new_strategy_not_in_gates")
    assert allowed is True


def test_override_allowed_regimes_wins():
    df = _flat_frame(80)  # RANGING by default
    # POS 5 EMA gate would block RANGING, but caller overrides
    allowed, _ = gate_strategy(
        df, "pos_5ema",
        allowed_regimes=frozenset({"RANGING"}),
    )
    assert allowed is True


# ── STRATEGY_GATES completeness ───────────────────────────────


def test_strategy_gates_have_valid_labels():
    valid = {"TRENDING_UP", "TRENDING_DOWN", "RANGING", "VOLATILE"}
    for strategy, gate in STRATEGY_GATES.items():
        for label in gate:
            assert label in valid, f"{strategy} gate has unknown label: {label}"


def test_pos_5ema_gate_contains_both_trend_labels():
    gate = STRATEGY_GATES["pos_5ema"]
    assert "TRENDING_UP" in gate
    assert "TRENDING_DOWN" in gate
    assert "RANGING" not in gate
    assert "VOLATILE" not in gate


def test_options_seller_gate_is_ranging_only():
    assert STRATEGY_GATES["options_seller"] == frozenset({"RANGING"})


# ── ADX constant sanity ───────────────────────────────────────


def test_default_adx_trending_is_25():
    assert DEFAULT_ADX_TRENDING == 25.0


def test_default_atr_volatile_pct_is_3():
    assert DEFAULT_ATR_VOLATILE_PCT == 3.0
