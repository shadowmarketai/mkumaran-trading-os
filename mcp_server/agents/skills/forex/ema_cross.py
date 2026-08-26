"""
Forex EMA 9/21 crossover on 1H bars.

BACKTEST RESULTS (365-day, 1H bars):
  USDJPY RRR 2.0: WR=43.7%, Sharpe=5.726, n=206 → TIER_2  ← best
  EURUSD RRR 1.5: WR=44.3%, Sharpe=4.049, n=219 → TIER_2
  USDINR RRR 1.5: WR=41.0%, Sharpe=0.539, n=205 → TIER_2
  GBPUSD:         OVERRIDE on all variants — disabled

Per-pair RRR: USDJPY=2.0, EURUSD=1.5, USDINR=1.5
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from mcp_server.agents.skills.base_skill import BaseSkill
from mcp_server.agents.skills.indicators import ema, make_signal

# Validated pairs and their best RRR — GBPUSD excluded (OVERRIDE)
_PAIR_RRR: dict[str, float] = {
    "CDS:USDINR": 1.5, "USDINR": 1.5, "USDINR=X": 1.5,
    "EURUSD": 1.5, "EURUSD=X": 1.5,
    "USDJPY": 2.0, "USDJPY=X": 2.0,
}


class ForexEMACrossSkill(BaseSkill):
    name = "forex_ema_cross"
    segment = "forex"
    timeframe = "1H"
    min_bars = 25
    version = "2.0.0"
    description = (
        "EMA9/21 crossover. TIER_2: USDJPY Sharpe=5.73, EURUSD Sharpe=4.05 "
        "(365-day backtest). GBPUSD disabled (OVERRIDE)."
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
        e9, e21 = ema(c, 9), ema(c, 21)

        if e9[-1] > e21[-1] and e9[-2] <= e21[-2]:
            sl = float(low[-3:].min())
            return make_signal(
                ticker=symbol, direction="LONG",
                entry=float(c[-1]), sl=sl,
                pattern="fx_ema9_21_bull",
                confidence=65, rrr_mult=rrr, validated=True,
            )
        if e9[-1] < e21[-1] and e9[-2] >= e21[-2]:
            sl = float(h[-3:].max())
            return make_signal(
                ticker=symbol, direction="SHORT",
                entry=float(c[-1]), sl=sl,
                pattern="fx_ema9_21_bear",
                confidence=65, rrr_mult=rrr, validated=True,
            )
        return None
