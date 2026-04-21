"""Breakout above 200-day SMA — close > SMA200, yesterday was below."""

from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd
from mcp_server.agents.skills.base_skill import BaseSkill
from mcp_server.agents.skills.indicators import make_signal


class Breakout200DMASkill(BaseSkill):
    name = "breakout_200dma"
    segment = "equity_swing"
    timeframe = "1D"
    min_bars = 201
    description = "Bullish breakout when close crosses above 200-day SMA"

    def scan(
        self, df: pd.DataFrame, symbol: str, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        c = np.asarray(df["close"], dtype=float)
        l = np.asarray(df["low"], dtype=float)
        sma200 = float(np.mean(c[-200:]))
        sma200_prev = float(np.mean(c[-201:-1]))
        if c[-1] > sma200 and c[-2] <= sma200_prev:
            sl = float(l[-5:].min())
            return make_signal(
                ticker=symbol,
                direction="LONG",
                entry=float(c[-1]),
                sl=sl,
                pattern="breakout_200dma",
                confidence=70,
            )
        return None
