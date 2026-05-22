"""
MCX Intraday ATR Breakout — hourly bars, 20-day high/low.

BACKTEST RESULTS (2024-2026, 730 days, GC=F 1h proxy):
  5d-high (40h),  hold 20h, SL1.5x TGT3x: WR=49.3%, n=335  -> OVERRIDE
  10d-high (80h), hold 30h, SL1.5x TGT3x: WR=46.3%, n=175  -> OVERRIDE
  20d-high (160h),hold 30h, SL1.5x TGT3x: WR=54.5%, n=101  -> borderline

OVERRIDE (enabled=False): no validated intraday edge on MCX gold hourly.
Needs 60+ live outcomes before re-classification.
Re-evaluate: 2026-08-13 (90 days of paper signals).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from mcp_server.agents.skills.base_skill import BaseSkill
from mcp_server.agents.skills.indicators import atr, make_signal

logger = logging.getLogger(__name__)

_LOOKBACK = 160    # 20 trading days * ~8 MCX hours
_HOLD_BARS = 30    # ~4 session hold
_SL_MULT = 1.5
_TGT_MULT = 3.0    # RRR 2.0

# MCX-symbol -> yfinance proxy for hourly fallback
_YF_PROXY = {
    "GOLD": "GC=F", "GOLDM": "GC=F",
    "GOLDPETAL": "GC=F", "GOLDGUINEA": "GC=F",
    "SILVER": "SI=F", "SILVERM": "SI=F",
    "CRUDEOIL": "CL=F",
    "NATURALGAS": "NG=F",
}


def _strip_exchange(symbol: str) -> str:
    return symbol.replace("MCX:", "").replace("NSE:", "").upper()


def _fetch_hourly(symbol: str) -> pd.DataFrame | None:
    """Fetch 30-day hourly bars. Tries routed provider first, falls back to yfinance."""
    sym = _strip_exchange(symbol)
    try:
        from mcp_server.data_provider import get_provider
        df = get_provider().get_ohlcv_routed(sym, interval="hour", days=30, exchange="MCX")
        if df is not None and not df.empty:
            df.columns = [c.lower() for c in df.columns]
            return df
    except Exception:
        pass

    yf_ticker = _YF_PROXY.get(sym)
    if yf_ticker:
        try:
            import yfinance as yf
            df = yf.download(yf_ticker, period="30d", interval="1h",
                             progress=False, auto_adjust=True)
            if df is not None and not df.empty:
                df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                              for c in df.columns]
                return df
        except Exception:
            pass
    return None


class MCXIntradayBreakoutSkill(BaseSkill):
    name = "mcx_intraday_breakout"
    segment = "commodity"
    timeframe = "1H"
    min_bars = 20        # daily bars (used by scan_all gate; hourly fetched internally)
    enabled = False      # OVERRIDE — paper collection only until 60+ live outcomes
    description = (
        "MCX hourly 20-day range breakout. OVERRIDE: intraday edge not yet validated "
        "(WR=49-55% on 730-day backtest). Re-evaluate 2026-08-13."
    )

    _fired: dict[tuple, bool] = {}   # (date, sym, dir) -> True — 1 signal per day

    def scan(
        self, df: pd.DataFrame, symbol: str, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        hourly = _fetch_hourly(symbol)
        if hourly is None or len(hourly) < _LOOKBACK:
            return None

        c = np.asarray(hourly["close"], dtype=float)
        h = np.asarray(hourly["high"],  dtype=float)
        lo = np.asarray(hourly["low"],  dtype=float)

        high_n = float(h[-_LOOKBACK:-1].max())
        low_n  = float(lo[-_LOOKBACK:-1].min())
        cur    = float(c[-1])
        cur_atr = atr(h, lo, 14)

        today = date.today()
        sym = _strip_exchange(symbol)

        if cur > high_n:
            key = (today, sym, "LONG")
            if self._fired.get(key):
                return None
            self._fired[key] = True
            sl  = round(cur - _SL_MULT * cur_atr, 2)
            tgt = round(cur + _TGT_MULT * cur_atr, 2)
            return make_signal(
                ticker=symbol, direction="LONG",
                entry=cur, sl=sl, target=tgt,
                pattern="mcx_intraday_breakout_20d",
                confidence=55, validated=False,
            )

        if cur < low_n:
            key = (today, sym, "SHORT")
            if self._fired.get(key):
                return None
            self._fired[key] = True
            sl  = round(cur + _SL_MULT * cur_atr, 2)
            tgt = round(cur - _TGT_MULT * cur_atr, 2)
            return make_signal(
                ticker=symbol, direction="SHORT",
                entry=cur, sl=sl, target=tgt,
                pattern="mcx_intraday_breakdown_20d",
                confidence=55, validated=False,
            )

        return None
