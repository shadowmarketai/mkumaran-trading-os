"""
Smart Money Concepts (SMC/ICT) Engine for MKUMARAN Trading OS.

Detects institutional order flow patterns:
- BOS (Break of Structure)
- CHoCH (Change of Character)
- Order Blocks (Demand/Supply)
- Fair Value Gaps (FVG)
- Liquidity Sweeps
- Premium/Discount Zones

Integrates with the MWA scoring system as scanners 41-52.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

from mcp_server.pattern_engine import PatternResult
from mcp_server.volatility import scaled_tolerance, atr_distance

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════


def _find_swing_points(
    df: pd.DataFrame, lookback: int = 5
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """
    Identify swing highs and swing lows using a rolling lookback window.

    A swing high is a bar whose high is the highest in [i-lookback, i+lookback].
    A swing low is a bar whose low is the lowest in [i-lookback, i+lookback].

    Returns:
        (swing_highs, swing_lows) as lists of (index, price) tuples.
    """
    highs = df["high"].values
    lows = df["low"].values
    n = len(highs)

    swing_highs: list[tuple[int, float]] = []
    swing_lows: list[tuple[int, float]] = []

    for i in range(lookback, n - lookback):
        window_high = highs[i - lookback : i + lookback + 1]
        if highs[i] == np.max(window_high):
            swing_highs.append((i, float(highs[i])))

        window_low = lows[i - lookback : i + lookback + 1]
        if lows[i] == np.min(window_low):
            swing_lows.append((i, float(lows[i])))

    return swing_highs, swing_lows


def _identify_trend(
    swing_highs: list[tuple[int, float]],
    swing_lows: list[tuple[int, float]],
) -> str:
    """
    Determine market structure trend from swing points.

    UPTREND: Higher Highs + Higher Lows
    DOWNTREND: Lower Highs + Lower Lows
    SIDEWAYS: Mixed or insufficient data
    """
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return "SIDEWAYS"

    # Check last 3 swing points (or fewer if not available)
    recent_highs = swing_highs[-3:]
    recent_lows = swing_lows[-3:]

    hh_count = sum(
        1
        for i in range(1, len(recent_highs))
        if recent_highs[i][1] > recent_highs[i - 1][1]
    )
    hl_count = sum(
        1
        for i in range(1, len(recent_lows))
        if recent_lows[i][1] > recent_lows[i - 1][1]
    )
    lh_count = sum(
        1
        for i in range(1, len(recent_highs))
        if recent_highs[i][1] < recent_highs[i - 1][1]
    )
    ll_count = sum(
        1
        for i in range(1, len(recent_lows))
        if recent_lows[i][1] < recent_lows[i - 1][1]
    )

    if hh_count > 0 and hl_count > 0:
        return "UPTREND"
    if lh_count > 0 and ll_count > 0:
        return "DOWNTREND"
    return "SIDEWAYS"


def _find_equal_levels(
    levels: list[tuple[int, float]], tolerance: float = 0.005
) -> list[list[tuple[int, float]]]:
    """
    Group price levels that are within tolerance of each other.

    Useful for finding equal highs/lows (liquidity pools).
    """
    if not levels:
        return []

    sorted_levels = sorted(levels, key=lambda x: x[1])
    groups: list[list[tuple[int, float]]] = [[sorted_levels[0]]]

    for lvl in sorted_levels[1:]:
        ref_price = groups[-1][0][1]
        if abs(lvl[1] - ref_price) / max(ref_price, 1) <= tolerance:
            groups[-1].append(lvl)
        else:
            groups.append([lvl])

    return [g for g in groups if len(g) >= 2]


def _calculate_dealing_range(
    swing_highs: list[tuple[int, float]],
    swing_lows: list[tuple[int, float]],
) -> tuple[float, float, float]:
    """
    Calculate the current dealing range (high, low, equilibrium).

    Uses the most recent significant swing high and swing low.
    """
    if not swing_highs or not swing_lows:
        return 0.0, 0.0, 0.0

    high = swing_highs[-1][1]
    low = swing_lows[-1][1]

    # Use the highest recent swing high and lowest recent swing low
    if len(swing_highs) >= 2:
        high = max(h[1] for h in swing_highs[-3:])
    if len(swing_lows) >= 2:
        low = min(l[1] for l in swing_lows[-3:])

    equilibrium = (high + low) / 2
    return high, low, equilibrium


# ══════════════════════════════════════════════════════════════
# SMC ENGINE CLASS
# ══════════════════════════════════════════════════════════════


class SMCEngine:
    """
    Smart Money Concepts detector.

    6 detectors covering institutional order flow patterns:
    1. BOS — Break of Structure
    2. CHoCH — Change of Character
    3. Order Blocks — Demand/Supply zones
    4. FVG — Fair Value Gaps
    5. Liquidity Sweeps — Stop hunts
    6. Premium/Discount — Zone context
    """

    def __init__(self, lookback: int = 60, swing_lookback: int = 5):
        self.lookback = lookback
        self.swing_lookback = swing_lookback
        self.df_full = None

    def detect_all(self, df: pd.DataFrame) -> list[PatternResult]:
        """Run all 6 SMC detectors and return matches."""
        if len(df) < self.lookback:
            logger.warning(
                "Insufficient data for SMC detection: %d bars", len(df)
            )
            return []

        self.df_full = df
        data = df.tail(self.lookback).copy()
        # Normalize column names to lowercase
        data.columns = [c.lower() for c in data.columns]
        data = data.reset_index(drop=True)

        patterns: list[PatternResult] = []
        detectors = [
            self.detect_bos,
            self.detect_choch,
            self.detect_order_blocks,
            self.detect_fvg,
            self.detect_liquidity_sweep,
            self.detect_premium_discount,
        ]

        for detector in detectors:
            try:
                results = detector(data)
                if isinstance(results, list):
                    patterns.extend(results)
                elif results is not None:
                    patterns.append(results)
            except Exception as e:
                logger.error(
                    "SMC detector %s failed: %s", detector.__name__, e
                )

        if patterns:
            logger.info(
                "SMC detected %d patterns: %s",
                len(patterns),
                [p.name for p in patterns],
            )

        return patterns

    def _tol(self, base=0.003):
        return scaled_tolerance(self.df_full, base) if self.df_full is not None and len(self.df_full) > 15 else base

    # ── 1. Break of Structure (BOS) ──────────────────────────

    def detect_bos(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """
        Detect Break of Structure.

        Bullish BOS: Price breaks above a previous swing high in an uptrend
        (continuation — higher high confirmed).

        Bearish BOS: Price breaks below a previous swing low in a downtrend
        (continuation — lower low confirmed).
        """
        swing_highs, swing_lows = _find_swing_points(df, self.swing_lookback)

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return None

        trend = _identify_trend(swing_highs, swing_lows)
        current_close = float(df["close"].iloc[-1])

        # Bullish BOS: uptrend + close breaks above previous swing high
        if trend == "UPTREND":
            prev_high = swing_highs[-2][1]
            if current_close > prev_high:
                return PatternResult(
                    name="BOS Bullish",
                    direction="BULLISH",
                    confidence=0.70,
                    description=(
                        f"Break of Structure up: close {current_close:.2f} "
                        f"broke above swing high {prev_high:.2f}"
                    ),
                )

        # Bearish BOS: downtrend + close breaks below previous swing low
        if trend == "DOWNTREND":
            prev_low = swing_lows[-2][1]
            if current_close < prev_low:
                return PatternResult(
                    name="BOS Bearish",
                    direction="BEARISH",
                    confidence=0.70,
                    description=(
                        f"Break of Structure down: close {current_close:.2f} "
                        f"broke below swing low {prev_low:.2f}"
                    ),
                )

        return None

    # ── 2. Change of Character (CHoCH) ───────────────────────

    def detect_choch(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """
        Detect Change of Character (trend reversal signal).

        Bullish CHoCH: In a downtrend, price breaks above a previous swing high
        (first higher high = potential reversal up).

        Bearish CHoCH: In an uptrend, price breaks below a previous swing low
        (first lower low = potential reversal down).
        """
        swing_highs, swing_lows = _find_swing_points(df, self.swing_lookback)

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return None

        trend = _identify_trend(swing_highs, swing_lows)
        current_close = float(df["close"].iloc[-1])

        # Bullish CHoCH: was downtrend, now breaking swing high
        if trend == "DOWNTREND":
            last_high = swing_highs[-1][1]
            if current_close > last_high:
                return PatternResult(
                    name="CHoCH Bullish",
                    direction="BULLISH",
                    confidence=0.75,
                    description=(
                        f"Change of Character up: close {current_close:.2f} "
                        f"broke swing high {last_high:.2f} in downtrend"
                    ),
                )

        # Bearish CHoCH: was uptrend, now breaking swing low
        if trend == "UPTREND":
            last_low = swing_lows[-1][1]
            if current_close < last_low:
                return PatternResult(
                    name="CHoCH Bearish",
                    direction="BEARISH",
                    confidence=0.75,
                    description=(
                        f"Change of Character down: close {current_close:.2f} "
                        f"broke swing low {last_low:.2f} in uptrend"
                    ),
                )

        return None

    # ── 3. Order Blocks ──────────────────────────────────────

    def detect_order_blocks(
        self, df: pd.DataFrame
    ) -> list[PatternResult]:
        """
        Detect Order Blocks (last opposing candle before impulsive move).

        Demand OB (Bullish): Last bearish candle before a strong bullish move.
        Supply OB (Bearish): Last bullish candle before a strong bearish move.
        """
        results: list[PatternResult] = []
        n = len(df)
        if n < 10:
            return results

        closes = df["close"].values
        opens = df["open"].values
        highs = df["high"].values
        lows = df["low"].values

        # Look at the last 20 bars for OBs
        scan_start = max(0, n - 20)

        for i in range(scan_start, n - 3):
            body_i = closes[i] - opens[i]
            # Next 2 candles form the impulsive move
            move = closes[i + 2] - closes[i]
            avg_range = np.mean(highs[scan_start:n] - lows[scan_start:n])

            # Demand OB: bearish candle followed by strong bullish move
            if body_i < 0 and move > avg_range * 1.5:
                ob_high = max(opens[i], closes[i])
                ob_low = min(opens[i], closes[i])
                current = closes[-1]

                # Check if OB is unmitigated (price hasn't returned to fill it)
                mitigated = any(lows[j] <= ob_high for j in range(i + 3, n))
                if not mitigated and current > ob_high:
                    results.append(
                        PatternResult(
                            name="Demand Order Block",
                            direction="BULLISH",
                            confidence=0.72,
                            description=(
                                f"Demand OB at {ob_low:.2f}-{ob_high:.2f} "
                                f"(unmitigated)"
                            ),
                        )
                    )

            # Supply OB: bullish candle followed by strong bearish move
            if body_i > 0 and move < -avg_range * 1.5:
                ob_high = max(opens[i], closes[i])
                ob_low = min(opens[i], closes[i])
                current = closes[-1]

                mitigated = any(highs[j] >= ob_low for j in range(i + 3, n))
                if not mitigated and current < ob_low:
                    results.append(
                        PatternResult(
                            name="Supply Order Block",
                            direction="BEARISH",
                            confidence=0.72,
                            description=(
                                f"Supply OB at {ob_low:.2f}-{ob_high:.2f} "
                                f"(unmitigated)"
                            ),
                        )
                    )

        # Return only the most recent OB per direction
        demand = [r for r in results if r.direction == "BULLISH"]
        supply = [r for r in results if r.direction == "BEARISH"]
        final: list[PatternResult] = []
        if demand:
            final.append(demand[-1])
        if supply:
            final.append(supply[-1])
        return final

    # ── 4. Fair Value Gap (FVG) ──────────────────────────────

    def detect_fvg(self, df: pd.DataFrame) -> list[PatternResult]:
        """
        Detect Fair Value Gaps (imbalance between 3 candles).

        Bullish FVG: Candle 3's low > Candle 1's high (gap up imbalance).
        Bearish FVG: Candle 1's low > Candle 3's high (gap down imbalance).

        Only reports unfilled FVGs in the last 15 bars.
        """
        results: list[PatternResult] = []
        n = len(df)
        if n < 5:
            return results

        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values

        scan_start = max(0, n - 15)

        for i in range(scan_start, n - 2):
            candle1_high = highs[i]
            candle1_low = lows[i]
            candle3_high = highs[i + 2]
            candle3_low = lows[i + 2]

            # Bullish FVG: gap between candle 1 high and candle 3 low
            if candle3_low > candle1_high:
                gap_size = candle3_low - candle1_high
                avg_range = np.mean(highs[scan_start:n] - lows[scan_start:n])
                if gap_size > avg_range * 0.2:
                    # Check if FVG is unfilled
                    filled = any(
                        lows[j] <= candle1_high
                        for j in range(i + 3, n)
                    )
                    if not filled:
                        results.append(
                            PatternResult(
                                name="Bullish FVG",
                                direction="BULLISH",
                                confidence=0.68,
                                description=(
                                    f"Fair Value Gap up at "
                                    f"{candle1_high:.2f}-{candle3_low:.2f}"
                                ),
                            )
                        )

            # Bearish FVG: gap between candle 3 high and candle 1 low
            if candle1_low > candle3_high:
                gap_size = candle1_low - candle3_high
                avg_range = np.mean(highs[scan_start:n] - lows[scan_start:n])
                if gap_size > avg_range * 0.2:
                    filled = any(
                        highs[j] >= candle1_low
                        for j in range(i + 3, n)
                    )
                    if not filled:
                        results.append(
                            PatternResult(
                                name="Bearish FVG",
                                direction="BEARISH",
                                confidence=0.68,
                                description=(
                                    f"Fair Value Gap down at "
                                    f"{candle3_high:.2f}-{candle1_low:.2f}"
                                ),
                            )
                        )

        # Return most recent per direction
        bull_fvg = [r for r in results if r.direction == "BULLISH"]
        bear_fvg = [r for r in results if r.direction == "BEARISH"]
        final: list[PatternResult] = []
        if bull_fvg:
            final.append(bull_fvg[-1])
        if bear_fvg:
            final.append(bear_fvg[-1])
        return final

    # ── 5. Liquidity Sweep ───────────────────────────────────

    def detect_liquidity_sweep(
        self, df: pd.DataFrame
    ) -> Optional[PatternResult]:
        """
        Detect Liquidity Sweeps (stop hunts / equal level raids).

        Bullish Sweep: Price dips below equal lows then closes back above
        (trapped shorts, smart money buying).

        Bearish Sweep: Price spikes above equal highs then closes back below
        (trapped longs, smart money selling).
        """
        swing_highs, swing_lows = _find_swing_points(df, self.swing_lookback)

        current_low = float(df["low"].iloc[-1])
        current_high = float(df["high"].iloc[-1])
        current_close = float(df["close"].iloc[-1])

        # Look for equal lows (liquidity pool below)
        equal_low_groups = _find_equal_levels(swing_lows, tolerance=self._tol(0.003))
        for group in equal_low_groups:
            level = min(p for _, p in group)
            # Price swept below the level but closed back above
            if current_low < level and current_close > level:
                return PatternResult(
                    name="Liquidity Sweep Bullish",
                    direction="BULLISH",
                    confidence=0.78,
                    description=(
                        f"Swept equal lows at {level:.2f}, "
                        f"closed back at {current_close:.2f}"
                    ),
                )

        # Look for equal highs (liquidity pool above)
        equal_high_groups = _find_equal_levels(swing_highs, tolerance=self._tol(0.003))
        for group in equal_high_groups:
            level = max(p for _, p in group)
            # Price swept above the level but closed back below
            if current_high > level and current_close < level:
                return PatternResult(
                    name="Liquidity Sweep Bearish",
                    direction="BEARISH",
                    confidence=0.78,
                    description=(
                        f"Swept equal highs at {level:.2f}, "
                        f"closed back at {current_close:.2f}"
                    ),
                )

        return None

    # ── 6. Premium / Discount Zones ──────────────────────────

    def detect_premium_discount(
        self, df: pd.DataFrame
    ) -> Optional[PatternResult]:
        """
        Detect whether price is in Premium (above EQ) or Discount (below EQ).

        Discount Zone (Bullish bias): Price below equilibrium of dealing range.
        Premium Zone (Bearish bias): Price above equilibrium of dealing range.
        """
        swing_highs, swing_lows = _find_swing_points(df, self.swing_lookback)

        if not swing_highs or not swing_lows:
            return None

        high, low, equilibrium = _calculate_dealing_range(
            swing_highs, swing_lows
        )

        if high == low:
            return None

        current_close = float(df["close"].iloc[-1])
        position_pct = (current_close - low) / (high - low) * 100

        if position_pct <= 40:
            return PatternResult(
                name="Discount Zone",
                direction="BULLISH",
                confidence=0.62,
                description=(
                    f"Price at {position_pct:.0f}% of dealing range "
                    f"({low:.2f}-{high:.2f}), EQ={equilibrium:.2f}"
                ),
            )

        if position_pct >= 60:
            return PatternResult(
                name="Premium Zone",
                direction="BEARISH",
                confidence=0.62,
                description=(
                    f"Price at {position_pct:.0f}% of dealing range "
                    f"({low:.2f}-{high:.2f}), EQ={equilibrium:.2f}"
                ),
            )

        return None


# ══════════════════════════════════════════════════════════════
# SCANNER WRAPPER FUNCTIONS (for MWA integration)
# ══════════════════════════════════════════════════════════════
# Each function accepts stock_data: dict[str, DataFrame]
# and returns list[str] of matching tickers.


def _run_smc_scan(
    stock_data: dict[str, pd.DataFrame],
    pattern_name: str,
    direction: str,
) -> list[str]:
    """Generic scanner: run SMCEngine on each stock and filter by pattern+direction."""
    engine = SMCEngine()
    matches: list[str] = []

    for ticker, df in stock_data.items():
        try:
            if len(df) < engine.lookback:
                continue
            patterns = engine.detect_all(df)
            for p in patterns:
                if p.name == pattern_name and p.direction == direction:
                    matches.append(ticker)
                    break
        except Exception as e:
            logger.error("SMC scan failed for %s: %s", ticker, e)

    return matches


def scan_bos_bull(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for Bullish Break of Structure."""
    return _run_smc_scan(stock_data, "BOS Bullish", "BULLISH")


def scan_bos_bear(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for Bearish Break of Structure."""
    return _run_smc_scan(stock_data, "BOS Bearish", "BEARISH")


def scan_choch_bull(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for Bullish Change of Character."""
    return _run_smc_scan(stock_data, "CHoCH Bullish", "BULLISH")


def scan_choch_bear(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for Bearish Change of Character."""
    return _run_smc_scan(stock_data, "CHoCH Bearish", "BEARISH")


def scan_bullish_ob(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for Demand Order Blocks."""
    return _run_smc_scan(stock_data, "Demand Order Block", "BULLISH")


def scan_bearish_ob(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for Supply Order Blocks."""
    return _run_smc_scan(stock_data, "Supply Order Block", "BEARISH")


def scan_bullish_fvg(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for Bullish Fair Value Gaps."""
    return _run_smc_scan(stock_data, "Bullish FVG", "BULLISH")


def scan_bearish_fvg(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for Bearish Fair Value Gaps."""
    return _run_smc_scan(stock_data, "Bearish FVG", "BEARISH")


def scan_liquidity_sweep_bull(
    stock_data: dict[str, pd.DataFrame],
) -> list[str]:
    """Scan for Bullish Liquidity Sweeps."""
    return _run_smc_scan(stock_data, "Liquidity Sweep Bullish", "BULLISH")


def scan_liquidity_sweep_bear(
    stock_data: dict[str, pd.DataFrame],
) -> list[str]:
    """Scan for Bearish Liquidity Sweeps."""
    return _run_smc_scan(stock_data, "Liquidity Sweep Bearish", "BEARISH")


def scan_discount_zone(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for stocks in Discount Zone."""
    return _run_smc_scan(stock_data, "Discount Zone", "BULLISH")


def scan_premium_zone(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for stocks in Premium Zone."""
    return _run_smc_scan(stock_data, "Premium Zone", "BEARISH")
