"""
Volatility Normalization Utilities for MKUMARAN Trading OS.

Provides ATR-based dynamic thresholds that adapt to each instrument's
volatility regime. Used by all 5 pattern engines to replace hardcoded
percentage thresholds.

Key principle: A 3% move in a Rs.10 stock (Rs.0.30) means something
very different from a 3% move in a Rs.5000 stock (Rs.150). ATR-based
thresholds normalize this automatically.
"""

import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """
    Calculate Average True Range (ATR) for the given OHLCV data.

    Returns the latest ATR value as a float.
    Returns 0.0 if insufficient data.
    """
    if len(df) < period + 1:
        # Fallback: use average high-low range
        if len(df) >= 2:
            return float((df["high"] - df["low"]).mean())
        return 0.0

    high = df["high"].values
    low = df["low"].values
    close = df["close"].values

    tr = np.zeros(len(df))
    tr[0] = high[0] - low[0]

    for i in range(1, len(df)):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )

    # Wilder's smoothed ATR
    atr = np.zeros(len(df))
    atr[period] = np.mean(tr[1:period + 1])
    for i in range(period + 1, len(df)):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    return float(atr[-1])


def calculate_atr_pct(df: pd.DataFrame, period: int = 14) -> float:
    """
    Calculate ATR as a percentage of the current price.

    Returns ATR / close * 100.
    A Rs.100 stock with ATR of 3 = 3%.
    A Rs.5000 stock with ATR of 150 = 3%.

    This is the primary normalization metric.
    """
    atr = calculate_atr(df, period)
    current_price = float(df["close"].iloc[-1]) if len(df) > 0 else 1.0
    if current_price <= 0:
        return 0.0
    return atr / current_price * 100


def get_volatility_regime(df: pd.DataFrame, period: int = 14) -> str:
    """
    Classify current volatility regime.

    LOW:    ATR% < 1.5% — tight range, small moves
    NORMAL: ATR% 1.5-3.5% — standard trading range
    HIGH:   ATR% 3.5-6% — elevated volatility
    EXTREME: ATR% > 6% — crisis / event-driven
    """
    atr_pct = calculate_atr_pct(df, period)

    if atr_pct < 1.5:
        return "LOW"
    elif atr_pct < 3.5:
        return "NORMAL"
    elif atr_pct < 6.0:
        return "HIGH"
    else:
        return "EXTREME"


# ── Dynamic Threshold Scaling ────────────────────────────────

def scaled_tolerance(
    df: pd.DataFrame,
    base_tolerance: float = 0.03,
    period: int = 14,
) -> float:
    """
    Scale a percentage tolerance by the instrument's volatility.

    Example:
        base_tolerance = 0.03 (3%)
        Low-vol stock (ATR% = 1%) → scaled to 0.015 (1.5%)
        Normal stock (ATR% = 3%) → stays at 0.03 (3%)
        High-vol stock (ATR% = 6%) → scaled to 0.06 (6%)

    This prevents:
    - False positives on low-vol stocks (too loose threshold)
    - Missed patterns on high-vol stocks (too tight threshold)
    """
    atr_pct = calculate_atr_pct(df, period)

    # Normalize around 3% ATR as "standard"
    # scale_factor = atr_pct / 3.0, clamped to [0.5, 2.5]
    if atr_pct <= 0:
        return base_tolerance

    scale_factor = max(0.5, min(2.5, atr_pct / 3.0))
    return base_tolerance * scale_factor


def scaled_spread_ratio(
    df: pd.DataFrame,
    base_ratio: float = 0.7,
    period: int = 14,
) -> float:
    """
    Scale a spread ratio threshold by volatility.

    Used for VSA: narrow bar / wide bar detection.
    In low-vol regimes, bars are naturally narrower, so threshold adjusts.
    """
    atr_pct = calculate_atr_pct(df, period)
    if atr_pct <= 0:
        return base_ratio

    scale_factor = max(0.6, min(1.5, atr_pct / 3.0))
    return base_ratio * scale_factor


def atr_distance(
    df: pd.DataFrame,
    atr_multiplier: float = 1.0,
    period: int = 14,
) -> float:
    """
    Get a price distance based on ATR.

    Use instead of fixed percentage distances.
    Example: atr_distance(df, 1.5) = 1.5x ATR in price terms.
    """
    atr = calculate_atr(df, period)
    return atr * atr_multiplier


def zigzag_threshold(df: pd.DataFrame, period: int = 14) -> float:
    """
    Dynamic zigzag threshold based on volatility.

    Low-vol: 1.5% minimum reversal
    Normal: 3% reversal
    High-vol: 5% reversal
    Extreme: 7% reversal

    This prevents:
    - Too many zigzag points on noisy low-vol stocks
    - Missing real reversals on high-vol stocks
    """
    atr_pct = calculate_atr_pct(df, period)

    if atr_pct < 1.5:
        return 1.5
    elif atr_pct < 3.5:
        return atr_pct  # Use ATR% directly
    elif atr_pct < 6.0:
        return min(atr_pct, 5.0)
    else:
        return 7.0
