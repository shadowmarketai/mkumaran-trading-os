"""
MKUMARAN Trading OS — Market Regime Detector

Classifies the market environment on each bar so that strategies can
self-gate: momentum strategies (POS 5 EMA) avoid ranging markets;
options sellers avoid extreme-volatility events; confluence scoring
can tilt weights by regime.

Regime taxonomy
───────────────
  TRENDING_UP     ADX ≥ threshold AND +DI > −DI
  TRENDING_DOWN   ADX ≥ threshold AND −DI > +DI
  RANGING         ADX < threshold AND intraday vol within normal band
  VOLATILE        ATR% above spike threshold (event / panic)

Strategy gates (defaults, tunable via caller kwargs)
──────────────────────────────────────────────────────
  POS 5 EMA       → allow TRENDING_UP | TRENDING_DOWN; block RANGING + VOLATILE
  Options seller  → allow RANGING; block TRENDING (IV too low / directional risk)
                    block VOLATILE (IV crushed OR event gap risk)
  Any strategy    → caller passes its own `allowed_regimes` set

Design notes
────────────
  - Wraps the existing `indicators.adx()` function so there is exactly
    one ADX implementation in the codebase.
  - Stateless — every call is a full computation on the supplied frame.
    Callers cache the result if they need it across multiple strategies.
  - Returns a `MarketRegime` dataclass whose `.label` matches the four
    strings already in models.Signal.entry_regime.
  - `classify_from_df()` is the primary API; it accepts any OHLCV
    DataFrame (must have high, low, close columns).
  - All float arithmetic; no Decimal (analysis zone, not money zone).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ── Regime labels — must match models.Signal.entry_regime comment ──
RegimeLabel = Literal["TRENDING_UP", "TRENDING_DOWN", "RANGING", "VOLATILE"]

# ── Default thresholds (tune via backtest) ──────────────────────────
DEFAULT_ADX_PERIOD = 14
DEFAULT_ADX_TRENDING = 25.0     # ADX ≥ 25 → trending (Wilder's standard)
DEFAULT_ADX_STRONG = 40.0       # ADX ≥ 40 → strong trend
DEFAULT_ATR_VOLATILE_PCT = 3.0  # ATR as % of close → volatile if above this
DEFAULT_LOOKBACK = 50           # bars needed for a reliable read

# ── Strategy gate map (allowed regimes per strategy) ───────────────
STRATEGY_GATES: dict[str, frozenset[RegimeLabel]] = {
    "pos_5ema":        frozenset({"TRENDING_UP", "TRENDING_DOWN"}),
    "rrms":            frozenset({"TRENDING_UP", "TRENDING_DOWN"}),
    "smc":             frozenset({"TRENDING_UP", "TRENDING_DOWN", "RANGING"}),
    "wyckoff":         frozenset({"RANGING"}),           # Wyckoff excels in accumulation
    "vsa":             frozenset({"TRENDING_UP", "TRENDING_DOWN", "RANGING"}),
    "harmonic":        frozenset({"RANGING", "VOLATILE"}),  # harmonic setups at extremes
    "options_seller":  frozenset({"RANGING"}),           # sell premium in low-ADX
    "iron_condor":     frozenset({"RANGING"}),
    "confluence":      frozenset({"TRENDING_UP", "TRENDING_DOWN", "RANGING"}),
}


@dataclass
class MarketRegime:
    """Output of one regime classification."""

    label: RegimeLabel
    adx: float
    plus_di: float
    minus_di: float
    atr_pct: float          # ATR as % of last close
    trend_strength: str     # "WEAK" | "MODERATE" | "STRONG" | "VOLATILE"
    bars_used: int

    # ── Convenience helpers ──────────────────────────────────────

    def is_trending(self) -> bool:
        return self.label in ("TRENDING_UP", "TRENDING_DOWN")

    def is_ranging(self) -> bool:
        return self.label == "RANGING"

    def is_volatile(self) -> bool:
        return self.label == "VOLATILE"

    def allows_strategy(self, strategy: str) -> bool:
        """Return True if the strategy's gate permits this regime.

        Falls back to True for unknown strategy names (opt-out model
        — unknown strategies see all regimes; add explicit gates above
        to restrict).
        """
        gate = STRATEGY_GATES.get(strategy)
        if gate is None:
            return True
        return self.label in gate

    def as_dict(self) -> dict:
        return {
            "regime": self.label,
            "adx": round(self.adx, 2),
            "plus_di": round(self.plus_di, 2),
            "minus_di": round(self.minus_di, 2),
            "atr_pct": round(self.atr_pct, 2),
            "trend_strength": self.trend_strength,
            "bars_used": self.bars_used,
        }


# ── ADX computation (wraps indicators.adx) ─────────────────────────


def _compute_adx_components(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    period: int,
) -> tuple[float, float, float]:
    """Return (adx_val, plus_di, minus_di) for the latest bar.

    Uses the same pure-numpy ADX as indicators.adx() but also extracts
    the +DI and −DI components for directional bias.
    """
    from mcp_server.agents.skills.indicators import adx as _adx

    # indicators.adx returns the smoothed ADX array
    adx_arr = _adx(high, low, close, period)
    adx_val = float(adx_arr[-1]) if len(adx_arr) else 0.0

    # Recompute +DI / −DI for the same window (share the TR math)
    n = len(close)
    if n < period + 2:
        return adx_val, 0.0, 0.0

    tr = np.maximum(high[1:] - low[1:], np.abs(high[1:] - close[:-1]))
    tr = np.maximum(tr, np.abs(low[1:] - close[:-1]))

    plus_dm = np.where(
        (high[1:] - high[:-1]) > (low[:-1] - low[1:]),
        np.maximum(high[1:] - high[:-1], 0.0),
        0.0,
    )
    minus_dm = np.where(
        (low[:-1] - low[1:]) > (high[1:] - high[:-1]),
        np.maximum(low[:-1] - low[1:], 0.0),
        0.0,
    )

    atr_roll = np.convolve(tr, np.ones(period) / period, mode="valid")
    plus_di_arr = (
        np.convolve(plus_dm, np.ones(period) / period, mode="valid")
        / np.where(atr_roll > 0, atr_roll, 1.0)
        * 100
    )
    minus_di_arr = (
        np.convolve(minus_dm, np.ones(period) / period, mode="valid")
        / np.where(atr_roll > 0, atr_roll, 1.0)
        * 100
    )

    plus_di = float(plus_di_arr[-1]) if len(plus_di_arr) else 0.0
    minus_di = float(minus_di_arr[-1]) if len(minus_di_arr) else 0.0
    return adx_val, plus_di, minus_di


def _atr_pct(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> float:
    """ATR as a percentage of last close — volatility proxy."""
    if len(close) < period + 1:
        return 0.0
    tr = np.maximum(high[1:] - low[1:], np.abs(high[1:] - close[:-1]))
    tr = np.maximum(tr, np.abs(low[1:] - close[:-1]))
    atr_val = float(np.mean(tr[-period:]))
    last_close = float(close[-1])
    return (atr_val / last_close * 100) if last_close > 0 else 0.0


# ── Classifier ─────────────────────────────────────────────────────


def classify(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    adx_period: int = DEFAULT_ADX_PERIOD,
    adx_trending: float = DEFAULT_ADX_TRENDING,
    adx_strong: float = DEFAULT_ADX_STRONG,
    atr_volatile_pct: float = DEFAULT_ATR_VOLATILE_PCT,
) -> MarketRegime:
    """Classify the latest bar's regime from OHLC arrays.

    Priority order:
      1. VOLATILE  — ATR% > spike threshold (overrides ADX)
      2. TRENDING  — ADX ≥ trending threshold (+DI vs −DI for direction)
      3. RANGING   — everything else
    """
    bars_used = len(close)

    if bars_used < adx_period + 2:
        return MarketRegime(
            label="RANGING",
            adx=0.0,
            plus_di=0.0,
            minus_di=0.0,
            atr_pct=0.0,
            trend_strength="WEAK",
            bars_used=bars_used,
        )

    adx_val, plus_di, minus_di = _compute_adx_components(high, low, close, adx_period)
    atr_p = _atr_pct(high, low, close, adx_period)

    # 1. Volatile check first — panic/event overrides trend state
    if atr_p >= atr_volatile_pct:
        label: RegimeLabel = "VOLATILE"
        strength = "VOLATILE"

    # 2. ADX trend check
    elif adx_val >= adx_trending:
        label = "TRENDING_UP" if plus_di >= minus_di else "TRENDING_DOWN"
        strength = "STRONG" if adx_val >= adx_strong else "MODERATE"

    # 3. Default: ranging
    else:
        label = "RANGING"
        strength = "WEAK" if adx_val < 15 else "MODERATE"

    return MarketRegime(
        label=label,
        adx=adx_val,
        plus_di=plus_di,
        minus_di=minus_di,
        atr_pct=atr_p,
        trend_strength=strength,
        bars_used=bars_used,
    )


def classify_from_df(
    df: pd.DataFrame,
    adx_period: int = DEFAULT_ADX_PERIOD,
    adx_trending: float = DEFAULT_ADX_TRENDING,
    adx_strong: float = DEFAULT_ADX_STRONG,
    atr_volatile_pct: float = DEFAULT_ATR_VOLATILE_PCT,
    lookback: int = DEFAULT_LOOKBACK,
) -> MarketRegime:
    """Classify regime from a pandas OHLCV DataFrame.

    Uses the last `lookback` bars to keep computation bounded when
    called on a long historical frame.

    Required columns: high, low, close.
    """
    required = {"high", "low", "close"}
    if not required.issubset(df.columns):
        logger.debug("regime_detector: missing columns %s", required - set(df.columns))
        return MarketRegime(
            label="RANGING", adx=0.0, plus_di=0.0, minus_di=0.0,
            atr_pct=0.0, trend_strength="WEAK", bars_used=0,
        )

    window = df.tail(lookback) if len(df) > lookback else df
    high = window["high"].values.astype(float)
    low = window["low"].values.astype(float)
    close = window["close"].values.astype(float)

    return classify(
        high, low, close,
        adx_period=adx_period,
        adx_trending=adx_trending,
        adx_strong=adx_strong,
        atr_volatile_pct=atr_volatile_pct,
    )


# ── Strategy gate helper ────────────────────────────────────────────


def gate_strategy(
    df: pd.DataFrame,
    strategy: str,
    allowed_regimes: frozenset[RegimeLabel] | None = None,
    **classify_kwargs,
) -> tuple[bool, MarketRegime]:
    """Return (allowed, regime).

    If `allowed_regimes` is provided, it overrides the STRATEGY_GATES
    default for this call (useful for A/B testing thresholds without
    editing the module-level dict).
    """
    regime = classify_from_df(df, **classify_kwargs)
    if allowed_regimes is not None:
        allowed = regime.label in allowed_regimes
    else:
        allowed = regime.allows_strategy(strategy)

    if not allowed:
        logger.debug(
            "regime_detector: strategy=%s BLOCKED in regime=%s (adx=%.1f)",
            strategy, regime.label, regime.adx,
        )
    return allowed, regime
