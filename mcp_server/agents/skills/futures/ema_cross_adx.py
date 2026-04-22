"""EMA 9/21 crossover with ADX > 25 filter on daily bars."""

from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd
from mcp_server.agents.skills.base_skill import BaseSkill
from mcp_server.agents.skills.indicators import ema, adx, make_signal


class EMACrossADXSkill(BaseSkill):
    name = "ema_cross_adx"
    segment = "futures"
    timeframe = "1D"
    min_bars = 30
    description = "EMA 9/21 crossover confirmed by ADX > 25"

    def scan(
        self, df: pd.DataFrame, symbol: str, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        c = np.asarray(df["close"], dtype=float)
        h = np.asarray(df["high"], dtype=float)
        low = np.asarray(df["low"], dtype=float)
        e9, e21 = ema(c, 9), ema(c, 21)
        adx_arr = adx(h, low, c, 14)
        if adx_arr[-1] < 25:
            return None
        if e9[-1] > e21[-1] and e9[-2] <= e21[-2]:
            sl = float(low[-3:].min())
            return make_signal(
                ticker=symbol,
                direction="LONG",
                entry=float(c[-1]),
                sl=sl,
                pattern="ema9_21_bull_adx",
                confidence=68,
            )
        if e9[-1] < e21[-1] and e9[-2] >= e21[-2]:
            sl = float(h[-3:].max())
            return make_signal(
                ticker=symbol,
                direction="SHORT",
                entry=float(c[-1]),
                sl=sl,
                pattern="ema9_21_bear_adx",
                confidence=68,
            )
        return None
