"""ATR breakout — close > 20d high with ATR-based SL/TGT."""

from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd
from mcp_server.agents.skills.base_skill import BaseSkill
from mcp_server.agents.skills.indicators import atr, make_signal


class ATRBreakoutSkill(BaseSkill):
    name = "atr_breakout"
    segment = "commodity"
    timeframe = "1D"
    min_bars = 21
    description = "Breakout above 20-day high with ATR-based stop-loss"

    def scan(
        self, df: pd.DataFrame, symbol: str, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        c = np.asarray(df["close"], dtype=float)
        h = np.asarray(df["high"], dtype=float)
        low = np.asarray(df["low"], dtype=float)
        high_20 = float(h[-21:-1].max())
        if c[-1] <= high_20:
            return None
        cur_atr = atr(h, low, 14)
        sl = round(float(c[-1]) - 1.5 * cur_atr, 2)
        return make_signal(
            ticker=symbol,
            direction="LONG",
            entry=float(c[-1]),
            sl=sl,
            pattern="atr_breakout_20d",
            confidence=67,
        )
