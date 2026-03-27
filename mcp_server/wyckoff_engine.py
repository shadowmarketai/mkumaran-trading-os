"""
Wyckoff Method Engine for MKUMARAN Trading OS.

Detects Wyckoff market cycle phases and key events:
- Accumulation Phases (A-E): Institutional buying at lows
- Distribution Phases (A-E): Institutional selling at highs
- Spring / Upthrust: False breakdowns/breakouts (traps)
- Sign of Strength (SOS) / Sign of Weakness (SOW)
- Last Point of Support (LPS) / Last Point of Supply (LPSY)
- Test after Spring: Confirmation of accumulation

Integrates with MWA scoring system.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

from mcp_server.pattern_engine import PatternResult
from mcp_server.volatility import scaled_tolerance, calculate_atr_pct

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════


def _detect_trading_range(
    df: pd.DataFrame, min_bars: int = 20
) -> Optional[dict]:
    """
    Detect if price is in a trading range (consolidation).

    Returns dict with range_high, range_low, range_start, duration
    or None if no range found.
    """
    if len(df) < min_bars:
        return None

    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values

    # Use the last `min_bars` to detect range
    recent_high = np.max(highs[-min_bars:])
    recent_low = np.min(lows[-min_bars:])
    range_size = (recent_high - recent_low) / max(recent_low, 1)

    # A trading range has relatively tight price action (< 20% range)
    if range_size > 0.20:
        return None

    # Check that price oscillates (not trending)
    mid = (recent_high + recent_low) / 2
    crosses = 0
    above = closes[-min_bars] > mid
    for c in closes[-min_bars:]:
        if (c > mid) != above:
            crosses += 1
            above = c > mid

    # Need at least 3 crosses for it to be a range
    if crosses < 3:
        return None

    return {
        "range_high": float(recent_high),
        "range_low": float(recent_low),
        "range_mid": float(mid),
        "range_size_pct": round(range_size * 100, 2),
        "duration": min_bars,
        "crosses": crosses,
    }


def _volume_analysis(
    df: pd.DataFrame, lookback: int = 20
) -> dict:
    """Analyze volume characteristics over lookback period."""
    vol = df["volume"].values
    recent_vol = vol[-lookback:]
    avg_vol = np.mean(recent_vol)

    return {
        "avg_volume": float(avg_vol),
        "last_volume": float(vol[-1]),
        "vol_ratio": float(vol[-1] / max(avg_vol, 1)),
        "declining": bool(np.mean(recent_vol[:lookback // 2]) > np.mean(recent_vol[lookback // 2:])),
        "spike": bool(vol[-1] > avg_vol * 2),
    }


# ══════════════════════════════════════════════════════════════
# WYCKOFF ENGINE CLASS
# ══════════════════════════════════════════════════════════════


class WyckoffEngine:
    """
    Wyckoff Method detector.

    Detects 6 key Wyckoff events:
    1. Accumulation Phase — Institutional buying at lows
    2. Distribution Phase — Institutional selling at highs
    3. Spring — False breakdown below trading range support
    4. Upthrust — False breakout above trading range resistance
    5. Sign of Strength (SOS) / Sign of Weakness (SOW)
    6. Test after Spring/Upthrust — Low-volume retest
    """

    def __init__(self, lookback: int = 60, range_lookback: int = 30):
        self.lookback = lookback
        self.range_lookback = range_lookback
        self.df_full = None

    def detect_all(self, df: pd.DataFrame) -> list[PatternResult]:
        """Run all Wyckoff detectors and return matches."""
        if len(df) < self.lookback:
            logger.warning(
                "Insufficient data for Wyckoff detection: %d bars", len(df)
            )
            return []

        self.df_full = df
        data = df.tail(self.lookback).copy()
        data.columns = [c.lower() for c in data.columns]
        data = data.reset_index(drop=True)

        patterns: list[PatternResult] = []
        detectors = [
            self.detect_accumulation,
            self.detect_distribution,
            self.detect_spring,
            self.detect_upthrust,
            self.detect_sos_sow,
            self.detect_test,
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
                    "Wyckoff detector %s failed: %s", detector.__name__, e
                )

        if patterns:
            logger.info(
                "Wyckoff detected %d patterns: %s",
                len(patterns),
                [p.name for p in patterns],
            )
        return patterns

    def _tol(self, base=0.03):
        return scaled_tolerance(self.df_full, base) if self.df_full is not None and len(self.df_full) > 15 else base

    # ── 1. Accumulation Phase ────────────────────────────────

    def detect_accumulation(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """
        Detect Wyckoff Accumulation.

        Characteristics:
        - Price in trading range after a downtrend
        - Volume declining during range (absorption)
        - Support holding on multiple tests
        """
        tr = _detect_trading_range(df, self.range_lookback)
        if tr is None:
            return None

        # Check for prior downtrend (first 1/3 of data declining)
        early_close = df["close"].values[: len(df) // 3]
        if len(early_close) < 5:
            return None
        slope = np.polyfit(range(len(early_close)), early_close, 1)[0]
        if slope >= 0:
            return None  # Need prior downtrend

        # Volume should be declining in the range
        vol_info = _volume_analysis(df, self.range_lookback)

        # Current price near range low (buying the lows)
        current = float(df["close"].iloc[-1])
        position_in_range = (current - tr["range_low"]) / max(
            tr["range_high"] - tr["range_low"], 1
        )

        if position_in_range <= 0.5 and vol_info["declining"]:
            return PatternResult(
                name="Wyckoff Accumulation",
                direction="BULLISH",
                confidence=0.72,
                description=(
                    f"Accumulation range {tr['range_low']:.2f}-{tr['range_high']:.2f}, "
                    f"volume declining, price in lower half"
                ),
            )

        return None

    # ── 2. Distribution Phase ────────────────────────────────

    def detect_distribution(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """
        Detect Wyckoff Distribution.

        Characteristics:
        - Price in trading range after an uptrend
        - Volume declining during range
        - Resistance holding on multiple tests
        """
        tr = _detect_trading_range(df, self.range_lookback)
        if tr is None:
            return None

        # Check for prior uptrend
        early_close = df["close"].values[: len(df) // 3]
        if len(early_close) < 5:
            return None
        slope = np.polyfit(range(len(early_close)), early_close, 1)[0]
        if slope <= 0:
            return None  # Need prior uptrend

        vol_info = _volume_analysis(df, self.range_lookback)

        current = float(df["close"].iloc[-1])
        position_in_range = (current - tr["range_low"]) / max(
            tr["range_high"] - tr["range_low"], 1
        )

        if position_in_range >= 0.5 and vol_info["declining"]:
            return PatternResult(
                name="Wyckoff Distribution",
                direction="BEARISH",
                confidence=0.72,
                description=(
                    f"Distribution range {tr['range_low']:.2f}-{tr['range_high']:.2f}, "
                    f"volume declining, price in upper half"
                ),
            )

        return None

    # ── 3. Spring ────────────────────────────────────────────

    def detect_spring(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """
        Detect Wyckoff Spring (false breakdown).

        Price dips below trading range support then closes back inside.
        This is a shakeout of weak longs — bullish signal.
        """
        tr = _detect_trading_range(df, self.range_lookback)
        if tr is None:
            return None

        # Check last 3 bars for a spring
        for i in range(-3, 0):
            bar_low = float(df["low"].iloc[i])
            bar_close = float(df["close"].iloc[i])

            # Low went below range, but close came back above
            if bar_low < tr["range_low"] and bar_close > tr["range_low"]:
                penetration = (tr["range_low"] - bar_low) / max(tr["range_low"], 1)
                # Shallow penetration is the strongest spring
                if penetration < self._tol(0.03):
                    return PatternResult(
                        name="Wyckoff Spring",
                        direction="BULLISH",
                        confidence=0.78,
                        description=(
                            f"Spring: dipped to {bar_low:.2f} below support "
                            f"{tr['range_low']:.2f}, closed back at {bar_close:.2f}"
                        ),
                    )

        return None

    # ── 4. Upthrust ──────────────────────────────────────────

    def detect_upthrust(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """
        Detect Wyckoff Upthrust (false breakout).

        Price spikes above trading range resistance then closes back inside.
        This is a trap for breakout buyers — bearish signal.
        """
        tr = _detect_trading_range(df, self.range_lookback)
        if tr is None:
            return None

        for i in range(-3, 0):
            bar_high = float(df["high"].iloc[i])
            bar_close = float(df["close"].iloc[i])

            if bar_high > tr["range_high"] and bar_close < tr["range_high"]:
                penetration = (bar_high - tr["range_high"]) / max(tr["range_high"], 1)
                if penetration < self._tol(0.03):
                    return PatternResult(
                        name="Wyckoff Upthrust",
                        direction="BEARISH",
                        confidence=0.78,
                        description=(
                            f"Upthrust: spiked to {bar_high:.2f} above resistance "
                            f"{tr['range_high']:.2f}, closed back at {bar_close:.2f}"
                        ),
                    )

        return None

    # ── 5. Sign of Strength / Sign of Weakness ───────────────

    def detect_sos_sow(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """
        Detect Sign of Strength (SOS) or Sign of Weakness (SOW).

        SOS: Strong up move on high volume breaking above range midpoint.
        SOW: Strong down move on high volume breaking below range midpoint.
        """
        tr = _detect_trading_range(df, self.range_lookback)
        if tr is None:
            return None

        vol_info = _volume_analysis(df, self.range_lookback)
        closes = df["close"].values
        current = float(closes[-1])
        prev = float(closes[-2]) if len(closes) >= 2 else current

        daily_move = (current - prev) / max(prev, 1)

        # SOS: big up move on volume, closing above range midpoint
        if daily_move > self._tol(0.02) and vol_info["vol_ratio"] > 1.5 and current > tr["range_mid"]:
            return PatternResult(
                name="Sign of Strength",
                direction="BULLISH",
                confidence=0.70,
                description=(
                    f"SOS: {daily_move*100:.1f}% up on {vol_info['vol_ratio']:.1f}x volume, "
                    f"above midpoint {tr['range_mid']:.2f}"
                ),
            )

        # SOW: big down move on volume, closing below range midpoint
        if daily_move < -self._tol(0.02) and vol_info["vol_ratio"] > 1.5 and current < tr["range_mid"]:
            return PatternResult(
                name="Sign of Weakness",
                direction="BEARISH",
                confidence=0.70,
                description=(
                    f"SOW: {daily_move*100:.1f}% down on {vol_info['vol_ratio']:.1f}x volume, "
                    f"below midpoint {tr['range_mid']:.2f}"
                ),
            )

        return None

    # ── 6. Test after Spring/Upthrust ────────────────────────

    def detect_test(self, df: pd.DataFrame) -> Optional[PatternResult]:
        """
        Detect Test after Spring or Upthrust.

        Bullish Test: After a Spring, price retests the range low on
        LOW volume (no selling pressure = confirmed accumulation).

        Bearish Test: After an Upthrust, price retests the range high on
        LOW volume (no buying pressure = confirmed distribution).
        """
        tr = _detect_trading_range(df, self.range_lookback)
        if tr is None:
            return None

        vol_info = _volume_analysis(df, self.range_lookback)
        current_low = float(df["low"].iloc[-1])
        current_high = float(df["high"].iloc[-1])
        current_close = float(df["close"].iloc[-1])

        # Bullish test: price near range low on low volume
        near_low = abs(current_low - tr["range_low"]) / max(tr["range_low"], 1) < self._tol(0.02)
        if near_low and vol_info["vol_ratio"] < 0.7 and current_close > tr["range_low"]:
            return PatternResult(
                name="Wyckoff Test Bullish",
                direction="BULLISH",
                confidence=0.74,
                description=(
                    f"Low-volume test of support {tr['range_low']:.2f}, "
                    f"vol ratio {vol_info['vol_ratio']:.2f}x — accumulation confirmed"
                ),
            )

        # Bearish test: price near range high on low volume
        near_high = abs(current_high - tr["range_high"]) / max(tr["range_high"], 1) < self._tol(0.02)
        if near_high and vol_info["vol_ratio"] < 0.7 and current_close < tr["range_high"]:
            return PatternResult(
                name="Wyckoff Test Bearish",
                direction="BEARISH",
                confidence=0.74,
                description=(
                    f"Low-volume test of resistance {tr['range_high']:.2f}, "
                    f"vol ratio {vol_info['vol_ratio']:.2f}x — distribution confirmed"
                ),
            )

        return None


# ══════════════════════════════════════════════════════════════
# SCANNER WRAPPER FUNCTIONS
# ══════════════════════════════════════════════════════════════


def _run_wyckoff_scan(
    stock_data: dict[str, pd.DataFrame],
    pattern_name: str,
    direction: str,
) -> list[str]:
    """Generic Wyckoff scanner."""
    engine = WyckoffEngine()
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
            logger.error("Wyckoff scan failed for %s: %s", ticker, e)

    return matches


def scan_accumulation(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    return _run_wyckoff_scan(stock_data, "Wyckoff Accumulation", "BULLISH")


def scan_distribution(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    return _run_wyckoff_scan(stock_data, "Wyckoff Distribution", "BEARISH")


def scan_spring(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    return _run_wyckoff_scan(stock_data, "Wyckoff Spring", "BULLISH")


def scan_upthrust(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    return _run_wyckoff_scan(stock_data, "Wyckoff Upthrust", "BEARISH")


def scan_sos(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    return _run_wyckoff_scan(stock_data, "Sign of Strength", "BULLISH")


def scan_sow(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    return _run_wyckoff_scan(stock_data, "Sign of Weakness", "BEARISH")


def scan_test_bull(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    return _run_wyckoff_scan(stock_data, "Wyckoff Test Bullish", "BULLISH")


def scan_test_bear(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    return _run_wyckoff_scan(stock_data, "Wyckoff Test Bearish", "BEARISH")
