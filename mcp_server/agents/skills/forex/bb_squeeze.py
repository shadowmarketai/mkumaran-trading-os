"""Bollinger Band squeeze — BB width < 1% then breakout."""

from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd
from mcp_server.agents.skills.base_skill import BaseSkill
from mcp_server.agents.skills.indicators import bollinger_bands, make_signal


class BBSqueezeSkill(BaseSkill):
    name = "bb_squeeze"
    segment = "forex"
    timeframe = "1H"
    min_bars = 25
    description = "BB squeeze breakout when bandwidth < 1%"

    def scan(
        self, df: pd.DataFrame, symbol: str, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        c = np.asarray(df["close"], dtype=float)
        l = np.asarray(df["low"], dtype=float)
        h = np.asarray(df["high"], dtype=float)
        sma, upper, lower = bollinger_bands(c[:-1], 20, 2.0)
        if sma <= 0:
            return None
        width_pct = (upper - lower) / sma * 100
        if width_pct >= 1.0:
            return None
        if c[-1] > upper:
            sl = float(l[-3:].min())
            return make_signal(
                ticker=symbol,
                direction="LONG",
                entry=float(c[-1]),
                sl=sl,
                pattern="bb_squeeze_bull_breakout",
                confidence=66,
            )
        if c[-1] < lower:
            sl = float(h[-3:].max())
            return make_signal(
                ticker=symbol,
                direction="SHORT",
                entry=float(c[-1]),
                sl=sl,
                pattern="bb_squeeze_bear_breakout",
                confidence=66,
            )
        return None
