"""Supertrend flip — direction change on 15m bars."""

from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd
from mcp_server.agents.skills.base_skill import BaseSkill
from mcp_server.agents.skills.indicators import atr, make_signal


class SupertrendFlipSkill(BaseSkill):
    name = "supertrend_flip"
    segment = "equity_intraday"
    timeframe = "15m"
    min_bars = 20
    description = "Supertrend direction flip on 15-min bars"

    def scan(
        self, df: pd.DataFrame, symbol: str, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        c = np.asarray(df["close"], dtype=float)
        h = np.asarray(df["high"], dtype=float)
        l = np.asarray(df["low"], dtype=float)
        n = len(c)
        cur_atr = atr(h, l, 10)
        mult = 3.0
        mid = (h + l) / 2.0
        up = mid - mult * cur_atr
        dn = mid + mult * cur_atr
        trend = np.ones(n)
        for i in range(1, n):
            up[i] = max(up[i], up[i - 1]) if c[i - 1] > up[i - 1] else up[i]
            dn[i] = min(dn[i], dn[i - 1]) if c[i - 1] < dn[i - 1] else dn[i]
            trend[i] = 1 if c[i] > dn[i] else (-1 if c[i] < up[i] else trend[i - 1])
        if trend[-1] == 1 and trend[-2] == -1:
            return make_signal(
                ticker=symbol,
                direction="LONG",
                entry=float(c[-1]),
                sl=float(up[-1]),
                pattern="supertrend_flip_bull",
                confidence=66,
            )
        if trend[-1] == -1 and trend[-2] == 1:
            return make_signal(
                ticker=symbol,
                direction="SHORT",
                entry=float(c[-1]),
                sl=float(dn[-1]),
                pattern="supertrend_flip_bear",
                confidence=66,
            )
        return None
