"""
Forex RSI reversal — RSI(14) crossback from 30/70 on 1H bars.

BACKTEST RESULTS (365-day, 1H bars):
  USDINR RRR 1.5: WR=42.4%, Sharpe=2.374, n=210 → TIER_2  ← live
  EURUSD/GBPUSD/USDJPY: OVERRIDE across all RRR variants

Restricted to USDINR (the only validated pair). RRR set to 1.5.
Exit dist: SL 54% | Target 31% | Max-hold 15%
"""

from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd
from mcp_server.agents.skills.base_skill import BaseSkill
from mcp_server.agents.skills.indicators import rsi, make_signal

# Only USDINR is validated — all major pairs (EUR/GBP/JPY) are OVERRIDE
_VALIDATED_PAIRS = {"CDS:USDINR", "USDINR", "USDINR=X"}


class ForexRSIReversalSkill(BaseSkill):
    name = "forex_rsi_reversal"
    segment = "forex"
    timeframe = "1H"
    min_bars = 20
    version = "2.0.0"
    description = (
        "RSI(14) crossback reversal on USDINR 1H. "
        "TIER_2 validated: WR=42.4%, Sharpe=2.37 (365-day backtest). RRR=1.5."
    )

    def scan(
        self, df: pd.DataFrame, symbol: str, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        # Only fire on validated pair
        if symbol.upper() not in _VALIDATED_PAIRS:
            return None

        c   = np.asarray(df["close"], dtype=float)
        low = np.asarray(df["low"],   dtype=float)
        h   = np.asarray(df["high"],  dtype=float)
        r   = rsi(c, 14)
        if len(r) < 2:
            return None

        if r[-2] < 30 and r[-1] >= 30:
            sl = float(low[-5:].min())
            return make_signal(
                ticker=symbol, direction="LONG",
                entry=float(c[-1]), sl=sl,
                pattern="fx_rsi_oversold_reversal",
                confidence=65, rrr_mult=1.5, validated=True,
            )
        if r[-2] > 70 and r[-1] <= 70:
            sl = float(h[-5:].max())
            return make_signal(
                ticker=symbol, direction="SHORT",
                entry=float(c[-1]), sl=sl,
                pattern="fx_rsi_overbought_reversal",
                confidence=65, rrr_mult=1.5, validated=True,
            )
        return None
