"""Swing low bounce — close near 20d low + green candle."""

from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd
from mcp_server.agents.skills.base_skill import BaseSkill
from mcp_server.agents.skills.indicators import make_signal


class SwingLowBounceSkill(BaseSkill):
    name = "swing_low_bounce"
    segment = "equity_swing"
    timeframe = "1D"
    min_bars = 21
    description = "Bounce from 20-day low with bullish green candle"

    def scan(
        self, df: pd.DataFrame, symbol: str, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        c = np.asarray(df["close"], dtype=float)
        o = np.asarray(df["open"], dtype=float)
        l = np.asarray(df["low"], dtype=float)
        low_20 = float(l[-21:-1].min())
        is_green = c[-1] > o[-1]
        near_low = l[-1] <= low_20 * 1.015
        if near_low and is_green:
            sl = round(low_20 * 0.99, 2)
            return make_signal(
                ticker=symbol,
                direction="LONG",
                entry=float(c[-1]),
                sl=sl,
                pattern="swing_low_bounce_20d",
                confidence=64,
            )
        return None
