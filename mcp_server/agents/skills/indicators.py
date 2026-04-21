"""Shared technical indicators for all skills."""

from __future__ import annotations

import numpy as np
import pandas as pd


def ema(data: np.ndarray | pd.Series, span: int) -> np.ndarray:
    arr = np.asarray(data, dtype=float)
    alpha = 2.0 / (span + 1)
    out = np.zeros_like(arr)
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = alpha * arr[i] + (1 - alpha) * out[i - 1]
    return out


def rsi(data: np.ndarray | pd.Series, period: int = 14) -> np.ndarray:
    arr = np.asarray(data, dtype=float)
    deltas = np.diff(arr)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.convolve(gains, np.ones(period) / period, mode="valid")
    avg_loss = np.convolve(losses, np.ones(period) / period, mode="valid")
    rs = avg_gain / np.where(avg_loss > 0, avg_loss, 1e-10)
    return 100 - (100 / (1 + rs))


def atr(high: np.ndarray, low: np.ndarray, period: int = 14) -> float:
    return float(np.mean(high[-period:] - low[-period:]))


def adx(
    high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14
) -> np.ndarray:
    n = len(close)
    if n < period + 1:
        return np.array([0.0])
    tr = np.maximum(high[1:] - low[1:], np.abs(high[1:] - close[:-1]))
    tr = np.maximum(tr, np.abs(low[1:] - close[:-1]))
    plus_dm = np.where(
        (high[1:] - high[:-1]) > (low[:-1] - low[1:]),
        np.maximum(high[1:] - high[:-1], 0),
        0,
    )
    minus_dm = np.where(
        (low[:-1] - low[1:]) > (high[1:] - high[:-1]),
        np.maximum(low[:-1] - low[1:], 0),
        0,
    )
    atr_arr = np.convolve(tr, np.ones(period) / period, mode="valid")
    plus_di = (
        np.convolve(plus_dm, np.ones(period) / period, mode="valid")
        / np.where(atr_arr > 0, atr_arr, 1)
        * 100
    )
    minus_di = (
        np.convolve(minus_dm, np.ones(period) / period, mode="valid")
        / np.where(atr_arr > 0, atr_arr, 1)
        * 100
    )
    dx = (
        np.abs(plus_di - minus_di)
        / np.where((plus_di + minus_di) > 0, plus_di + minus_di, 1)
        * 100
    )
    if len(dx) >= period:
        return np.convolve(dx, np.ones(period) / period, mode="valid")
    return dx


def bollinger_bands(
    close: np.ndarray, period: int = 20, mult: float = 2.0
) -> tuple[float, float, float]:
    """Returns (sma, upper, lower) for the latest bar."""
    sma = float(np.mean(close[-period:]))
    std = float(np.std(close[-period:]))
    return sma, sma + mult * std, sma - mult * std


def make_signal(
    ticker: str,
    direction: str,
    entry: float,
    sl: float,
    pattern: str,
    confidence: int = 65,
    rrr_mult: float = 2.0,
) -> dict:
    risk = abs(entry - sl)
    if risk <= 0:
        risk = entry * 0.002
    target = entry + risk * rrr_mult if direction == "LONG" else entry - risk * rrr_mult
    return {
        "ticker": ticker,
        "direction": direction,
        "entry": round(entry, 2),
        "sl": round(sl, 2),
        "target": round(target, 2),
        "rrr": round(abs(target - entry) / risk, 1),
        "pattern": pattern,
        "confidence": confidence,
    }
