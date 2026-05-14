"""
Market direction — Nifty 50 Supertrend regime detection.

Single source of truth for market direction across:
  - Intraday scanner  (gate: skip LONG signals on bearish days)
  - Debate validator  (context: regime injected into all agent prompts)
  - Backtest scripts  (regime_map for walk-forward simulation)

Uses Nifty Supertrend(10, 3) on daily bars — same indicator as the
TIER_1 BB Breakout strategy, so entry signals are always evaluated
in the context of the same trend tool that validated them.

Data source: yfinance (^NSEI daily). Cached 23 hours per process so
the pipeline doesn't refetch on every 5-minute intraday scan cycle.

Fail-open contract: any data failure returns BULLISH (+1) and logs a
warning. The pipeline is never silently blocked by a missing API call.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)

# ── Supertrend parameters ─────────────────────────────────────────────────────
# Same as BB Breakout strategy for system coherence.
ST_PERIOD     = 10
ST_MULTIPLIER = 3.0

# ── In-process cache ──────────────────────────────────────────────────────────
_cache_ts:        Optional[datetime] = None
_cache_direction: int                = 1   # default: bullish
_CACHE_TTL_HOURS                     = 23


# ── Internal helpers ──────────────────────────────────────────────────────────

def _fetch_nifty_daily(lookback_days: int = 220) -> "Optional[pd.DataFrame]":
    """Download Nifty 50 daily OHLCV via yfinance."""
    try:
        import yfinance as yf
        period = f"{min(lookback_days, 365)}d"
        df = yf.download("^NSEI", period=period, interval="1d",
                         progress=False, auto_adjust=True)
        if df.empty:
            return None
        df.columns = [str(c).lower() for c in df.columns]
        return df
    except Exception as exc:
        logger.warning("Nifty daily fetch failed: %s", exc)
        return None


def _supertrend(df: "pd.DataFrame",
                period: int = ST_PERIOD,
                multiplier: float = ST_MULTIPLIER) -> "pd.Series":
    """
    Compute Supertrend direction (+1 bullish / -1 bearish) on daily OHLCV.
    Uses Wilder's ATR (not simple rolling mean) for accuracy on daily data.
    """
    import pandas as pd
    n      = len(df)
    highs  = df["high"].values
    lows   = df["low"].values
    closes = df["close"].values

    # True Range
    trs = [highs[0] - lows[0]]
    for i in range(1, n):
        trs.append(max(
            highs[i] - lows[i],
            abs(highs[i]  - closes[i - 1]),
            abs(lows[i]   - closes[i - 1]),
        ))

    # Wilder's smoothed ATR
    atr = [0.0] * n
    atr[0] = trs[0]
    alpha = 1.0 / period
    for i in range(1, n):
        atr[i] = (1 - alpha) * atr[i - 1] + alpha * trs[i]

    # Direction
    direction = [1] * n
    for i in range(1, n):
        hl2   = (highs[i] + lows[i]) / 2.0
        upper = hl2 + multiplier * atr[i]
        lower = hl2 - multiplier * atr[i]
        if closes[i] > upper:
            direction[i] = 1
        elif closes[i] < lower:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]

    return pd.Series(direction, index=df.index, dtype=int)


def _refresh() -> int:
    """Fetch fresh data, compute Supertrend, return +1 or -1."""
    df = _fetch_nifty_daily()
    if df is None or len(df) < ST_PERIOD + 2:
        logger.warning("market_direction: data unavailable — keeping %s",
                       "BULLISH" if _cache_direction == 1 else "BEARISH")
        return _cache_direction

    st        = _supertrend(df)
    direction = int(st.iloc[-1])
    as_of     = str(df.index[-1])[:10]
    logger.info(
        "Market direction: Nifty Supertrend(%d, %.0f) = %s (as of %s)",
        ST_PERIOD, ST_MULTIPLIER,
        "BULLISH" if direction == 1 else "BEARISH",
        as_of,
    )
    return direction


# ── Public API ────────────────────────────────────────────────────────────────

def get_market_direction() -> int:
    """
    Return +1 (Nifty Supertrend bullish) or -1 (bearish).
    Cached 23 hours. Always returns +1 on data failure (fail-open).
    """
    global _cache_ts, _cache_direction

    now = datetime.now()
    if _cache_ts is None or (now - _cache_ts).total_seconds() > _CACHE_TTL_HOURS * 3600:
        _cache_direction = _refresh()
        _cache_ts = now

    return _cache_direction


def is_market_bullish() -> bool:
    """True when Nifty daily Supertrend is +1 (bullish)."""
    return get_market_direction() == 1


def get_direction_label() -> str:
    """Human-readable label: 'BULLISH' or 'BEARISH'."""
    return "BULLISH" if is_market_bullish() else "BEARISH"


def get_regime_map(lookback_days: int = 220) -> dict[date, bool]:
    """
    Return {date: True/False} for backtest walk-forward simulation.
    True = Nifty Supertrend bullish on that date (allow LONG signals).
    Returns empty dict on failure — simulation runs without filter.
    """
    df = _fetch_nifty_daily(lookback_days=lookback_days)
    if df is None or len(df) < ST_PERIOD + 2:
        logger.warning("regime_map: returning empty dict — no filter applied")
        return {}

    st     = _supertrend(df)
    regime: dict[date, bool] = {}
    for ts, direction in st.items():
        d = ts.date() if hasattr(ts, "date") else ts
        regime[d] = int(direction) == 1

    bullish = sum(v for v in regime.values())
    logger.info(
        "Regime map: %d days | %d bullish (%.0f%%) / %d bearish (%.0f%%)",
        len(regime),
        bullish, bullish / len(regime) * 100,
        len(regime) - bullish, (len(regime) - bullish) / len(regime) * 100,
    )
    return regime
