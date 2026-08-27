"""
MKUMARAN Trading OS — Quad Confluence Strategy (4-of-4 AND gate)

A strict-confluence bullish breakout: SuperTrend + RSI + Traditional Pivot R1
+ Bollinger upper band must ALL be true on the same bar. Three of four is not
a trade — the gate is an AND, not a score.

This is deliberately different from the MWA scanner architecture, which is
ADDITIVE (more scanners firing -> higher confidence). Here a single FALSE
vetoes the entry.

Entry (all four on the same bar):
  1. SuperTrend(10, 2)      close > SuperTrend line          (trend)
  2. RSI(14) > 70                                            (momentum)
  3. close > R1 (traditional floor pivots, prior session)    (structure)
  4. close > upper Bollinger(20, 2)                          (expansion)

Optional 5th gate (ADX_MIN, default ON):
  ADX(14) >= 20 — a range filter. The source framework omits ADX, but the
  same author's own 43-strategy book uses ADX as a range filter in 34 of 42
  strategies, and this system's worst losses came in SIDEWAYS tape. Set
  QUAD_ADX_MIN = 0 to disable and reproduce the original 4-condition rule.

Exit: SuperTrend flip (trailing) or hard stop, whichever comes first.

NOTHING here is validated. Run the backtest before wiring to live signals.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Tunables ──────────────────────────────────────────────────────
ST_PERIOD = 10
ST_MULT = 2.0        # deck says (10,2); note repo default elsewhere is 3.0
RSI_PERIOD = 14
RSI_MIN = 70.0
BB_PERIOD = 20
BB_MULT = 2.0
ADX_PERIOD = 14
QUAD_ADX_MIN = 20.0  # set to 0.0 to disable the ADX range filter
STOP_ATR_MULT = 1.5
ATR_PERIOD = 14


def _wilder_rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    """Wilder-smoothed RSI (matches TradingView/Quantman, not simple-mean RSI)."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def _wilder_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    """True-range ATR with Wilder smoothing (not the high-low mean used elsewhere)."""
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def _supertrend(df: pd.DataFrame, period: int = ST_PERIOD, mult: float = ST_MULT) -> pd.DataFrame:
    """Proper SuperTrend with band ratcheting. Returns cols: st_line, st_dir (+1/-1).

    Uses true-range ATR and the standard 'final band' carry-forward rule. The
    simplified version in intraday_scanner.py uses a high-low mean instead of
    true range and no band ratcheting, so its line sits in a different place.
    """
    atr = _wilder_atr(df, period)
    hl2 = (df["high"] + df["low"]) / 2
    upper_basic = hl2 + mult * atr
    lower_basic = hl2 - mult * atr

    n = len(df)
    upper = upper_basic.copy()
    lower = lower_basic.copy()
    close = df["close"]

    up_arr = upper.to_numpy(copy=True)
    lo_arr = lower.to_numpy(copy=True)
    c = close.to_numpy()

    for i in range(1, n):
        up_arr[i] = (
            min(upper_basic.iloc[i], up_arr[i - 1])
            if c[i - 1] <= up_arr[i - 1]
            else upper_basic.iloc[i]
        )
        lo_arr[i] = (
            max(lower_basic.iloc[i], lo_arr[i - 1])
            if c[i - 1] >= lo_arr[i - 1]
            else lower_basic.iloc[i]
        )

    direction = np.ones(n, dtype=int)
    st_line = np.full(n, np.nan)
    for i in range(1, n):
        if c[i] > up_arr[i - 1]:
            direction[i] = 1
        elif c[i] < lo_arr[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
        st_line[i] = lo_arr[i] if direction[i] == 1 else up_arr[i]

    return pd.DataFrame({"st_line": st_line, "st_dir": direction}, index=df.index)


def _traditional_pivots(df: pd.DataFrame) -> pd.DataFrame:
    """Traditional floor pivots computed from the PRIOR bar (no look-ahead).

    P  = (H + L + C) / 3
    R1 = 2P - L        S1 = 2P - H
    """
    ph = df["high"].shift(1)
    pl = df["low"].shift(1)
    pc = df["close"].shift(1)
    p = (ph + pl + pc) / 3
    return pd.DataFrame({"pivot": p, "r1": 2 * p - pl, "s1": 2 * p - ph}, index=df.index)


def _adx(df: pd.DataFrame, period: int = ADX_PERIOD) -> pd.Series:
    """Wilder ADX."""
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    atr = _wilder_atr(df, period)
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(
        alpha=1 / period, adjust=False
    ).mean() / atr.replace(0, np.nan)
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(
        alpha=1 / period, adjust=False
    ).mean() / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False).mean().fillna(0.0)


def compute_conditions(df: pd.DataFrame) -> pd.DataFrame:
    """Attach the four (or five) boolean gates plus supporting columns.

    Every indicator is computed from data available at or before each bar's
    close; pivots use the prior bar explicitly. No look-ahead.
    """
    out = df.copy()
    out.columns = [c.lower() for c in out.columns]

    st = _supertrend(out)
    piv = _traditional_pivots(out)

    sma = out["close"].rolling(BB_PERIOD).mean()
    # ddof=0 (population std) to match Quantman/TradingView Bollinger.
    std = out["close"].rolling(BB_PERIOD).std(ddof=0)

    out["st_line"] = st["st_line"]
    out["st_dir"] = st["st_dir"]
    out["rsi"] = _wilder_rsi(out["close"])
    out["r1"] = piv["r1"]
    out["bb_upper"] = sma + BB_MULT * std
    out["adx"] = _adx(out)
    out["atr"] = _wilder_atr(out)

    out["c1_supertrend"] = (out["close"] > out["st_line"]) & (out["st_dir"] == 1)
    out["c2_rsi"] = out["rsi"] > RSI_MIN
    out["c3_pivot"] = out["close"] > out["r1"]
    out["c4_bb"] = out["close"] > out["bb_upper"]
    out["c5_adx"] = out["adx"] >= QUAD_ADX_MIN if QUAD_ADX_MIN > 0 else True

    out["conditions_met"] = (
        out[["c1_supertrend", "c2_rsi", "c3_pivot", "c4_bb"]].sum(axis=1).astype(int)
    )
    out["entry"] = (
        out["c1_supertrend"] & out["c2_rsi"] & out["c3_pivot"] & out["c4_bb"] & out["c5_adx"]
    )
    return out


def generate_signals_for_backtest(
    data: pd.DataFrame, ticker: str = "", capital: float = 100000
) -> list[dict[str, Any]]:
    """Emit entry signals for the backtester.

    Entry is taken at the NEXT bar's open after all conditions confirm on a
    closed bar — you cannot trade a close you have not seen yet.
    Exit: SuperTrend flip to -1, or stop at entry - STOP_ATR_MULT * ATR.
    """
    df = compute_conditions(data)
    if len(df) < BB_PERIOD + ST_PERIOD + 5:
        return []

    signals: list[dict[str, Any]] = []
    in_position = False
    entry_idx = 0
    entry_price = 0.0
    stop = 0.0

    idx = df.index
    for i in range(BB_PERIOD + ST_PERIOD, len(df) - 1):
        if not in_position and bool(df["entry"].iloc[i]):
            entry_price = float(df["open"].iloc[i + 1])   # next-bar open
            atr_val = float(df["atr"].iloc[i]) or entry_price * 0.01
            stop = entry_price - STOP_ATR_MULT * atr_val
            entry_idx = i + 1
            in_position = True
            continue

        if in_position:
            low = float(df["low"].iloc[i])
            if low <= stop:
                exit_price, reason = stop, "STOP"
            elif int(df["st_dir"].iloc[i]) == -1:
                exit_price, reason = float(df["close"].iloc[i]), "ST_FLIP"
            else:
                continue

            qty = max(int(capital // entry_price), 1) if entry_price > 0 else 1
            signals.append(
                {
                    "ticker": ticker,
                    "direction": "LONG",
                    "pattern": "quad_confluence_4x",
                    "entry_date": idx[entry_idx],
                    "entry": round(entry_price, 2),
                    "exit_date": idx[i],
                    "exit": round(exit_price, 2),
                    "stop_loss": round(stop, 2),
                    "exit_reason": reason,
                    "qty": qty,
                    "pnl_pct": round((exit_price - entry_price) / entry_price * 100, 3),
                    "bars_held": i - entry_idx,
                }
            )
            in_position = False

    return signals
