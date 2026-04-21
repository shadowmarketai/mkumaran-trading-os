"""Forex EMA 9/21 crossover."""

from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd
from mcp_server.agents.skills.base_skill import BaseSkill
from mcp_server.agents.skills.indicators import ema, make_signal


class ForexEMACrossSkill(BaseSkill):
    name = "forex_ema_cross"
    segment = "forex"
    timeframe = "1H"
    min_bars = 25
    description = "EMA 9/21 crossover on forex pairs"

    def scan(
        self, df: pd.DataFrame, symbol: str, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        c = np.asarray(df["close"], dtype=float)
        l = np.asarray(df["low"], dtype=float)
        h = np.asarray(df["high"], dtype=float)
        e9, e21 = ema(c, 9), ema(c, 21)
        if e9[-1] > e21[-1] and e9[-2] <= e21[-2]:
            sl = float(l[-3:].min())
            return make_signal(
                ticker=symbol,
                direction="LONG",
                entry=float(c[-1]),
                sl=sl,
                pattern="fx_ema9_21_bull",
                confidence=64,
            )
        if e9[-1] < e21[-1] and e9[-2] >= e21[-2]:
            sl = float(h[-3:].max())
            return make_signal(
                ticker=symbol,
                direction="SHORT",
                entry=float(c[-1]),
                sl=sl,
                pattern="fx_ema9_21_bear",
                confidence=64,
            )
        return None
