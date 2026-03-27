"""
RL-Inspired Engine for MKUMARAN Trading OS.

Extracts the intelligence from reinforcement learning trading strategies
(SAC/TD3 state representation and reward logic) into deterministic rules
using only numpy/pandas. Zero new dependencies.

Detectors:
1. Regime Trend — Volatility + trend strength classification
2. VWAP Deviation — Price vs VWAP mean-reversion signals
3. Momentum Score — Composite returns + RSI + volume ratio
4. Risk-Reward Setup — ATR-based SL/TP with 2:1+ R:R
5. Regime Shift — Ranging-to-Trending transition detection
6. Optimal Entry — Multi-factor confluence (regime + VWAP + momentum)
"""

import logging

import numpy as np
import pandas as pd

from mcp_server.pattern_engine import PatternResult
from mcp_server.volatility import scaled_tolerance, calculate_atr

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS (from RL state representation)
# ══════════════════════════════════════════════════════════════


def _compute_vwap(df: pd.DataFrame) -> pd.Series:
    """
    Compute Volume Weighted Average Price.

    Derived from IntradayEnv observation space — VWAP is a core
    feature in the RL agent's state vector for mean-reversion signals.
    """
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    cum_tp_vol = (typical_price * df["volume"]).cumsum()
    cum_vol = df["volume"].cumsum()
    vwap = cum_tp_vol / cum_vol.replace(0, np.nan)
    return vwap.fillna(typical_price)


def _calculate_regime(df: pd.DataFrame, window: int = 50) -> str:
    """
    Classify market regime from price action.

    From the RL agent's _detect_regime() method: uses SMA slope
    and volatility ratio to classify TRENDING_UP / TRENDING_DOWN / RANGING.
    """
    if len(df) < window:
        return "RANGING"

    closes = df["close"].values[-window:]
    sma = np.mean(closes)
    slope = np.polyfit(range(len(closes)), closes, 1)[0]

    # Normalize slope by price level
    norm_slope = slope / max(sma, 1) * 100

    # Volatility check: high vol = ranging
    std = np.std(closes[-20:]) / max(sma, 1) * 100
    atr_pct = std  # simplified ATR proxy

    if atr_pct > 3.0 and abs(norm_slope) < 0.5:
        return "RANGING"
    elif norm_slope > 0.3:
        return "TRENDING_UP"
    elif norm_slope < -0.3:
        return "TRENDING_DOWN"
    return "RANGING"


def _normalize_momentum(df: pd.DataFrame, window: int = 14) -> float:
    """
    Composite momentum score from returns + RSI + volume ratio.

    Extracted from SAC agent state vector: these three features
    are the primary momentum indicators in the observation space.
    Returns score in [-1, 1] range.
    """
    if len(df) < window + 1:
        return 0.0

    closes = df["close"].values
    volumes = df["volume"].values

    # Returns component (5-day)
    ret_5 = (closes[-1] - closes[-5]) / max(abs(closes[-5]), 1)
    ret_score = np.clip(ret_5 * 10, -1, 1)

    # RSI component
    deltas = np.diff(closes[-(window + 1):])
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains) if len(gains) > 0 else 0
    avg_loss = np.mean(losses) if len(losses) > 0 else 0.001
    rs = avg_gain / max(avg_loss, 0.001)
    rsi = 100 - (100 / (1 + rs))
    rsi_score = (rsi - 50) / 50  # normalize to [-1, 1]

    # Volume ratio component
    vol_avg = np.mean(volumes[-20:]) if len(volumes) >= 20 else np.mean(volumes)
    vol_ratio = volumes[-1] / max(vol_avg, 1)
    vol_score = np.clip((vol_ratio - 1) * 0.5, -0.5, 0.5)

    # Weighted composite
    momentum = 0.4 * ret_score + 0.4 * rsi_score + 0.2 * vol_score
    return float(np.clip(momentum, -1, 1))


def _calculate_risk_reward(
    df: pd.DataFrame, atr_mult: float = 2.0
) -> tuple[float, float, float, float]:
    """
    Calculate entry, stop loss, target, and R:R ratio using ATR.

    From the RL reward function: uses ATR-scaled risk management
    for position sizing and reward calculation.

    Returns: (entry, stop_loss, target, rr_ratio)
    """
    atr = calculate_atr(df)
    if atr <= 0:
        return 0.0, 0.0, 0.0, 0.0

    entry = float(df["close"].iloc[-1])
    sl = entry - atr * atr_mult
    tp = entry + atr * atr_mult * 2  # 2:1 R:R minimum
    risk = entry - sl
    reward = tp - entry
    rr = reward / max(risk, 0.01)

    return entry, sl, tp, float(rr)


# ══════════════════════════════════════════════════════════════
# RL ENGINE CLASS
# ══════════════════════════════════════════════════════════════


class RLEngine:
    """
    RL-inspired detector engine.

    Extracts decision logic from reinforcement learning trading strategies
    into 6 deterministic detectors that follow the same PatternResult
    interface as all other engines.
    """

    def __init__(self, lookback: int = 60):
        self.lookback = lookback
        self.df_full = None

    def detect_all(self, df: pd.DataFrame) -> list[PatternResult]:
        """Run all RL detectors and return matches."""
        if len(df) < self.lookback:
            logger.warning("Insufficient data for RL detection: %d bars", len(df))
            return []

        self.df_full = df
        data = df.tail(self.lookback).copy()
        patterns: list[PatternResult] = []

        detectors = [
            self.detect_regime_trend,
            self.detect_vwap_deviation,
            self.detect_momentum_score,
            self.detect_risk_reward_setup,
            self.detect_regime_shift,
            self.detect_optimal_entry,
        ]

        for detector in detectors:
            try:
                result = detector(data)
                if result is not None:
                    patterns.append(result)
            except Exception as e:
                logger.error("RL detector %s failed: %s", detector.__name__, e)

        if patterns:
            logger.info("RL detected %d patterns: %s", len(patterns), [p.name for p in patterns])

        return patterns

    def _tol(self, base: float = 0.03) -> float:
        return scaled_tolerance(self.df_full, base) if self.df_full is not None and len(self.df_full) > 15 else base

    def detect_regime_trend(self, df: pd.DataFrame) -> PatternResult | None:
        """
        Detect regime-based trend signal.

        From RL agent's regime classifier: combines volatility regime
        with trend strength for directional bias.
        """
        regime = _calculate_regime(df)
        if regime == "RANGING":
            return None

        closes = df["close"].values
        slope = np.polyfit(range(len(closes[-20:])), closes[-20:], 1)[0]
        trend_strength = abs(slope) / max(np.mean(closes[-20:]), 1) * 100

        if trend_strength < 0.2:
            return None

        direction = "BULLISH" if regime == "TRENDING_UP" else "BEARISH"
        confidence = min(0.72 + trend_strength * 0.02, 0.85)

        return PatternResult(
            name="RL Regime Trend",
            direction=direction,
            confidence=round(confidence, 2),
            description=f"Regime: {regime} | Trend strength: {trend_strength:.2f}%",
        )

    def detect_vwap_deviation(self, df: pd.DataFrame) -> PatternResult | None:
        """
        Detect VWAP mean-reversion signal.

        From IntradayEnv: price deviation from VWAP is a primary
        feature for mean-reversion entries in the RL state space.
        """
        vwap = _compute_vwap(df)
        price = df["close"].iloc[-1]
        vwap_val = vwap.iloc[-1]

        if vwap_val <= 0:
            return None

        deviation = (price - vwap_val) / vwap_val * 100
        threshold = self._tol(0.015) * 100  # convert to percentage

        if abs(deviation) < threshold:
            return None

        # Mean-reversion: price below VWAP = bullish (expect revert up)
        if deviation < -threshold:
            return PatternResult(
                name="RL VWAP Deviation",
                direction="BULLISH",
                confidence=min(0.68 + abs(deviation) * 0.01, 0.82),
                description=f"Price {deviation:.2f}% below VWAP — mean reversion expected",
            )
        elif deviation > threshold:
            return PatternResult(
                name="RL VWAP Deviation",
                direction="BEARISH",
                confidence=min(0.68 + abs(deviation) * 0.01, 0.82),
                description=f"Price {deviation:.2f}% above VWAP — mean reversion expected",
            )
        return None

    def detect_momentum_score(self, df: pd.DataFrame) -> PatternResult | None:
        """
        Detect momentum-based signal from composite score.

        From SAC state vector: returns + RSI + volume ratio composite
        score determines the agent's directional conviction.
        """
        score = _normalize_momentum(df)

        if abs(score) < 0.3:
            return None

        direction = "BULLISH" if score > 0 else "BEARISH"
        confidence = min(0.70 + abs(score) * 0.15, 0.85)

        return PatternResult(
            name="RL Momentum Score",
            direction=direction,
            confidence=round(confidence, 2),
            description=f"Composite momentum: {score:.3f} (returns + RSI + volume)",
        )

    def detect_risk_reward_setup(self, df: pd.DataFrame) -> PatternResult | None:
        """
        Detect favorable risk-reward setup using ATR.

        From RL reward function: the agent optimizes for trades
        with 2:1+ risk-reward ratios using ATR-based stops.
        """
        entry, sl, tp, rr = _calculate_risk_reward(df)
        if rr < 2.0:
            return None

        # Determine direction from recent trend
        closes = df["close"].values
        short_trend = (closes[-1] - closes[-5]) / max(abs(closes[-5]), 1)

        if abs(short_trend) < 0.005:
            return None

        direction = "BULLISH" if short_trend > 0 else "BEARISH"
        confidence = min(0.65 + (rr - 2.0) * 0.05, 0.80)

        return PatternResult(
            name="RL Risk-Reward Setup",
            direction=direction,
            confidence=round(confidence, 2),
            description=f"Entry: {entry:.2f} SL: {sl:.2f} TP: {tp:.2f} R:R={rr:.1f}",
        )

    def detect_regime_shift(self, df: pd.DataFrame) -> PatternResult | None:
        """
        Detect ranging-to-trending regime transition.

        From RL regime classifier: transitions from ranging to trending
        are the highest-value signals (volatility expansion).
        """
        if len(df) < 40:
            return None

        # Check if previous window was ranging
        prev_regime = _calculate_regime(df.iloc[:-10], window=30)
        curr_regime = _calculate_regime(df, window=30)

        if prev_regime != "RANGING":
            return None
        if curr_regime == "RANGING":
            return None

        direction = "BULLISH" if curr_regime == "TRENDING_UP" else "BEARISH"

        return PatternResult(
            name="RL Regime Shift",
            direction=direction,
            confidence=0.75,
            description=f"Regime shift: RANGING -> {curr_regime}",
        )

    def detect_optimal_entry(self, df: pd.DataFrame) -> PatternResult | None:
        """
        Detect multi-factor optimal entry confluence.

        Combines regime + VWAP + momentum for highest-conviction
        signals — equivalent to the RL agent's highest-reward actions.
        """
        regime = _calculate_regime(df)
        if regime == "RANGING":
            return None

        momentum = _normalize_momentum(df)
        if abs(momentum) < 0.2:
            return None

        vwap = _compute_vwap(df)
        price = df["close"].iloc[-1]
        vwap_val = vwap.iloc[-1]
        vwap_dev = (price - vwap_val) / max(vwap_val, 1) * 100

        # All factors must align
        if regime == "TRENDING_UP" and momentum > 0.2 and vwap_dev > -1.0:
            confidence = min(0.80 + abs(momentum) * 0.05, 0.90)
            return PatternResult(
                name="RL Optimal Entry",
                direction="BULLISH",
                confidence=round(confidence, 2),
                description=f"Confluence: {regime} + momentum={momentum:.2f} + VWAP_dev={vwap_dev:.1f}%",
            )
        elif regime == "TRENDING_DOWN" and momentum < -0.2 and vwap_dev < 1.0:
            confidence = min(0.80 + abs(momentum) * 0.05, 0.90)
            return PatternResult(
                name="RL Optimal Entry",
                direction="BEARISH",
                confidence=round(confidence, 2),
                description=f"Confluence: {regime} + momentum={momentum:.2f} + VWAP_dev={vwap_dev:.1f}%",
            )
        return None


# ══════════════════════════════════════════════════════════════
# SCANNER WRAPPER FUNCTIONS
# ══════════════════════════════════════════════════════════════


def _run_rl_scan(
    stock_data: dict[str, pd.DataFrame],
    pattern_name: str,
    direction: str,
) -> list[str]:
    """Generic RL scanner — matches patterns by name and direction."""
    engine = RLEngine()
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
            logger.error("RL scan failed for %s: %s", ticker, e)
    return matches


def scan_rl_trend_bull(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    return _run_rl_scan(stock_data, "RL Regime Trend", "BULLISH")


def scan_rl_trend_bear(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    return _run_rl_scan(stock_data, "RL Regime Trend", "BEARISH")


def scan_rl_vwap_bull(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    return _run_rl_scan(stock_data, "RL VWAP Deviation", "BULLISH")


def scan_rl_vwap_bear(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    return _run_rl_scan(stock_data, "RL VWAP Deviation", "BEARISH")


def scan_rl_momentum_bull(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    return _run_rl_scan(stock_data, "RL Momentum Score", "BULLISH")


def scan_rl_momentum_bear(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    return _run_rl_scan(stock_data, "RL Momentum Score", "BEARISH")


def scan_rl_optimal_entry_bull(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    return _run_rl_scan(stock_data, "RL Optimal Entry", "BULLISH")


def scan_rl_optimal_entry_bear(stock_data: dict[str, pd.DataFrame]) -> list[str]:
    return _run_rl_scan(stock_data, "RL Optimal Entry", "BEARISH")
