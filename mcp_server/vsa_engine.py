"""
Volume Spread Analysis (VSA) Engine for MKUMARAN Trading OS.

Detects Tom Williams / Richard Wyckoff volume-price patterns:
- No Demand / No Supply: Low-volume test bars
- Stopping Volume: High volume at extremes halting a trend
- Climactic Volume: Blow-off tops / selling climaxes
- Effort vs Result: Volume-price divergence
- Upthrust / Spring (VSA variant): Trap bars with volume confirmation
- Test Bars: Low-volume retests confirming supply/demand exhaustion

Integrates with MWA scoring system.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

from mcp_server.pattern_engine import PatternResult
from mcp_server.volatility import scaled_spread_ratio, scaled_tolerance

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════


def _bar_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Add spread, body, and volume ratio columns."""
    out = df.copy()
    out["spread"] = out["high"] - out["low"]
    out["body"] = abs(out["close"] - out["open"])
    avg_vol = out["volume"].rolling(20, min_periods=1).mean()
    out["vol_ratio"] = out["volume"] / avg_vol.clip(lower=1)
    avg_spread = out["spread"].rolling(20, min_periods=1).mean()
    out["spread_ratio"] = out["spread"] / avg_spread.clip(lower=0.01)
    out["is_up"] = out["close"] > out["open"]
    out["is_down"] = out["close"] < out["open"]
    return out


# ══════════════════════════════════════════════════════════════
# VSA ENGINE CLASS
# ══════════════════════════════════════════════════════════════


class VSAEngine:
    """
    Volume Spread Analysis detector.

    6 detectors:
    1. No Demand / No Supply — Low-volume narrow-spread bars
    2. Stopping Volume — High volume halting a trend
    3. Climactic Volume — Blow-off / selling climax
    4. Effort vs Result — Volume-price divergence
    5. VSA Upthrust / Spring — Trap bars with volume
    6. Test Bar — Low-volume retest
    """

    def __init__(self, lookback: int = 60):
        self.lookback = lookback
        self.df_full = None

    def detect_all(self, df: pd.DataFrame) -> list[PatternResult]:
        """Run all VSA detectors and return matches."""
        if len(df) < self.lookback:
            logger.warning(
                "Insufficient data for VSA detection: %d bars", len(df)
            )
            return []

        data = df.tail(self.lookback).copy()
        data.columns = [c.lower() for c in data.columns]
        data = data.reset_index(drop=True)
        data = _bar_metrics(data)
        self.df_full = df

        patterns: list[PatternResult] = []
        detectors = [
            self.detect_no_demand_supply,
            self.detect_stopping_volume,
            self.detect_climactic_volume,
            self.detect_effort_vs_result,
            self.detect_vsa_trap,
            self.detect_test_bar,
        ]

        for detector in detectors:
            try:
                results = detector(data)
                if isinstance(results, list):
                    patterns.extend(results)
                elif results is not None:
                    patterns.append(results)
            except Exception as e:
                logger.error("VSA detector %s failed: %s", detector.__name__, e)

        if patterns:
            logger.info(
                "VSA detected %d patterns: %s",
                len(patterns),
                [p.name for p in patterns],
            )
        return patterns

    def _spread_tol(self, base: float = 0.7) -> float:
        """Scale spread ratio threshold by recent volatility."""
        if self.df_full is not None and len(self.df_full) > 15:
            return scaled_spread_ratio(self.df_full, base)
        return base

    def _tol(self, base: float = 0.02) -> float:
        """Scale proximity tolerance by recent volatility."""
        if self.df_full is not None and len(self.df_full) > 15:
            return scaled_tolerance(self.df_full, base)
        return base

    # ── 1. No Demand / No Supply ─────────────────────────────

    def detect_no_demand_supply(
        self, df: pd.DataFrame
    ) -> Optional[PatternResult]:
        """
        Detect No Demand or No Supply bars.

        No Demand (bearish): Up bar with narrow spread + low volume
        → No institutional interest in buying; expect decline.

        No Supply (bullish): Down bar with narrow spread + low volume
        → No institutional selling pressure; expect rise.
        """
        last = df.iloc[-1]

        # No Demand: up bar, narrow spread, low volume
        if last["is_up"] and last["spread_ratio"] < self._spread_tol(0.7) and last["vol_ratio"] < 0.7:
            return PatternResult(
                name="VSA No Demand",
                direction="BEARISH",
                confidence=0.65,
                description=(
                    f"No Demand: up bar with {last['spread_ratio']:.2f}x spread, "
                    f"{last['vol_ratio']:.2f}x volume — no buying interest"
                ),
            )

        # No Supply: down bar, narrow spread, low volume
        if last["is_down"] and last["spread_ratio"] < self._spread_tol(0.7) and last["vol_ratio"] < 0.7:
            return PatternResult(
                name="VSA No Supply",
                direction="BULLISH",
                confidence=0.65,
                description=(
                    f"No Supply: down bar with {last['spread_ratio']:.2f}x spread, "
                    f"{last['vol_ratio']:.2f}x volume — no selling pressure"
                ),
            )

        return None

    # ── 2. Stopping Volume ───────────────────────────────────

    def detect_stopping_volume(
        self, df: pd.DataFrame
    ) -> Optional[PatternResult]:
        """
        Detect Stopping Volume.

        Bullish: After a downtrend, a high-volume bar with close near the high
        → Institutional buying absorbing supply.

        Bearish: After an uptrend, a high-volume bar with close near the low
        → Institutional selling absorbing demand.
        """
        if len(df) < 10:
            return None

        last = df.iloc[-1]
        recent_closes = df["close"].values[-10:-1]

        # Check for prior trend
        slope = np.polyfit(range(len(recent_closes)), recent_closes, 1)[0]

        spread = float(last["spread"])
        close_position = (float(last["close"]) - float(last["low"])) / max(spread, 0.01)

        # Bullish stopping volume: downtrend + high volume + close near high
        if slope < -0.05 and last["vol_ratio"] > 2.0 and close_position > 0.6:
            return PatternResult(
                name="VSA Stopping Volume Bull",
                direction="BULLISH",
                confidence=0.72,
                description=(
                    f"Stopping volume: {last['vol_ratio']:.1f}x vol after decline, "
                    f"close at {close_position*100:.0f}% of bar — absorption"
                ),
            )

        # Bearish stopping volume: uptrend + high volume + close near low
        if slope > 0.05 and last["vol_ratio"] > 2.0 and close_position < 0.4:
            return PatternResult(
                name="VSA Stopping Volume Bear",
                direction="BEARISH",
                confidence=0.72,
                description=(
                    f"Stopping volume: {last['vol_ratio']:.1f}x vol after rally, "
                    f"close at {close_position*100:.0f}% of bar — distribution"
                ),
            )

        return None

    # ── 3. Climactic Volume ──────────────────────────────────

    def detect_climactic_volume(
        self, df: pd.DataFrame
    ) -> Optional[PatternResult]:
        """
        Detect Climactic Volume (blow-off / selling climax).

        Selling Climax (bullish): Ultra-high volume + wide spread down bar
        after extended decline → capitulation, expect reversal up.

        Buying Climax (bearish): Ultra-high volume + wide spread up bar
        after extended rally → euphoria, expect reversal down.
        """
        if len(df) < 15:
            return None

        last = df.iloc[-1]
        recent_closes = df["close"].values[-15:-1]
        slope = np.polyfit(range(len(recent_closes)), recent_closes, 1)[0]

        # Selling climax: decline + massive volume + wide down bar
        if (
            slope < -0.1
            and last["vol_ratio"] > 3.0
            and last["spread_ratio"] > 1.5
            and last["is_down"]
        ):
            return PatternResult(
                name="VSA Selling Climax",
                direction="BULLISH",
                confidence=0.76,
                description=(
                    f"Selling climax: {last['vol_ratio']:.1f}x vol, "
                    f"{last['spread_ratio']:.1f}x spread — capitulation"
                ),
            )

        # Buying climax: rally + massive volume + wide up bar
        if (
            slope > 0.1
            and last["vol_ratio"] > 3.0
            and last["spread_ratio"] > 1.5
            and last["is_up"]
        ):
            return PatternResult(
                name="VSA Buying Climax",
                direction="BEARISH",
                confidence=0.76,
                description=(
                    f"Buying climax: {last['vol_ratio']:.1f}x vol, "
                    f"{last['spread_ratio']:.1f}x spread — euphoria top"
                ),
            )

        return None

    # ── 4. Effort vs Result ──────────────────────────────────

    def detect_effort_vs_result(
        self, df: pd.DataFrame
    ) -> Optional[PatternResult]:
        """
        Detect Effort vs Result divergence.

        Bullish: High volume (effort) but narrow down spread (no result)
        → Supply being absorbed; smart money buying.

        Bearish: High volume (effort) but narrow up spread (no result)
        → Demand being absorbed; smart money selling.
        """
        last = df.iloc[-1]

        # Bullish: high volume down bar with narrow spread
        if last["is_down"] and last["vol_ratio"] > 1.5 and last["spread_ratio"] < self._spread_tol(0.6):
            return PatternResult(
                name="VSA Effort No Result Bull",
                direction="BULLISH",
                confidence=0.70,
                description=(
                    f"Effort vs Result: {last['vol_ratio']:.1f}x volume but only "
                    f"{last['spread_ratio']:.2f}x spread down — supply absorbed"
                ),
            )

        # Bearish: high volume up bar with narrow spread
        if last["is_up"] and last["vol_ratio"] > 1.5 and last["spread_ratio"] < self._spread_tol(0.6):
            return PatternResult(
                name="VSA Effort No Result Bear",
                direction="BEARISH",
                confidence=0.70,
                description=(
                    f"Effort vs Result: {last['vol_ratio']:.1f}x volume but only "
                    f"{last['spread_ratio']:.2f}x spread up — demand absorbed"
                ),
            )

        return None

    # ── 5. VSA Trap (Upthrust / Spring variant) ──────────────

    def detect_vsa_trap(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """
        Detect VSA Upthrust/Spring with volume confirmation.

        VSA Spring: Wide-spread down bar breaking below support on
        high volume, but closing near the high → bullish trap.

        VSA Upthrust: Wide-spread up bar breaking above resistance on
        high volume, but closing near the low → bearish trap.
        """
        if len(df) < 20:
            return None

        last = df.iloc[-1]
        recent_lows = df["low"].values[-20:-1]
        recent_highs = df["high"].values[-20:-1]
        support = np.min(recent_lows)
        resistance = np.max(recent_highs)

        spread = float(last["spread"])
        close_pos = (float(last["close"]) - float(last["low"])) / max(spread, 0.01)

        # VSA Spring: low below support, close near high, high volume
        if (
            float(last["low"]) < support
            and close_pos > 0.6
            and last["vol_ratio"] > 1.3
        ):
            return PatternResult(
                name="VSA Spring",
                direction="BULLISH",
                confidence=0.75,
                description=(
                    f"VSA Spring: broke below {support:.2f}, "
                    f"closed at {close_pos*100:.0f}% of bar on "
                    f"{last['vol_ratio']:.1f}x volume"
                ),
            )

        # VSA Upthrust: high above resistance, close near low, high volume
        if (
            float(last["high"]) > resistance
            and close_pos < 0.4
            and last["vol_ratio"] > 1.3
        ):
            return PatternResult(
                name="VSA Upthrust",
                direction="BEARISH",
                confidence=0.75,
                description=(
                    f"VSA Upthrust: broke above {resistance:.2f}, "
                    f"closed at {close_pos*100:.0f}% of bar on "
                    f"{last['vol_ratio']:.1f}x volume"
                ),
            )

        return None

    # ── 6. Test Bar ──────────────────────────────────────────

    def detect_test_bar(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """
        Detect VSA Test Bar.

        Bullish Test: Down bar near recent lows on LOW volume
        → No sellers left; safe to go long.

        Bearish Test: Up bar near recent highs on LOW volume
        → No buyers left; safe to go short.
        """
        if len(df) < 10:
            return None

        last = df.iloc[-1]
        recent_low = np.min(df["low"].values[-10:-1])
        recent_high = np.max(df["high"].values[-10:-1])

        # Bullish test: near lows, low volume, closes up
        near_low = abs(float(last["low"]) - recent_low) / max(recent_low, 1) < self._tol(0.02)
        if near_low and last["vol_ratio"] < 0.6 and last["is_up"]:
            return PatternResult(
                name="VSA Test Bull",
                direction="BULLISH",
                confidence=0.68,
                description=(
                    f"Test bar near {recent_low:.2f} on "
                    f"{last['vol_ratio']:.2f}x volume — no sellers"
                ),
            )

        # Bearish test: near highs, low volume, closes down
        near_high = abs(float(last["high"]) - recent_high) / max(recent_high, 1) < self._tol(0.02)
        if near_high and last["vol_ratio"] < 0.6 and last["is_down"]:
            return PatternResult(
                name="VSA Test Bear",
                direction="BEARISH",
                confidence=0.68,
                description=(
                    f"Test bar near {recent_high:.2f} on "
                    f"{last['vol_ratio']:.2f}x volume — no buyers"
                ),
            )

        return None


# ══════════════════════════════════════════════════════════════
# SCANNER WRAPPER FUNCTIONS
# ══════════════════════════════════════════════════════════════


def _run_vsa_scan(
    stock_data: dict[str, pd.DataFrame],
    pattern_name: str,
    direction: str,
) -> list[str]:
    engine = VSAEngine()
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
            logger.error("VSA scan failed for %s: %s", ticker, e)
    return matches


def scan_no_supply(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    return _run_vsa_scan(stock_data, "VSA No Supply", "BULLISH")


def scan_no_demand(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    return _run_vsa_scan(stock_data, "VSA No Demand", "BEARISH")


def scan_stopping_vol_bull(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    return _run_vsa_scan(stock_data, "VSA Stopping Volume Bull", "BULLISH")


def scan_stopping_vol_bear(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    return _run_vsa_scan(stock_data, "VSA Stopping Volume Bear", "BEARISH")


def scan_selling_climax(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    return _run_vsa_scan(stock_data, "VSA Selling Climax", "BULLISH")


def scan_buying_climax(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    return _run_vsa_scan(stock_data, "VSA Buying Climax", "BEARISH")


def scan_effort_bull(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    return _run_vsa_scan(stock_data, "VSA Effort No Result Bull", "BULLISH")


def scan_effort_bear(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    return _run_vsa_scan(stock_data, "VSA Effort No Result Bear", "BEARISH")
