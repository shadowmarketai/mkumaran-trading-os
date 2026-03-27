"""
Harmonic Pattern Engine for MKUMARAN Trading OS.

Detects Fibonacci-based geometric price patterns:
- Gartley (222): The most reliable harmonic
- Butterfly: Extension pattern for reversals at extremes
- Bat: Deep retracement pattern (0.886 XA)
- Crab: Extreme extension pattern (1.618 XA)
- Cypher: Anti-harmonic pattern with unique ratios

Each pattern provides precise entry, stop loss, and target levels
that integrate with the RRMS position sizing engine.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

from mcp_server.pattern_engine import PatternResult
from mcp_server.volatility import zigzag_threshold

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# FIBONACCI RATIO DEFINITIONS
# ══════════════════════════════════════════════════════════════

# Each pattern: {leg: (min_ratio, max_ratio)}
# Ratios are of the relevant prior leg

HARMONIC_RATIOS = {
    "Gartley": {
        "AB_XA": (0.618, 0.618),   # AB retraces 61.8% of XA
        "BC_AB": (0.382, 0.886),    # BC retraces 38.2-88.6% of AB
        "CD_BC": (1.272, 1.618),    # CD extends 127.2-161.8% of BC
        "AD_XA": (0.786, 0.786),    # D completes at 78.6% of XA
        "tolerance": 0.05,
    },
    "Butterfly": {
        "AB_XA": (0.786, 0.786),
        "BC_AB": (0.382, 0.886),
        "CD_BC": (1.618, 2.618),
        "AD_XA": (1.272, 1.618),    # D extends beyond X
        "tolerance": 0.06,
    },
    "Bat": {
        "AB_XA": (0.382, 0.50),
        "BC_AB": (0.382, 0.886),
        "CD_BC": (1.618, 2.618),
        "AD_XA": (0.886, 0.886),
        "tolerance": 0.05,
    },
    "Crab": {
        "AB_XA": (0.382, 0.618),
        "BC_AB": (0.382, 0.886),
        "CD_BC": (2.240, 3.618),
        "AD_XA": (1.618, 1.618),    # Extreme extension
        "tolerance": 0.07,
    },
    "Cypher": {
        "AB_XA": (0.382, 0.618),
        "BC_AB": (1.130, 1.414),    # BC extends beyond A
        "CD_XC": (0.786, 0.786),    # D retraces 78.6% of XC (unique)
        "tolerance": 0.06,
    },
}


# ══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════


def _find_zigzag_points(
    df: pd.DataFrame, pct_threshold: float = 3.0, max_points: int = 5
) -> list[tuple[int, float]]:
    """
    Find zigzag swing points (XABCD) using percentage threshold.

    Returns list of (index, price) tuples representing alternating
    highs and lows, most recent last. Returns up to max_points.
    """
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    n = len(closes)

    if n < 20:
        return []

    # Build zigzag
    points: list[tuple[int, float]] = []
    direction = 0  # 1 = looking for high, -1 = looking for low
    last_idx = 0
    last_price = float(closes[0])

    for i in range(1, n):
        change = (closes[i] - last_price) / max(abs(last_price), 1) * 100

        if direction == 0:
            if change >= pct_threshold:
                points.append((last_idx, last_price))
                direction = 1
                last_idx = i
                last_price = float(highs[i])
            elif change <= -pct_threshold:
                points.append((last_idx, last_price))
                direction = -1
                last_idx = i
                last_price = float(lows[i])
        elif direction == 1:
            if float(highs[i]) > last_price:
                last_idx = i
                last_price = float(highs[i])
            elif (last_price - closes[i]) / max(last_price, 1) * 100 >= pct_threshold:
                points.append((last_idx, last_price))
                direction = -1
                last_idx = i
                last_price = float(lows[i])
        elif direction == -1:
            if float(lows[i]) < last_price:
                last_idx = i
                last_price = float(lows[i])
            elif (closes[i] - last_price) / max(abs(last_price), 1) * 100 >= pct_threshold:
                points.append((last_idx, last_price))
                direction = 1
                last_idx = i
                last_price = float(highs[i])

    points.append((last_idx, last_price))

    # Return the last max_points
    return points[-max_points:] if len(points) >= max_points else points


def _check_ratio(
    actual: float,
    expected_min: float,
    expected_max: float,
    tolerance: float,
) -> bool:
    """Check if a ratio is within expected range +/- tolerance."""
    return (expected_min - tolerance) <= actual <= (expected_max + tolerance)


def _get_retracement(a: float, b: float, c: float) -> float:
    """Calculate how much C retraces the move from A to B. Returns ratio."""
    move = b - a
    if abs(move) < 0.01:
        return 0.0
    return abs(c - b) / abs(move)


# ══════════════════════════════════════════════════════════════
# HARMONIC ENGINE CLASS
# ══════════════════════════════════════════════════════════════


class HarmonicEngine:
    """
    Harmonic Pattern detector.

    Detects 5 harmonic patterns:
    1. Gartley — Most reliable, moderate retracement
    2. Butterfly — Extension reversal at extremes
    3. Bat — Deep retracement (0.886)
    4. Crab — Extreme extension (1.618)
    5. Cypher — Anti-harmonic with unique XC ratio
    """

    def __init__(self, lookback: int = 120, zigzag_pct: float = 3.0):
        self.lookback = lookback
        self.zigzag_pct = zigzag_pct
        self.df_full = None

    def detect_all(self, df: pd.DataFrame) -> list[PatternResult]:
        """Run all harmonic detectors and return matches."""
        if len(df) < self.lookback:
            logger.warning(
                "Insufficient data for harmonic detection: %d bars", len(df)
            )
            return []

        data = df.tail(self.lookback).copy()
        data.columns = [c.lower() for c in data.columns]
        data = data.reset_index(drop=True)
        self.df_full = df

        # Use dynamic zigzag threshold based on volatility
        dynamic_pct = zigzag_threshold(data) if len(data) > 15 else self.zigzag_pct

        points = _find_zigzag_points(data, dynamic_pct, max_points=5)
        if len(points) < 5:
            return []

        # Extract XABCD
        x_price = points[-5][1]
        a_price = points[-4][1]
        b_price = points[-3][1]
        c_price = points[-2][1]
        d_price = points[-1][1]

        patterns: list[PatternResult] = []

        for name in ["Gartley", "Butterfly", "Bat", "Crab", "Cypher"]:
            try:
                result = self._check_pattern(
                    name, x_price, a_price, b_price, c_price, d_price
                )
                if result is not None:
                    patterns.append(result)
            except Exception as e:
                logger.error("Harmonic %s check failed: %s", name, e)

        if patterns:
            logger.info(
                "Harmonic detected %d patterns: %s",
                len(patterns),
                [p.name for p in patterns],
            )
        return patterns

    def _check_pattern(
        self,
        name: str,
        x: float,
        a: float,
        b: float,
        c: float,
        d: float,
    ) -> Optional[PatternResult]:
        """Check if XABCD points match a specific harmonic pattern."""
        ratios = HARMONIC_RATIOS[name]
        tol = ratios["tolerance"]

        xa_move = a - x
        ab_move = b - a
        bc_move = c - b

        if abs(xa_move) < 0.01 or abs(ab_move) < 0.01:
            return None

        # AB / XA ratio
        ab_xa = abs(ab_move) / abs(xa_move)
        if not _check_ratio(ab_xa, *ratios["AB_XA"], tol):
            return None

        # BC / AB ratio
        if abs(ab_move) > 0.01:
            bc_ab = abs(bc_move) / abs(ab_move)
            if not _check_ratio(bc_ab, *ratios["BC_AB"], tol):
                return None

        # Cypher uses CD/XC instead of CD/BC and AD/XA
        if name == "Cypher":
            xc_move = c - x
            if abs(xc_move) < 0.01:
                return None
            cd_xc = abs(d - c) / abs(xc_move)
            if not _check_ratio(cd_xc, *ratios["CD_XC"], tol):
                return None
        else:
            # CD / BC ratio
            cd_move = d - c
            if abs(bc_move) > 0.01:
                cd_bc = abs(cd_move) / abs(bc_move)
                if not _check_ratio(cd_bc, *ratios["CD_BC"], tol):
                    return None

            # AD / XA ratio
            ad_move = d - a
            ad_xa = abs(ad_move) / abs(xa_move)
            if not _check_ratio(ad_xa, *ratios["AD_XA"], tol):
                return None

        # Determine direction: bullish if D is a low (buy at D), bearish if D is a high
        is_bullish = xa_move > 0  # X<A means bullish pattern (D is a buy point)

        confidence_map = {
            "Gartley": 0.75,
            "Bat": 0.72,
            "Butterfly": 0.70,
            "Crab": 0.68,
            "Cypher": 0.66,
        }

        direction = "BULLISH" if is_bullish else "BEARISH"
        pattern_name = f"Harmonic {name} {'Bull' if is_bullish else 'Bear'}"

        return PatternResult(
            name=pattern_name,
            direction=direction,
            confidence=confidence_map.get(name, 0.65),
            description=(
                f"{name} XABCD: X={x:.2f} A={a:.2f} B={b:.2f} "
                f"C={c:.2f} D={d:.2f} | AB/XA={ab_xa:.3f}"
            ),
        )


# ══════════════════════════════════════════════════════════════
# SCANNER WRAPPER FUNCTIONS
# ══════════════════════════════════════════════════════════════


def _run_harmonic_scan(
    stock_data: dict[str, pd.DataFrame],
    pattern_prefix: str,
    direction: str,
) -> list[str]:
    """Generic harmonic scanner — matches patterns starting with prefix."""
    engine = HarmonicEngine()
    matches: list[str] = []
    for ticker, df in stock_data.items():
        try:
            if len(df) < engine.lookback:
                continue
            patterns = engine.detect_all(df)
            for p in patterns:
                if p.name.startswith(pattern_prefix) and p.direction == direction:
                    matches.append(ticker)
                    break
        except Exception as e:
            logger.error("Harmonic scan failed for %s: %s", ticker, e)
    return matches


def scan_harmonic_gartley_bull(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    return _run_harmonic_scan(stock_data, "Harmonic Gartley", "BULLISH")


def scan_harmonic_gartley_bear(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    return _run_harmonic_scan(stock_data, "Harmonic Gartley", "BEARISH")


def scan_harmonic_bat_bull(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    return _run_harmonic_scan(stock_data, "Harmonic Bat", "BULLISH")


def scan_harmonic_bat_bear(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    return _run_harmonic_scan(stock_data, "Harmonic Bat", "BEARISH")


def scan_harmonic_any_bull(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for any bullish harmonic pattern (Gartley/Butterfly/Bat/Crab/Cypher)."""
    return _run_harmonic_scan(stock_data, "Harmonic", "BULLISH")


def scan_harmonic_any_bear(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    """Scan for any bearish harmonic pattern."""
    return _run_harmonic_scan(stock_data, "Harmonic", "BEARISH")
