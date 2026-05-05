import logging
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional

from mcp_server.volatility import scaled_tolerance, calculate_atr_pct

logger = logging.getLogger(__name__)


# ── Utility functions (adapted from Vibe-Trading, MIT License) ──────────────
# Source: https://github.com/HKUDS/Vibe-Trading (agent/src/tools/pattern_tool.py)

def find_support_resistance(
    close: pd.Series,
    window: int = 20,
    num_levels: int = 3,
) -> dict:
    """Identify support and resistance levels via peak/valley price clustering.

    Returns dict with 'support' and 'resistance' as lists of price levels,
    sorted by cluster size (most-tested levels first).
    """
    n = len(close)
    if n < 2 * window + 1:
        return {"support": [], "resistance": []}

    values = close.values.astype(float)
    peaks, valleys = [], []

    for i in range(window, n - window):
        seg = values[i - window: i + window + 1]
        seg = seg[~np.isnan(seg)]
        if len(seg) == 0 or np.isnan(values[i]):
            continue
        if values[i] == np.max(seg):
            peaks.append(float(values[i]))
        if values[i] == np.min(seg):
            valleys.append(float(values[i]))

    def cluster(prices: list, n_clusters: int) -> list:
        if not prices:
            return []
        sp = sorted(prices)
        if len(sp) <= n_clusters:
            return sp
        clusters: list[list[float]] = [[sp[0]]]
        rng = sp[-1] - sp[0]
        thr = rng * 0.05 if rng > 0 else 1.0
        for p in sp[1:]:
            if abs(p - float(np.mean(clusters[-1]))) <= thr:
                clusters[-1].append(p)
            else:
                clusters.append([p])
        centers = [(len(c), float(np.mean(c))) for c in clusters]
        centers.sort(reverse=True)
        return [c for _, c in centers[:n_clusters]]

    return {
        "support": cluster(valleys, num_levels),
        "resistance": cluster(peaks, num_levels),
    }


def detect_candlestick_signals(
    open_: pd.Series,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
) -> pd.Series:
    """Classify each bar as bullish (+1), bearish (-1), or neutral (0).

    Detects: doji (indecision), hammer (bullish reversal), bullish/bearish engulfing.
    Returns a Series aligned to the close index.
    """
    body = (close - open_).abs()
    total_range = high - low
    upper_shadow = high - pd.concat([open_, close], axis=1).max(axis=1)
    lower_shadow = pd.concat([open_, close], axis=1).min(axis=1) - low

    result = pd.Series(0, index=close.index, dtype=int)

    safe_range = total_range.replace(0, np.nan)
    is_doji = (body / safe_range) < 0.10

    is_hammer = (lower_shadow > 2 * body) & (upper_shadow < body) & ~is_doji
    result = result.where(~is_hammer, 1)

    prev_bearish = close.shift(1) < open_.shift(1)
    curr_bullish = close > open_
    engulf_bull = (
        prev_bearish & curr_bullish
        & (open_ <= close.shift(1))
        & (close >= open_.shift(1))
        & (body > body.shift(1))
    )
    result = result.where(~engulf_bull, 1)

    prev_bullish = close.shift(1) > open_.shift(1)
    curr_bearish = close < open_
    engulf_bear = (
        prev_bullish & curr_bearish
        & (open_ >= close.shift(1))
        & (close <= open_.shift(1))
        & (body > body.shift(1))
    )
    result = result.where(~engulf_bear, -1)

    return result


def rolling_trend_slope(close: pd.Series, window: int = 20) -> pd.Series:
    """Compute rolling linear-regression slope over a price series.

    Positive values indicate uptrend; negative indicate downtrend.
    First window-1 entries are NaN.
    """
    n = len(close)
    slopes = np.full(n, np.nan)
    values = close.values.astype(float)
    x = np.arange(window, dtype=float)

    for i in range(window - 1, n):
        seg = values[i - window + 1: i + 1]
        if np.any(np.isnan(seg)):
            continue
        slopes[i] = np.polyfit(x, seg, 1)[0]

    return pd.Series(slopes, index=close.index)


@dataclass
class PatternResult:
    """Result of pattern detection."""
    name: str
    direction: str  # BULLISH, BEARISH, CONTINUATION
    confidence: float  # 0.0 - 1.0
    description: str


class PatternEngine:
    """
    Detects 12 price patterns from OHLCV data.

    Bottom Reversals (BULLISH):
    1. Double Bottom
    2. Triple Bottom
    3. Rounded Bottom
    4. Inverse Head & Shoulders
    5. Falling Wedge

    Top Reversals (BEARISH):
    6. Double Top
    7. Triple Top
    8. Rounded Top
    9. Head & Shoulders
    10. Rising Wedge

    Continuation:
    11. Symmetrical/Ascending/Descending Triangle
    12. Flag/Rectangle
    13. Broadening / Megaphone
    """

    def __init__(self, lookback: int = 60):
        self.lookback = lookback
        self.df_full = None

    def detect_all(self, df: pd.DataFrame) -> list[PatternResult]:
        """Run all pattern detectors and return matches."""
        if len(df) < self.lookback:
            logger.warning("Insufficient data for pattern detection: %d bars", len(df))
            return []

        self.df_full = df
        data = df.tail(self.lookback).copy()
        patterns: list[PatternResult] = []

        detectors = [
            self._detect_double_bottom,
            self._detect_triple_bottom,
            self._detect_rounded_bottom,
            self._detect_inverse_head_shoulders,
            self._detect_falling_wedge,
            self._detect_double_top,
            self._detect_triple_top,
            self._detect_rounded_top,
            self._detect_head_shoulders,
            self._detect_rising_wedge,
            self._detect_triangle,
            self._detect_flag_rectangle,
            self._detect_broadening,
        ]

        for detector in detectors:
            try:
                result = detector(data)
                if result is not None:
                    patterns.append(result)
            except Exception as e:
                logger.error("Pattern detector %s failed: %s", detector.__name__, e)

        if patterns:
            logger.info("Detected %d patterns: %s", len(patterns), [p.name for p in patterns])

        return patterns

    def _tol(self, base=0.03):
        return scaled_tolerance(self.df_full, base) if self.df_full is not None and len(self.df_full) > 15 else base

    def _slope_threshold(self):
        atr_pct = calculate_atr_pct(self.df_full) if self.df_full is not None and len(self.df_full) > 15 else 3.0
        return max(0.05, atr_pct / 100 * 2)

    def _detect_double_bottom(self, df: pd.DataFrame) -> PatternResult | None:
        """Detect Double Bottom: two roughly equal lows with a peak between."""
        lows = df['low'].values
        n = len(lows)
        third = n // 3

        # Find low in first third and last third
        first_low_idx = np.argmin(lows[:third])
        first_low = lows[first_low_idx]

        last_low_idx = np.argmin(lows[2 * third:]) + 2 * third
        last_low = lows[last_low_idx]

        # Peak between them
        mid_start = max(first_low_idx + 1, third)
        mid_end = min(last_low_idx, 2 * third)
        if mid_start >= mid_end:
            return None

        mid_high = np.max(df['high'].values[mid_start:mid_end])

        # Lows should be within tolerance of each other
        tolerance = self._tol(0.03)
        if abs(first_low - last_low) / max(first_low, 1) > tolerance:
            return None

        # Peak should be significantly higher than lows
        if mid_high < first_low * (1 + self._tol(0.03)):
            return None

        # Current price should be rising from second low
        if df['close'].iloc[-1] > last_low * (1 + self._tol(0.01)):
            confidence = min(1.0, (mid_high - first_low) / max(first_low, 1) * 5)
            return PatternResult(
                name="Double Bottom",
                direction="BULLISH",
                confidence=round(confidence, 2),
                description=f"Two lows near {first_low:.2f}/{last_low:.2f} with peak at {mid_high:.2f}",
            )
        return None

    def _detect_triple_bottom(self, df: pd.DataFrame) -> PatternResult | None:
        """Detect Triple Bottom: three roughly equal lows."""
        lows = df['low'].values
        n = len(lows)
        quarter = n // 4

        low1 = np.min(lows[:quarter])
        low2 = np.min(lows[quarter:2*quarter])
        low3 = np.min(lows[2*quarter:3*quarter])

        avg_low = (low1 + low2 + low3) / 3
        tolerance = self._tol(0.03)

        if all(abs(val - avg_low) / max(avg_low, 1) < tolerance for val in [low1, low2, low3]):
            if df['close'].iloc[-1] > avg_low * (1 + self._tol(0.02)):
                return PatternResult(
                    name="Triple Bottom",
                    direction="BULLISH",
                    confidence=0.75,
                    description=f"Three lows near {avg_low:.2f}",
                )
        return None

    def _detect_rounded_bottom(self, df: pd.DataFrame) -> PatternResult | None:
        """Detect Rounded Bottom: U-shaped price action."""
        closes = df['close'].values
        n = len(closes)

        # Split into left half and right half
        mid = n // 2
        left_slope = np.polyfit(range(mid), closes[:mid], 1)[0]
        right_slope = np.polyfit(range(n - mid), closes[mid:], 1)[0]

        # Left side should be declining, right side rising
        if left_slope < -self._slope_threshold() and right_slope > self._slope_threshold():
            return PatternResult(
                name="Rounded Bottom",
                direction="BULLISH",
                confidence=0.65,
                description="U-shaped recovery pattern detected",
            )
        return None

    def _detect_inverse_head_shoulders(self, df: pd.DataFrame) -> PatternResult | None:
        """Detect Inverse H&S: three lows where middle is lowest."""
        lows = df['low'].values
        n = len(lows)
        third = n // 3

        left_shoulder = np.min(lows[:third])
        head = np.min(lows[third:2*third])
        right_shoulder = np.min(lows[2*third:])

        # Head must be the lowest
        if head >= left_shoulder or head >= right_shoulder:
            return None

        # Shoulders should be roughly equal (within tolerance)
        tolerance = self._tol(0.05)
        if abs(left_shoulder - right_shoulder) / max(left_shoulder, 1) > tolerance:
            return None

        # Head should be significantly lower
        if (left_shoulder - head) / max(left_shoulder, 1) > self._tol(0.02):
            return PatternResult(
                name="Inverse Head & Shoulders",
                direction="BULLISH",
                confidence=0.80,
                description=f"LS: {left_shoulder:.2f}, Head: {head:.2f}, RS: {right_shoulder:.2f}",
            )
        return None

    def _detect_falling_wedge(self, df: pd.DataFrame) -> PatternResult | None:
        """Detect Falling Wedge: converging downward trendlines."""
        highs = df['high'].values
        lows = df['low'].values
        x = np.arange(len(highs))

        high_slope = np.polyfit(x, highs, 1)[0]
        low_slope = np.polyfit(x, lows, 1)[0]

        # Both slopes negative but converging (low slope less negative)
        if high_slope < 0 and low_slope < 0 and low_slope > high_slope:
            return PatternResult(
                name="Falling Wedge",
                direction="BULLISH",
                confidence=0.70,
                description="Converging downward trendlines -- bullish breakout expected",
            )
        return None

    def _detect_double_top(self, df: pd.DataFrame) -> PatternResult | None:
        """Detect Double Top: two roughly equal highs."""
        highs = df['high'].values
        n = len(highs)
        third = n // 3

        first_high = np.max(highs[:third])
        last_high = np.max(highs[2*third:])
        mid_low = np.min(df['low'].values[third:2*third])

        tolerance = self._tol(0.03)
        if abs(first_high - last_high) / max(first_high, 1) > tolerance:
            return None

        if mid_low > first_high * (1 - self._tol(0.03)):
            return None

        if df['close'].iloc[-1] < last_high * (1 - self._tol(0.01)):
            confidence = min(1.0, (first_high - mid_low) / max(first_high, 1) * 5)
            return PatternResult(
                name="Double Top",
                direction="BEARISH",
                confidence=round(confidence, 2),
                description=f"Two highs near {first_high:.2f}/{last_high:.2f}",
            )
        return None

    def _detect_triple_top(self, df: pd.DataFrame) -> PatternResult | None:
        """Detect Triple Top: three roughly equal highs."""
        highs = df['high'].values
        n = len(highs)
        quarter = n // 4

        high1 = np.max(highs[:quarter])
        high2 = np.max(highs[quarter:2*quarter])
        high3 = np.max(highs[2*quarter:3*quarter])

        avg_high = (high1 + high2 + high3) / 3
        tolerance = self._tol(0.03)

        if all(abs(h - avg_high) / max(avg_high, 1) < tolerance for h in [high1, high2, high3]):
            if df['close'].iloc[-1] < avg_high * (1 - self._tol(0.02)):
                return PatternResult(
                    name="Triple Top",
                    direction="BEARISH",
                    confidence=0.75,
                    description=f"Three highs near {avg_high:.2f}",
                )
        return None

    def _detect_rounded_top(self, df: pd.DataFrame) -> PatternResult | None:
        """Detect Rounded Top: inverted U-shaped."""
        closes = df['close'].values
        n = len(closes)
        mid = n // 2

        left_slope = np.polyfit(range(mid), closes[:mid], 1)[0]
        right_slope = np.polyfit(range(n - mid), closes[mid:], 1)[0]

        if left_slope > self._slope_threshold() and right_slope < -self._slope_threshold():
            return PatternResult(
                name="Rounded Top",
                direction="BEARISH",
                confidence=0.65,
                description="Inverted U-shaped distribution pattern",
            )
        return None

    def _detect_head_shoulders(self, df: pd.DataFrame) -> PatternResult | None:
        """Detect Head & Shoulders: three highs where middle is highest."""
        highs = df['high'].values
        n = len(highs)
        third = n // 3

        left_shoulder = np.max(highs[:third])
        head = np.max(highs[third:2*third])
        right_shoulder = np.max(highs[2*third:])

        if head <= left_shoulder or head <= right_shoulder:
            return None

        tolerance = self._tol(0.05)
        if abs(left_shoulder - right_shoulder) / max(left_shoulder, 1) > tolerance:
            return None

        if (head - left_shoulder) / max(left_shoulder, 1) > self._tol(0.02):
            return PatternResult(
                name="Head & Shoulders",
                direction="BEARISH",
                confidence=0.80,
                description=f"LS: {left_shoulder:.2f}, Head: {head:.2f}, RS: {right_shoulder:.2f}",
            )
        return None

    def _detect_rising_wedge(self, df: pd.DataFrame) -> PatternResult | None:
        """Detect Rising Wedge: converging upward trendlines."""
        highs = df['high'].values
        lows = df['low'].values
        x = np.arange(len(highs))

        high_slope = np.polyfit(x, highs, 1)[0]
        low_slope = np.polyfit(x, lows, 1)[0]

        if high_slope > 0 and low_slope > 0 and low_slope > high_slope:
            return PatternResult(
                name="Rising Wedge",
                direction="BEARISH",
                confidence=0.70,
                description="Converging upward trendlines -- bearish breakdown expected",
            )
        return None

    def _detect_triangle(self, df: pd.DataFrame) -> PatternResult | None:
        """Detect Triangle patterns: symmetrical, ascending, or descending."""
        highs = df['high'].values
        lows = df['low'].values
        x = np.arange(len(highs))

        high_slope = np.polyfit(x, highs, 1)[0]
        low_slope = np.polyfit(x, lows, 1)[0]

        # Symmetrical: highs declining, lows rising (converging)
        if high_slope < -self._slope_threshold() and low_slope > self._slope_threshold():
            return PatternResult(
                name="Symmetrical Triangle",
                direction="CONTINUATION",
                confidence=0.65,
                description="Converging trendlines -- breakout direction uncertain",
            )

        # Ascending: flat highs, rising lows
        if abs(high_slope) < self._slope_threshold() and low_slope > self._slope_threshold():
            return PatternResult(
                name="Ascending Triangle",
                direction="BULLISH",
                confidence=0.72,
                description="Flat resistance with rising support -- bullish bias",
            )

        # Descending: flat lows, declining highs
        if high_slope < -self._slope_threshold() and abs(low_slope) < self._slope_threshold():
            return PatternResult(
                name="Descending Triangle",
                direction="BEARISH",
                confidence=0.72,
                description="Declining highs with flat support -- bearish bias",
            )

        return None

    def _detect_flag_rectangle(self, df: pd.DataFrame) -> PatternResult | None:
        """Detect Flag or Rectangle: consolidation after a strong move."""
        closes = df['close'].values
        n = len(closes)

        # Check first quarter for a strong move
        first_q = n // 4
        initial_move = (closes[first_q] - closes[0]) / max(abs(closes[0]), 1)

        # Rest should be consolidation (low volatility relative to the move)
        consolidation = closes[first_q:]
        cons_range = (np.max(consolidation) - np.min(consolidation)) / max(np.mean(consolidation), 1)

        if abs(initial_move) > self._tol(0.05) and cons_range < self._tol(0.05):
            direction = "BULLISH" if initial_move > 0 else "BEARISH"
            pattern_name = "Bull Flag" if initial_move > 0 else "Bear Flag"
            return PatternResult(
                name=pattern_name,
                direction=direction,
                confidence=0.68,
                description=f"Strong {'up' if initial_move > 0 else 'down'} move followed by tight consolidation",
            )

        return None

    def _detect_broadening(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """Detect Broadening (Megaphone): rising highs AND falling lows simultaneously.

        Signals increasing volatility and indecision — typically precedes sharp moves.
        Adapted from Vibe-Trading pattern_tool.py (MIT License).
        """
        highs = df['high'].values
        lows = df['low'].values
        n = len(highs)
        min_peaks = 2

        # Find local highs and lows with a small window
        win = max(2, self.lookback // 10)
        peak_prices, valley_prices = [], []

        for i in range(win, n - win):
            seg_h = highs[i - win: i + win + 1]
            seg_l = lows[i - win: i + win + 1]
            if highs[i] == np.max(seg_h):
                peak_prices.append(highs[i])
            if lows[i] == np.min(seg_l):
                valley_prices.append(lows[i])

        if len(peak_prices) < min_peaks or len(valley_prices) < min_peaks:
            return None

        peaks_rising = all(
            peak_prices[j + 1] > peak_prices[j]
            for j in range(len(peak_prices) - 1)
        )
        valleys_falling = all(
            valley_prices[j + 1] < valley_prices[j]
            for j in range(len(valley_prices) - 1)
        )

        if peaks_rising and valleys_falling:
            return PatternResult(
                name="Broadening / Megaphone",
                direction="CONTINUATION",
                confidence=0.60,
                description=(
                    f"Rising highs ({peak_prices[0]:.0f}→{peak_prices[-1]:.0f}) + "
                    f"falling lows ({valley_prices[0]:.0f}→{valley_prices[-1]:.0f}) — "
                    "expanding volatility, directional breakout pending"
                ),
            )

        return None
