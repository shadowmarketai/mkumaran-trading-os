"""
Bollinger Band squeeze breakout on 1H bars.

BACKTEST RESULTS (365-day, 1H bars):
  GBPUSD RRR 1.5: WR=45.0%, Sharpe=2.521, n=420 → TIER_2  ← best
  USDJPY RRR 2.0: WR=42.4%, Sharpe=1.222, n=399 → TIER_2
  EURUSD:         OVERRIDE on all variants — disabled
  USDINR RRR 2.0: Sharpe=0.337 — too marginal, disabled

Signal: BB(20,2) width < 1% then price breaks above upper / below lower.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from mcp_server.agents.skills.base_skill import BaseSkill
from mcp_server.agents.skills.indicators import bollinger_bands, make_signal

# Validated pairs and their best RRR — EURUSD and USDINR excluded
_PAIR_RRR: dict[str, float] = {
    "GBPUSD": 1.5, "GBPUSD=X": 1.5,
    "USDJPY": 2.0, "USDJPY=X": 2.0,
}


class BBSqueezeSkill(BaseSkill):
    name = "bb_squeeze"
    segment = "forex"
    timeframe = "1H"
    min_bars = 25
    version = "2.0.0"
    description = (
        "BB squeeze breakout (width<1%). TIER_2: GBPUSD Sharpe=2.52, "
        "USDJPY Sharpe=1.22 (365-day backtest). EURUSD/USDINR disabled."
    )

    def scan(
        self, df: pd.DataFrame, symbol: str, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        rrr = _PAIR_RRR.get(symbol.upper())
        if rrr is None:
            return None  # not a validated pair

        c   = np.asarray(df["close"], dtype=float)
        low = np.asarray(df["low"],   dtype=float)
        h   = np.asarray(df["high"],  dtype=float)

        sma, upper, lower = bollinger_bands(c[:-1], 20, 2.0)
        if sma <= 0:
            return None
        width_pct = (upper - lower) / sma * 100
        if width_pct >= 1.0:
            return None

        if c[-1] > upper:
            sl = float(low[-3:].min())
            return make_signal(
                ticker=symbol, direction="LONG",
                entry=float(c[-1]), sl=sl,
                pattern="bb_squeeze_bull_breakout",
                confidence=65, rrr_mult=rrr, validated=True,
            )
        if c[-1] < lower:
            sl = float(h[-3:].max())
            return make_signal(
                ticker=symbol, direction="SHORT",
                entry=float(c[-1]), sl=sl,
                pattern="bb_squeeze_bear_breakout",
                confidence=65, rrr_mult=rrr, validated=True,
            )
        return None
