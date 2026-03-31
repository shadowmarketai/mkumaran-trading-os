import logging
import pandas as pd

logger = logging.getLogger(__name__)

def find_swing_low(df: pd.DataFrame, lookback: int = 20) -> float:
    """
    Find the most recent swing low (LTRP) from OHLCV data.
    A swing low is a bar whose low is lower than the N bars before and after it.

    Args:
        df: DataFrame with 'low' column, sorted by date ascending
        lookback: Number of bars to look back for swing detection

    Returns:
        The most recent swing low price, or 0.0 if none found
    """
    if len(df) < lookback * 2:
        logger.warning("Insufficient data for swing detection: %d bars", len(df))
        return 0.0

    lows = df['low'].values
    swing_lows: list[float] = []

    for i in range(lookback, len(lows) - lookback):
        is_swing = True
        for j in range(1, lookback + 1):
            if lows[i] > lows[i - j] or lows[i] > lows[i + j]:
                is_swing = False
                break
        if is_swing:
            swing_lows.append(lows[i])

    if not swing_lows:
        # Fallback: use the minimum of the last N bars
        recent_low = float(df['low'].tail(lookback).min())
        logger.info("No swing low found, using recent minimum: %.2f", recent_low)
        return recent_low

    return swing_lows[-1]


def find_swing_high(df: pd.DataFrame, lookback: int = 20) -> float:
    """
    Find the most recent swing high (Pivot High) from OHLCV data.
    A swing high is a bar whose high is higher than the N bars before and after it.

    Args:
        df: DataFrame with 'high' column, sorted by date ascending
        lookback: Number of bars to look back for swing detection

    Returns:
        The most recent swing high price, or 0.0 if none found
    """
    if len(df) < lookback * 2:
        logger.warning("Insufficient data for swing detection: %d bars", len(df))
        return 0.0

    highs = df['high'].values
    swing_highs: list[float] = []

    for i in range(lookback, len(highs) - lookback):
        is_swing = True
        for j in range(1, lookback + 1):
            if highs[i] < highs[i - j] or highs[i] < highs[i + j]:
                is_swing = False
                break
        if is_swing:
            swing_highs.append(highs[i])

    if not swing_highs:
        recent_high = float(df['high'].tail(lookback).max())
        logger.info("No swing high found, using recent maximum: %.2f", recent_high)
        return recent_high

    return swing_highs[-1]


def auto_detect_levels(df: pd.DataFrame, lookback: int = 20) -> dict[str, float]:
    """
    Auto-detect both LTRP and Pivot High from OHLCV data.

    Returns:
        Dict with 'ltrp' and 'pivot_high' keys
    """
    ltrp = find_swing_low(df, lookback)
    pivot_high = find_swing_high(df, lookback)

    logger.info("Auto-detected levels - LTRP: %.2f, Pivot High: %.2f", ltrp, pivot_high)

    return {
        "ltrp": ltrp,
        "pivot_high": pivot_high,
    }
