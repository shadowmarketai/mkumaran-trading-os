"""Forex RSI reversal — entry when RSI crosses back from 30/70."""

from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd
from mcp_server.agents.skills.base_skill import BaseSkill
from mcp_server.agents.skills.indicators import rsi, make_signal


class ForexRSIReversalSkill(BaseSkill):
    name = "forex_rsi_reversal"
    segment = "forex"
    timeframe = "1H"
    min_bars = 20
    description = "RSI reversal when crossing back from oversold/overbought"

    def scan(
        self, df: pd.DataFrame, symbol: str, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        c = np.asarray(df["close"], dtype=float)
        l = np.asarray(df["low"], dtype=float)
        h = np.asarray(df["high"], dtype=float)
        r = rsi(c, 14)
        if len(r) < 2:
            return None
        if r[-2] < 30 and r[-1] >= 30:
            sl = float(l[-5:].min())
            return make_signal(
                ticker=symbol,
                direction="LONG",
                entry=float(c[-1]),
                sl=sl,
                pattern="fx_rsi_oversold_reversal",
                confidence=63,
            )
        if r[-2] > 70 and r[-1] <= 70:
            sl = float(h[-5:].max())
            return make_signal(
                ticker=symbol,
                direction="SHORT",
                entry=float(c[-1]),
                sl=sl,
                pattern="fx_rsi_overbought_reversal",
                confidence=63,
            )
        return None
