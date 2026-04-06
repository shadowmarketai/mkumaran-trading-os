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
from mcp_server.volatility import scaled_tolerance

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
        low = min(sl[1] for sl in swing_lows[-3:])

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
            self.detect_breaker_block,
            self.detect_mitigation_block,
            self.detect_inversion_fvg,
            self.detect_mss,
            self.detect_ote,
            self.detect_inducement,
            self.detect_ce,
            self.detect_irl_erl,
            self.detect_fake_breakout,
            self.detect_ema_pullback,
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
            logger.debug(
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

    # ── 7. Breaker Block (BB) ─────────────────────────────────

    def detect_breaker_block(
        self, df: pd.DataFrame
    ) -> list[PatternResult]:
        """
        Detect Breaker Blocks — failed Order Blocks that flip polarity.

        When price breaks through an OB, that OB becomes a Breaker Block.
        Bullish BB: A supply OB that gets broken upward — now acts as demand.
        Bearish BB: A demand OB that gets broken downward — now acts as supply.
        Trade: wait for price to retest the BB zone, enter on rejection candle.
        """
        results: list[PatternResult] = []
        n = len(df)
        if n < 15:
            return results

        closes = df["close"].values
        opens = df["open"].values
        highs = df["high"].values
        lows = df["low"].values
        scan_start = max(0, n - 25)

        for i in range(scan_start, n - 5):
            body_i = closes[i] - opens[i]
            avg_range = np.mean(highs[scan_start:n] - lows[scan_start:n])

            # Supply OB candidate: bullish candle before bearish move
            if body_i > 0:
                move_down = closes[i] - min(closes[i + 1], closes[min(i + 2, n - 1)])
                if move_down > avg_range * 1.2:
                    ob_high = max(opens[i], closes[i])
                    ob_low = min(opens[i], closes[i])
                    # Check if price later broke ABOVE this supply OB -> Bullish BB
                    broken_above = False
                    break_idx = -1
                    for j in range(i + 3, n):
                        if closes[j] > ob_high:
                            broken_above = True
                            break_idx = j
                            break
                    if broken_above and break_idx < n - 1:
                        # Check if price is retesting the BB from above
                        current = closes[-1]
                        if ob_low <= current <= ob_high * 1.01:
                            results.append(
                                PatternResult(
                                    name="Breaker Block Bullish",
                                    direction="BULLISH",
                                    confidence=0.74,
                                    description=(
                                        f"Bullish BB at {ob_low:.2f}-{ob_high:.2f} "
                                        f"(failed supply OB, retesting)"
                                    ),
                                )
                            )

            # Demand OB candidate: bearish candle before bullish move
            if body_i < 0:
                move_up = max(closes[i + 1], closes[min(i + 2, n - 1)]) - closes[i]
                if move_up > avg_range * 1.2:
                    ob_high = max(opens[i], closes[i])
                    ob_low = min(opens[i], closes[i])
                    # Check if price later broke BELOW this demand OB -> Bearish BB
                    broken_below = False
                    break_idx = -1
                    for j in range(i + 3, n):
                        if closes[j] < ob_low:
                            broken_below = True
                            break_idx = j
                            break
                    if broken_below and break_idx < n - 1:
                        current = closes[-1]
                        if ob_low * 0.99 <= current <= ob_high:
                            results.append(
                                PatternResult(
                                    name="Breaker Block Bearish",
                                    direction="BEARISH",
                                    confidence=0.74,
                                    description=(
                                        f"Bearish BB at {ob_low:.2f}-{ob_high:.2f} "
                                        f"(failed demand OB, retesting)"
                                    ),
                                )
                            )

        bull_bb = [r for r in results if r.direction == "BULLISH"]
        bear_bb = [r for r in results if r.direction == "BEARISH"]
        final: list[PatternResult] = []
        if bull_bb:
            final.append(bull_bb[-1])
        if bear_bb:
            final.append(bear_bb[-1])
        return final

    # ── 8. Mitigation Block (MB) ──────────────────────────────

    def detect_mitigation_block(
        self, df: pd.DataFrame
    ) -> list[PatternResult]:
        """
        Detect Mitigation Blocks — OBs that were partially filled (mitigated)
        but price returned and reacted again.

        Bullish MB: Demand OB was wicked into but held, price bounced again.
        Bearish MB: Supply OB was wicked into but held, price rejected again.
        """
        results: list[PatternResult] = []
        n = len(df)
        if n < 15:
            return results

        closes = df["close"].values
        opens = df["open"].values
        highs = df["high"].values
        lows = df["low"].values
        scan_start = max(0, n - 25)

        for i in range(scan_start, n - 5):
            body_i = closes[i] - opens[i]
            avg_range = np.mean(highs[scan_start:n] - lows[scan_start:n])

            # Demand OB: bearish candle before bullish move
            if body_i < 0:
                move = closes[min(i + 2, n - 1)] - closes[i]
                if move > avg_range * 1.3:
                    ob_high = max(opens[i], closes[i])
                    ob_low = min(opens[i], closes[i])
                    # Check if price returned and wicked into OB (mitigated)
                    mitigated = False
                    held = True
                    for j in range(i + 3, n - 1):
                        if lows[j] <= ob_high and lows[j] >= ob_low:
                            mitigated = True
                        if closes[j] < ob_low:
                            held = False
                            break
                    if mitigated and held:
                        current = closes[-1]
                        if current > ob_high:
                            results.append(
                                PatternResult(
                                    name="Mitigation Block Bullish",
                                    direction="BULLISH",
                                    confidence=0.70,
                                    description=(
                                        f"Bullish MB at {ob_low:.2f}-{ob_high:.2f} "
                                        f"(demand OB mitigated but held)"
                                    ),
                                )
                            )

            # Supply OB: bullish candle before bearish move
            if body_i > 0:
                move = closes[i] - closes[min(i + 2, n - 1)]
                if move > avg_range * 1.3:
                    ob_high = max(opens[i], closes[i])
                    ob_low = min(opens[i], closes[i])
                    mitigated = False
                    held = True
                    for j in range(i + 3, n - 1):
                        if highs[j] >= ob_low and highs[j] <= ob_high:
                            mitigated = True
                        if closes[j] > ob_high:
                            held = False
                            break
                    if mitigated and held:
                        current = closes[-1]
                        if current < ob_low:
                            results.append(
                                PatternResult(
                                    name="Mitigation Block Bearish",
                                    direction="BEARISH",
                                    confidence=0.70,
                                    description=(
                                        f"Bearish MB at {ob_low:.2f}-{ob_high:.2f} "
                                        f"(supply OB mitigated but held)"
                                    ),
                                )
                            )

        bull = [r for r in results if r.direction == "BULLISH"]
        bear = [r for r in results if r.direction == "BEARISH"]
        final: list[PatternResult] = []
        if bull:
            final.append(bull[-1])
        if bear:
            final.append(bear[-1])
        return final

    # ── 9. Inversion FVG (IFVG) ───────────────────────────────

    def detect_inversion_fvg(
        self, df: pd.DataFrame
    ) -> list[PatternResult]:
        """
        Detect Inversion FVG — a filled FVG that flips polarity.

        Bullish IFVG: A bearish FVG that got filled, now acts as support.
        Bearish IFVG: A bullish FVG that got filled, now acts as resistance.
        """
        results: list[PatternResult] = []
        n = len(df)
        if n < 10:
            return results

        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        scan_start = max(0, n - 20)

        for i in range(scan_start, n - 4):
            # Bullish FVG: candle3_low > candle1_high
            c1h = highs[i]
            c3l = lows[i + 2]
            if c3l > c1h:
                # Check if it got filled (price came back down through the gap)
                filled = False
                fill_idx = -1
                for j in range(i + 3, n):
                    if lows[j] <= c1h:
                        filled = True
                        fill_idx = j
                        break
                # IFVG Bearish: bullish FVG filled -> now resistance
                if filled and fill_idx < n - 1:
                    current = closes[-1]
                    if c1h * 0.99 <= current <= c3l * 1.01:
                        results.append(
                            PatternResult(
                                name="Inversion FVG Bearish",
                                direction="BEARISH",
                                confidence=0.66,
                                description=(
                                    f"Bearish IFVG at {c1h:.2f}-{c3l:.2f} "
                                    f"(filled bullish FVG acting as resistance)"
                                ),
                            )
                        )

            # Bearish FVG: candle1_low > candle3_high
            c1l = lows[i]
            c3h = highs[i + 2]
            if c1l > c3h:
                # Check if it got filled (price came back up through the gap)
                filled = False
                fill_idx = -1
                for j in range(i + 3, n):
                    if highs[j] >= c1l:
                        filled = True
                        fill_idx = j
                        break
                # IFVG Bullish: bearish FVG filled -> now support
                if filled and fill_idx < n - 1:
                    current = closes[-1]
                    if c3h * 0.99 <= current <= c1l * 1.01:
                        results.append(
                            PatternResult(
                                name="Inversion FVG Bullish",
                                direction="BULLISH",
                                confidence=0.66,
                                description=(
                                    f"Bullish IFVG at {c3h:.2f}-{c1l:.2f} "
                                    f"(filled bearish FVG acting as support)"
                                ),
                            )
                        )

        bull = [r for r in results if r.direction == "BULLISH"]
        bear = [r for r in results if r.direction == "BEARISH"]
        final: list[PatternResult] = []
        if bull:
            final.append(bull[-1])
        if bear:
            final.append(bear[-1])
        return final

    # ── 10. Market Structure Shift (MSS) ──────────────────────

    def detect_mss(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """
        Detect Market Structure Shift — the first break of a key level
        that signals a potential trend change. More aggressive than CHoCH.

        MSS Bullish: In a downtrend, the first higher high after a liquidity sweep
        of a swing low.
        MSS Bearish: In an uptrend, the first lower low after a liquidity sweep
        of a swing high.
        """
        swing_highs, swing_lows = _find_swing_points(df, self.swing_lookback)

        if len(swing_highs) < 3 or len(swing_lows) < 3:
            return None

        trend = _identify_trend(swing_highs, swing_lows)
        current_close = float(df["close"].iloc[-1])
        current_low = float(df["low"].iloc[-1])
        current_high = float(df["high"].iloc[-1])

        # Bullish MSS: downtrend + sweep of low + close above high
        if trend == "DOWNTREND":
            recent_low = swing_lows[-1][1]
            prior_high = swing_highs[-1][1]
            # Check if last few bars swept the swing low
            swept = current_low < recent_low
            if swept and current_close > prior_high:
                return PatternResult(
                    name="MSS Bullish",
                    direction="BULLISH",
                    confidence=0.76,
                    description=(
                        f"Market Structure Shift up: swept low {recent_low:.2f}, "
                        f"close {current_close:.2f} broke high {prior_high:.2f}"
                    ),
                )

        # Bearish MSS: uptrend + sweep of high + close below low
        if trend == "UPTREND":
            recent_high = swing_highs[-1][1]
            prior_low = swing_lows[-1][1]
            swept = current_high > recent_high
            if swept and current_close < prior_low:
                return PatternResult(
                    name="MSS Bearish",
                    direction="BEARISH",
                    confidence=0.76,
                    description=(
                        f"Market Structure Shift down: swept high {recent_high:.2f}, "
                        f"close {current_close:.2f} broke low {prior_low:.2f}"
                    ),
                )

        return None

    # ── 11. Optimal Trade Entry (OTE) ─────────────────────────

    def detect_ote(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """
        Detect Optimal Trade Entry — price retracing to the 62%-79% Fibonacci
        zone of the last impulse move (the institutional sweet spot).

        Bullish OTE: In an uptrend impulse, price retraces to 62-79% and holds.
        Bearish OTE: In a downtrend impulse, price retraces to 62-79% and holds.
        """
        swing_highs, swing_lows = _find_swing_points(df, self.swing_lookback)

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return None

        current_close = float(df["close"].iloc[-1])

        # Find the most recent impulse move
        last_high_idx, last_high = swing_highs[-1]
        last_low_idx, last_low = swing_lows[-1]

        # Bullish OTE: impulse was up (low came before high), now retracing
        if last_low_idx < last_high_idx:
            impulse_range = last_high - last_low
            if impulse_range <= 0:
                return None
            fib_62 = last_high - (0.618 * impulse_range)
            fib_79 = last_high - (0.786 * impulse_range)
            # Price is in the OTE zone (between 62% and 79% retracement)
            if fib_79 <= current_close <= fib_62:
                return PatternResult(
                    name="OTE Bullish",
                    direction="BULLISH",
                    confidence=0.72,
                    description=(
                        f"Optimal Trade Entry zone: price {current_close:.2f} "
                        f"at Fib 62-79% ({fib_62:.2f}-{fib_79:.2f}) "
                        f"of impulse {last_low:.2f}-{last_high:.2f}"
                    ),
                )

        # Bearish OTE: impulse was down (high came before low), now retracing
        if last_high_idx < last_low_idx:
            impulse_range = last_high - last_low
            if impulse_range <= 0:
                return None
            fib_62 = last_low + (0.618 * impulse_range)
            fib_79 = last_low + (0.786 * impulse_range)
            if fib_62 <= current_close <= fib_79:
                return PatternResult(
                    name="OTE Bearish",
                    direction="BEARISH",
                    confidence=0.72,
                    description=(
                        f"Optimal Trade Entry zone: price {current_close:.2f} "
                        f"at Fib 62-79% ({fib_62:.2f}-{fib_79:.2f}) "
                        f"of impulse {last_high:.2f}-{last_low:.2f}"
                    ),
                )

        return None

    # ── 12. Inducement (IDM) ──────────────────────────────────

    def detect_inducement(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """
        Detect Inducement — minor liquidity pools (minor swing highs/lows)
        that trap retail traders before the real move.

        Bullish IDM: Minor swing low gets swept but major swing low holds.
        Bearish IDM: Minor swing high gets swept but major swing high holds.
        """
        # Use a smaller lookback for minor swings
        minor_highs, minor_lows = _find_swing_points(df, lookback=3)
        major_highs, major_lows = _find_swing_points(df, self.swing_lookback)

        if len(minor_lows) < 2 or len(major_lows) < 1:
            return None

        current_low = float(df["low"].iloc[-1])
        current_high = float(df["high"].iloc[-1])
        current_close = float(df["close"].iloc[-1])

        # Bullish IDM: minor low swept but major low held
        if major_lows:
            major_low = major_lows[-1][1]
            for _, minor_low in minor_lows[-3:]:
                if minor_low > major_low:
                    # Minor low is above major low — it's inducement
                    if current_low < minor_low and current_close > minor_low:
                        if current_low > major_low * 0.995:
                            return PatternResult(
                                name="Inducement Bullish",
                                direction="BULLISH",
                                confidence=0.65,
                                description=(
                                    f"Bullish inducement: swept minor low "
                                    f"{minor_low:.2f}, major low {major_low:.2f} held"
                                ),
                            )

        # Bearish IDM: minor high swept but major high held
        if major_highs:
            major_high = major_highs[-1][1]
            for _, minor_high in minor_highs[-3:]:
                if minor_high < major_high:
                    if current_high > minor_high and current_close < minor_high:
                        if current_high < major_high * 1.005:
                            return PatternResult(
                                name="Inducement Bearish",
                                direction="BEARISH",
                                confidence=0.65,
                                description=(
                                    f"Bearish inducement: swept minor high "
                                    f"{minor_high:.2f}, major high {major_high:.2f} held"
                                ),
                            )

        return None

    # ── 13. Consequent Encroachment (CE) ──────────────────────

    def detect_ce(self, df: pd.DataFrame) -> list[PatternResult]:
        """
        Detect Consequent Encroachment — price reacting at the 50% midpoint
        of a Fair Value Gap. CE is the equilibrium of an FVG.
        """
        results: list[PatternResult] = []
        n = len(df)
        if n < 8:
            return results

        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        current = closes[-1]
        tol = self._tol(0.003)
        scan_start = max(0, n - 15)

        for i in range(scan_start, n - 2):
            # Bullish FVG CE
            c1h = highs[i]
            c3l = lows[i + 2]
            if c3l > c1h:
                ce_level = (c1h + c3l) / 2
                if abs(current - ce_level) / max(ce_level, 1) <= tol:
                    results.append(
                        PatternResult(
                            name="CE Bullish FVG",
                            direction="BULLISH",
                            confidence=0.60,
                            description=(
                                f"Price at CE (50%) of bullish FVG: "
                                f"{ce_level:.2f} (gap {c1h:.2f}-{c3l:.2f})"
                            ),
                        )
                    )

            # Bearish FVG CE
            c1l = lows[i]
            c3h = highs[i + 2]
            if c1l > c3h:
                ce_level = (c3h + c1l) / 2
                if abs(current - ce_level) / max(ce_level, 1) <= tol:
                    results.append(
                        PatternResult(
                            name="CE Bearish FVG",
                            direction="BEARISH",
                            confidence=0.60,
                            description=(
                                f"Price at CE (50%) of bearish FVG: "
                                f"{ce_level:.2f} (gap {c3h:.2f}-{c1l:.2f})"
                            ),
                        )
                    )

        bull = [r for r in results if r.direction == "BULLISH"]
        bear = [r for r in results if r.direction == "BEARISH"]
        final: list[PatternResult] = []
        if bull:
            final.append(bull[-1])
        if bear:
            final.append(bear[-1])
        return final

    # ── 14. Internal/External Range Liquidity (IRL/ERL) ───────

    def detect_irl_erl(self, df: pd.DataFrame) -> list[PatternResult]:
        """
        Detect IRL/ERL context.

        IRL (Internal Range Liquidity): FVGs, OBs within the current dealing range
            — price is drawn to these as intermediate targets.
        ERL (External Range Liquidity): Swing highs/lows outside the range
            — price is drawn to these as ultimate targets.

        Bullish ERL: Price targeting buy-side liquidity (swing highs above).
        Bearish ERL: Price targeting sell-side liquidity (swing lows below).
        """
        results: list[PatternResult] = []
        swing_highs, swing_lows = _find_swing_points(df, self.swing_lookback)

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return results

        high, low, eq = _calculate_dealing_range(swing_highs, swing_lows)
        current_close = float(df["close"].iloc[-1])

        if high == low:
            return results

        # ERL: external swing levels as draw on liquidity
        # Buy-side liquidity (BSL): swing highs above current price
        bsl_levels = [p for _, p in swing_highs if p > current_close]
        # Sell-side liquidity (SSL): swing lows below current price
        ssl_levels = [p for _, p in swing_lows if p < current_close]

        # If price is in discount and there's BSL above -> Bullish draw
        position_pct = (current_close - low) / (high - low) * 100
        if position_pct <= 50 and bsl_levels:
            nearest_bsl = min(bsl_levels)
            results.append(
                PatternResult(
                    name="ERL Bullish",
                    direction="BULLISH",
                    confidence=0.64,
                    description=(
                        f"Buy-side liquidity target at {nearest_bsl:.2f}, "
                        f"price in discount ({position_pct:.0f}%)"
                    ),
                )
            )

        # If price is in premium and there's SSL below -> Bearish draw
        if position_pct >= 50 and ssl_levels:
            nearest_ssl = max(ssl_levels)
            results.append(
                PatternResult(
                    name="ERL Bearish",
                    direction="BEARISH",
                    confidence=0.64,
                    description=(
                        f"Sell-side liquidity target at {nearest_ssl:.2f}, "
                        f"price in premium ({position_pct:.0f}%)"
                    ),
                )
            )

        return results

    # ── 15. Fake Breakout Detection ───────────────────────────

    def detect_fake_breakout(
        self, df: pd.DataFrame
    ) -> Optional[PatternResult]:
        """
        Detect Fake Breakout — price breaks a key level then reverses.

        Bullish Fake Breakout: Price breaks below support, then closes back above
        (bear trap / spring).
        Bearish Fake Breakout: Price breaks above resistance, then closes back below
        (bull trap / upthrust).
        """
        swing_highs, swing_lows = _find_swing_points(df, self.swing_lookback)

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return None

        n = len(df)
        current_close = float(df["close"].iloc[-1])
        lows_arr = df["low"].values
        highs_arr = df["high"].values

        # Check last 3 bars for a fake breakout below support
        for _, support_level in swing_lows[-3:]:
            for k in range(max(0, n - 3), n):
                if lows_arr[k] < support_level and current_close > support_level:
                    return PatternResult(
                        name="Fake Breakout Bullish",
                        direction="BULLISH",
                        confidence=0.73,
                        description=(
                            f"Fake breakout below {support_level:.2f}, "
                            f"closed back at {current_close:.2f} (bear trap)"
                        ),
                    )

        # Check last 3 bars for a fake breakout above resistance
        for _, resist_level in swing_highs[-3:]:
            for k in range(max(0, n - 3), n):
                if highs_arr[k] > resist_level and current_close < resist_level:
                    return PatternResult(
                        name="Fake Breakout Bearish",
                        direction="BEARISH",
                        confidence=0.73,
                        description=(
                            f"Fake breakout above {resist_level:.2f}, "
                            f"closed back at {current_close:.2f} (bull trap)"
                        ),
                    )

        return None

    # ── 16. EMA 9/21 Framework ────────────────────────────────

    def detect_ema_pullback(
        self, df: pd.DataFrame
    ) -> Optional[PatternResult]:
        """
        Detect 9/21 EMA pullback entries in trending markets.

        Bullish: Price above EMA 21 (trending up), pulls back between 9 & 21 EMA,
        bullish candle confirmation.
        Bearish: Price below EMA 21 (trending down), pulls back between 9 & 21 EMA,
        bearish candle confirmation.
        """
        if len(df) < 25:
            return None

        closes = df["close"]
        ema9 = closes.ewm(span=9, adjust=False).mean()
        ema21 = closes.ewm(span=21, adjust=False).mean()

        curr_close = float(closes.iloc[-1])
        curr_ema9 = float(ema9.iloc[-1])
        curr_ema21 = float(ema21.iloc[-1])
        prev_close = float(closes.iloc[-2])

        # Bullish: EMA9 > EMA21, price between EMAs, bullish candle
        if curr_ema9 > curr_ema21:
            if curr_ema21 <= curr_close <= curr_ema9:
                if curr_close > prev_close:
                    # Verify EMA21 is sloping up
                    ema21_slope = float(ema21.iloc[-1]) - float(ema21.iloc[-5])
                    if ema21_slope > 0:
                        return PatternResult(
                            name="EMA Pullback Bullish",
                            direction="BULLISH",
                            confidence=0.68,
                            description=(
                                f"9/21 EMA pullback buy: price {curr_close:.2f} "
                                f"between EMA9={curr_ema9:.2f} & EMA21={curr_ema21:.2f}"
                            ),
                        )

        # Bearish: EMA9 < EMA21, price between EMAs, bearish candle
        if curr_ema9 < curr_ema21:
            if curr_ema9 <= curr_close <= curr_ema21:
                if curr_close < prev_close:
                    ema21_slope = float(ema21.iloc[-1]) - float(ema21.iloc[-5])
                    if ema21_slope < 0:
                        return PatternResult(
                            name="EMA Pullback Bearish",
                            direction="BEARISH",
                            confidence=0.68,
                            description=(
                                f"9/21 EMA pullback sell: price {curr_close:.2f} "
                                f"between EMA9={curr_ema9:.2f} & EMA21={curr_ema21:.2f}"
                            ),
                        )


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


# ── New SMC Scanner Wrappers (Breaker Block, MB, IFVG, MSS, OTE, IDM, CE, IRL/ERL, Fake BO, EMA) ──


def scan_breaker_block_bull(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for Bullish Breaker Blocks."""
    return _run_smc_scan(stock_data, "Breaker Block Bullish", "BULLISH")


def scan_breaker_block_bear(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for Bearish Breaker Blocks."""
    return _run_smc_scan(stock_data, "Breaker Block Bearish", "BEARISH")


def scan_mitigation_block_bull(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for Bullish Mitigation Blocks."""
    return _run_smc_scan(stock_data, "Mitigation Block Bullish", "BULLISH")


def scan_mitigation_block_bear(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for Bearish Mitigation Blocks."""
    return _run_smc_scan(stock_data, "Mitigation Block Bearish", "BEARISH")


def scan_ifvg_bull(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for Bullish Inversion FVG."""
    return _run_smc_scan(stock_data, "Inversion FVG Bullish", "BULLISH")


def scan_ifvg_bear(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for Bearish Inversion FVG."""
    return _run_smc_scan(stock_data, "Inversion FVG Bearish", "BEARISH")


def scan_mss_bull(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for Bullish Market Structure Shift."""
    return _run_smc_scan(stock_data, "MSS Bullish", "BULLISH")


def scan_mss_bear(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for Bearish Market Structure Shift."""
    return _run_smc_scan(stock_data, "MSS Bearish", "BEARISH")


def scan_ote_bull(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for Bullish Optimal Trade Entry (Fib 62-79%)."""
    return _run_smc_scan(stock_data, "OTE Bullish", "BULLISH")


def scan_ote_bear(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for Bearish Optimal Trade Entry (Fib 62-79%)."""
    return _run_smc_scan(stock_data, "OTE Bearish", "BEARISH")


def scan_inducement_bull(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for Bullish Inducement."""
    return _run_smc_scan(stock_data, "Inducement Bullish", "BULLISH")


def scan_inducement_bear(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for Bearish Inducement."""
    return _run_smc_scan(stock_data, "Inducement Bearish", "BEARISH")


def scan_ce_bull(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for Bullish Consequent Encroachment."""
    return _run_smc_scan(stock_data, "CE Bullish FVG", "BULLISH")


def scan_ce_bear(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for Bearish Consequent Encroachment."""
    return _run_smc_scan(stock_data, "CE Bearish FVG", "BEARISH")


def scan_erl_bull(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for Bullish External Range Liquidity draw."""
    return _run_smc_scan(stock_data, "ERL Bullish", "BULLISH")


def scan_erl_bear(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for Bearish External Range Liquidity draw."""
    return _run_smc_scan(stock_data, "ERL Bearish", "BEARISH")


def scan_fake_breakout_bull(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for Bullish Fake Breakout (bear trap)."""
    return _run_smc_scan(stock_data, "Fake Breakout Bullish", "BULLISH")


def scan_fake_breakout_bear(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for Bearish Fake Breakout (bull trap)."""
    return _run_smc_scan(stock_data, "Fake Breakout Bearish", "BEARISH")


def scan_ema_pullback_bull(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for Bullish 9/21 EMA pullback."""
    return _run_smc_scan(stock_data, "EMA Pullback Bullish", "BULLISH")


def scan_ema_pullback_bear(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for Bearish 9/21 EMA pullback."""
    return _run_smc_scan(stock_data, "EMA Pullback Bearish", "BEARISH")
