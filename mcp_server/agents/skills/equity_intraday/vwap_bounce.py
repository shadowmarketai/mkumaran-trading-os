"""VWAP bounce — 3-bar flip above/below VWAP on 5m bars."""

from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd
from mcp_server.agents.skills.base_skill import BaseSkill
from mcp_server.agents.skills.indicators import make_signal


class VWAPBounceSkill(BaseSkill):
    name = "vwap_bounce"
    segment = "equity_intraday"
    timeframe = "5m"
    min_bars = 10
    description = "3-bar flip above or below VWAP for intraday momentum"

    def scan(
        self, df: pd.DataFrame, symbol: str, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        c = np.asarray(df["close"], dtype=float)
        h = np.asarray(df["high"], dtype=float)
        l = np.asarray(df["low"], dtype=float)
        v = np.asarray(df["volume"], dtype=float)
        cum_vol = np.cumsum(v)
        tp = (h + l + c) / 3.0
        vwap = np.cumsum(tp * v) / np.where(cum_vol > 0, cum_vol, 1)
        diff = c - vwap
        if len(diff) < 4:
            return None
        # 3 bars below then cross above
        if diff[-4] < 0 and diff[-3] < 0 and diff[-2] < 0 and diff[-1] > 0:
            sl = float(l[-3:].min())
            return make_signal(
                ticker=symbol,
                direction="LONG",
                entry=float(c[-1]),
                sl=sl,
                pattern="vwap_bounce_bull",
                confidence=65,
            )
        if diff[-4] > 0 and diff[-3] > 0 and diff[-2] > 0 and diff[-1] < 0:
            sl = float(h[-3:].max())
            return make_signal(
                ticker=symbol,
                direction="SHORT",
                entry=float(c[-1]),
                sl=sl,
                pattern="vwap_bounce_bear",
                confidence=65,
            )
        return None
