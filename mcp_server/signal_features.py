"""
Signal Feature Extraction — captures the entry-time context for every signal.

Produces a canonical feature dict used by:
  - Postmortem RCA engine (signal_postmortem.py)
  - Vector similarity search (signal_similarity.py)
  - Predictive loss probability model (signal_predictor.py)
  - Bayesian scanner learner (scanner_bayesian.py)

All computations are pure-pandas/numpy — zero external deps beyond what's
already in requirements.txt (pandas, numpy, ta).
"""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# Feature vector key order — MUST stay stable; append-only for compatibility.
FEATURE_KEYS: list[str] = [
    "rsi",
    "adx",
    "atr_pct",
    "volume_ratio",
    "vwap_dev",
    "momentum_5d",
    "macd_hist",
    "bb_width",
    "ema_9_slope",
    "ema_21_slope",
    "regime_trending_up",   # one-hot
    "regime_trending_down", # one-hot
    "regime_ranging",       # one-hot
    "regime_volatile",      # one-hot
    "mwa_bull_pct",
    "mwa_bear_pct",
    "scanner_count",
    "bull_scanner_count",
    "bear_scanner_count",
    "ai_confidence",
    "rrr",
    "direction_long",       # one-hot
    "direction_short",      # one-hot
    "segment_nse",          # one-hot
    "segment_nfo",
    "segment_mcx",
    "segment_cds",
    "segment_bse",
]


def _safe_last(series: pd.Series, default: float = 0.0) -> float:
    """Return the last non-NaN float from a series, or default."""
    try:
        if series is None or len(series) == 0:
            return default
        val = series.dropna().iloc[-1] if series.dropna().size else default
        if val is None or (isinstance(val, float) and (math.isnan(val) or math.isinf(val))):
            return default
        return float(val)
    except Exception:
        return default


def _compute_rsi(close: pd.Series, period: int = 14) -> float:
    """Wilder RSI."""
    if len(close) < period + 1:
        return 50.0
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    rsi = 100 - (100 / (1 + rs))
    return _safe_last(rsi, 50.0)


def _compute_adx(df: pd.DataFrame, period: int = 14) -> float:
    """Classic Wilder ADX — needs high/low/close."""
    if len(df) < period * 2:
        return 20.0
    high = df["high"]
    low = df["low"]
    close = df["close"]

    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr.replace(0, 1e-10))
    minus_di = 100 * (minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr.replace(0, 1e-10))

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-10)
    adx = dx.ewm(alpha=1 / period, adjust=False).mean()
    return _safe_last(adx, 20.0)


def _compute_atr_pct(df: pd.DataFrame, period: int = 14) -> float:
    """ATR as percentage of close."""
    if len(df) < period + 1:
        return 1.0
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr = pd.concat(
        [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(period).mean()
    last_close = _safe_last(close, 1.0)
    if last_close <= 0:
        return 1.0
    return _safe_last(atr, 0.0) / last_close * 100


def _compute_volume_ratio(df: pd.DataFrame, period: int = 20) -> float:
    """Current volume / period average."""
    if "volume" not in df.columns or len(df) < period:
        return 1.0
    vol = df["volume"]
    avg = vol.rolling(period).mean()
    avg_last = _safe_last(avg, 1.0)
    if avg_last <= 0:
        return 1.0
    return _safe_last(vol, 0.0) / avg_last


def _compute_vwap_dev(df: pd.DataFrame) -> float:
    """Percent deviation of last close from rolling VWAP (20-period)."""
    if "volume" not in df.columns or len(df) < 20:
        return 0.0
    typical = (df["high"] + df["low"] + df["close"]) / 3
    pv = typical * df["volume"]
    cum_pv = pv.rolling(20).sum()
    cum_vol = df["volume"].rolling(20).sum().replace(0, 1e-10)
    vwap = cum_pv / cum_vol
    vwap_last = _safe_last(vwap, 0.0)
    close_last = _safe_last(df["close"], 0.0)
    if vwap_last <= 0:
        return 0.0
    return (close_last - vwap_last) / vwap_last * 100


def _compute_momentum(close: pd.Series, period: int = 5) -> float:
    """N-day percent change."""
    if len(close) < period + 1:
        return 0.0
    prev = close.iloc[-period - 1] if len(close) > period else close.iloc[0]
    last = _safe_last(close, 0.0)
    if prev == 0:
        return 0.0
    return (last - float(prev)) / float(prev) * 100


def _compute_macd_hist(close: pd.Series) -> float:
    """MACD histogram (12, 26, 9)."""
    if len(close) < 35:
        return 0.0
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    return _safe_last(hist, 0.0)


def _compute_bb_width(close: pd.Series, period: int = 20) -> float:
    """Bollinger band width as % of middle band."""
    if len(close) < period:
        return 2.0
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = mid + 2 * std
    lower = mid - 2 * std
    mid_last = _safe_last(mid, 1.0)
    if mid_last <= 0:
        return 2.0
    return (_safe_last(upper, 0.0) - _safe_last(lower, 0.0)) / mid_last * 100


def _compute_ema_slope(close: pd.Series, period: int, lookback: int = 5) -> float:
    """Slope of an EMA over the last N bars, normalized by current price."""
    if len(close) < period + lookback:
        return 0.0
    ema = close.ewm(span=period, adjust=False).mean()
    if len(ema) < lookback + 1:
        return 0.0
    prev = ema.iloc[-lookback - 1]
    last = _safe_last(ema, 0.0)
    if prev == 0 or last == 0:
        return 0.0
    return (last - float(prev)) / float(prev) * 100 / lookback


def _classify_regime(adx: float, atr_pct: float, ema9_slope: float, ema21_slope: float) -> str:
    """
    Classify market regime from already-computed indicators:
      TRENDING_UP   : strong uptrend, ADX >= 20 and both EMAs rising
      TRENDING_DOWN : strong downtrend, ADX >= 20 and both EMAs falling
      VOLATILE      : high ATR but no clear direction
      RANGING       : low ADX, low ATR, flat EMAs
    """
    strong_trend = adx >= 20
    if strong_trend and ema9_slope > 0.05 and ema21_slope > 0.02:
        return "TRENDING_UP"
    if strong_trend and ema9_slope < -0.05 and ema21_slope < -0.02:
        return "TRENDING_DOWN"
    if atr_pct >= 2.5:
        return "VOLATILE"
    return "RANGING"


def extract_entry_features(
    df: pd.DataFrame,
    *,
    mwa_bull_pct: float = 0.0,
    mwa_bear_pct: float = 0.0,
    scanner_count: int = 0,
    bull_scanner_count: int = 0,
    bear_scanner_count: int = 0,
    scanner_list: list[str] | None = None,
    ai_confidence: int = 50,
    rrr: float = 0.0,
    direction: str = "LONG",
    exchange: str = "NSE",
) -> dict[str, Any]:
    """
    Compute the full feature dict for a signal at entry time.

    `df` must be an OHLCV DataFrame with at least ~30 bars (columns: open,
    high, low, close, volume). Missing data falls back to neutral defaults
    so we never crash a signal creation.
    """
    if df is None or df.empty or len(df) < 5:
        logger.debug("extract_entry_features: insufficient data, returning defaults")
        return _default_features(
            mwa_bull_pct=mwa_bull_pct,
            mwa_bear_pct=mwa_bear_pct,
            scanner_count=scanner_count,
            bull_scanner_count=bull_scanner_count,
            bear_scanner_count=bear_scanner_count,
            scanner_list=scanner_list or [],
            ai_confidence=ai_confidence,
            rrr=rrr,
            direction=direction,
            exchange=exchange,
        )

    # Normalize column names (some providers use uppercase)
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    for col in ("open", "high", "low", "close"):
        if col not in df.columns:
            logger.debug("extract_entry_features: missing %s column", col)
            return _default_features(
                mwa_bull_pct=mwa_bull_pct,
                mwa_bear_pct=mwa_bear_pct,
                scanner_count=scanner_count,
                bull_scanner_count=bull_scanner_count,
                bear_scanner_count=bear_scanner_count,
                scanner_list=scanner_list or [],
                ai_confidence=ai_confidence,
                rrr=rrr,
                direction=direction,
                exchange=exchange,
            )

    close = df["close"]

    try:
        rsi = _compute_rsi(close)
        adx = _compute_adx(df)
        atr_pct = _compute_atr_pct(df)
        volume_ratio = _compute_volume_ratio(df)
        vwap_dev = _compute_vwap_dev(df)
        momentum_5d = _compute_momentum(close, 5)
        macd_hist = _compute_macd_hist(close)
        bb_width = _compute_bb_width(close)
        ema_9_slope = _compute_ema_slope(close, 9)
        ema_21_slope = _compute_ema_slope(close, 21)
        regime = _classify_regime(adx, atr_pct, ema_9_slope, ema_21_slope)
    except Exception as e:
        logger.warning("extract_entry_features failed: %s", e)
        return _default_features(
            mwa_bull_pct=mwa_bull_pct,
            mwa_bear_pct=mwa_bear_pct,
            scanner_count=scanner_count,
            bull_scanner_count=bull_scanner_count,
            bear_scanner_count=bear_scanner_count,
            scanner_list=scanner_list or [],
            ai_confidence=ai_confidence,
            rrr=rrr,
            direction=direction,
            exchange=exchange,
        )

    return {
        "rsi": round(rsi, 2),
        "adx": round(adx, 2),
        "atr_pct": round(atr_pct, 3),
        "volume_ratio": round(volume_ratio, 3),
        "vwap_dev": round(vwap_dev, 3),
        "momentum_5d": round(momentum_5d, 3),
        "macd_hist": round(macd_hist, 4),
        "bb_width": round(bb_width, 3),
        "ema_9_slope": round(ema_9_slope, 4),
        "ema_21_slope": round(ema_21_slope, 4),
        "regime": regime,
        "mwa_bull_pct": round(float(mwa_bull_pct or 0), 1),
        "mwa_bear_pct": round(float(mwa_bear_pct or 0), 1),
        "scanner_count": int(scanner_count or 0),
        "bull_scanner_count": int(bull_scanner_count or 0),
        "bear_scanner_count": int(bear_scanner_count or 0),
        "scanner_list": list(scanner_list or []),
        "ai_confidence": int(ai_confidence or 50),
        "rrr": round(float(rrr or 0), 2),
        "direction": (direction or "LONG").upper(),
        "exchange": (exchange or "NSE").upper(),
    }


def _default_features(**kwargs) -> dict[str, Any]:
    """Neutral defaults when OHLCV is unavailable."""
    return {
        "rsi": 50.0,
        "adx": 20.0,
        "atr_pct": 1.0,
        "volume_ratio": 1.0,
        "vwap_dev": 0.0,
        "momentum_5d": 0.0,
        "macd_hist": 0.0,
        "bb_width": 2.0,
        "ema_9_slope": 0.0,
        "ema_21_slope": 0.0,
        "regime": "RANGING",
        "mwa_bull_pct": float(kwargs.get("mwa_bull_pct", 0) or 0),
        "mwa_bear_pct": float(kwargs.get("mwa_bear_pct", 0) or 0),
        "scanner_count": int(kwargs.get("scanner_count", 0) or 0),
        "bull_scanner_count": int(kwargs.get("bull_scanner_count", 0) or 0),
        "bear_scanner_count": int(kwargs.get("bear_scanner_count", 0) or 0),
        "scanner_list": list(kwargs.get("scanner_list", [])),
        "ai_confidence": int(kwargs.get("ai_confidence", 50) or 50),
        "rrr": float(kwargs.get("rrr", 0) or 0),
        "direction": str(kwargs.get("direction", "LONG") or "LONG").upper(),
        "exchange": str(kwargs.get("exchange", "NSE") or "NSE").upper(),
    }


def to_feature_vector(features: dict[str, Any]) -> list[float]:
    """
    Convert a feature dict to a fixed-length numeric vector for ML / similarity.
    Order matches FEATURE_KEYS — never reorder; only append.
    """
    regime = (features.get("regime") or "RANGING").upper()
    direction = (features.get("direction") or "LONG").upper()
    exchange = (features.get("exchange") or "NSE").upper()

    vec = [
        float(features.get("rsi", 50.0)),
        float(features.get("adx", 20.0)),
        float(features.get("atr_pct", 1.0)),
        float(features.get("volume_ratio", 1.0)),
        float(features.get("vwap_dev", 0.0)),
        float(features.get("momentum_5d", 0.0)),
        float(features.get("macd_hist", 0.0)),
        float(features.get("bb_width", 2.0)),
        float(features.get("ema_9_slope", 0.0)),
        float(features.get("ema_21_slope", 0.0)),
        1.0 if regime == "TRENDING_UP" else 0.0,
        1.0 if regime == "TRENDING_DOWN" else 0.0,
        1.0 if regime == "RANGING" else 0.0,
        1.0 if regime == "VOLATILE" else 0.0,
        float(features.get("mwa_bull_pct", 0.0)),
        float(features.get("mwa_bear_pct", 0.0)),
        float(features.get("scanner_count", 0)),
        float(features.get("bull_scanner_count", 0)),
        float(features.get("bear_scanner_count", 0)),
        float(features.get("ai_confidence", 50)),
        float(features.get("rrr", 0.0)),
        1.0 if direction in ("LONG", "BUY") else 0.0,
        1.0 if direction in ("SHORT", "SELL") else 0.0,
        1.0 if exchange == "NSE" else 0.0,
        1.0 if exchange == "NFO" else 0.0,
        1.0 if exchange == "MCX" else 0.0,
        1.0 if exchange == "CDS" else 0.0,
        1.0 if exchange == "BSE" else 0.0,
    ]

    # Replace any remaining NaN/inf with 0
    return [0.0 if (v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))) else v for v in vec]


def normalize_vector(vec: list[float]) -> np.ndarray:
    """L2-normalize for cosine similarity."""
    arr = np.array(vec, dtype=np.float32)
    norm = np.linalg.norm(arr)
    if norm < 1e-10:
        return arr
    return arr / norm


def apply_features_to_signal(db_signal, features: dict[str, Any]) -> None:
    """
    Copy feature dict into a Signal ORM instance's columns.
    Safe — only sets the entry_* fields, preserves everything else.
    """
    try:
        db_signal.entry_rsi = features.get("rsi")
        db_signal.entry_adx = features.get("adx")
        db_signal.entry_atr_pct = features.get("atr_pct")
        db_signal.entry_volume_ratio = features.get("volume_ratio")
        db_signal.entry_vwap_dev = features.get("vwap_dev")
        db_signal.entry_momentum = features.get("momentum_5d")
        db_signal.entry_macd_hist = features.get("macd_hist")
        db_signal.entry_bb_width = features.get("bb_width")
        db_signal.entry_regime = features.get("regime")
        db_signal.entry_mwa_bull_pct = features.get("mwa_bull_pct")
        db_signal.entry_mwa_bear_pct = features.get("mwa_bear_pct")
        db_signal.scanner_list = features.get("scanner_list") or []
        db_signal.feature_vector = to_feature_vector(features)
    except Exception as e:
        logger.warning("apply_features_to_signal failed: %s", e)
