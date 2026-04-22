"""ORB breakout — first 15-min range breakout with volume."""

from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd
from mcp_server.agents.skills.base_skill import BaseSkill
from mcp_server.agents.skills.indicators import make_signal


class ORBBreakoutSkill(BaseSkill):
    name = "orb_breakout"
    segment = "equity_intraday"
    timeframe = "5m"
    min_bars = 6
    description = "Opening range breakout on first 15-min high/low with volume"

    def scan(
        self, df: pd.DataFrame, symbol: str, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        h = np.asarray(df["high"], dtype=float)
        low = np.asarray(df["low"], dtype=float)
        c = np.asarray(df["close"], dtype=float)
        v = np.asarray(df["volume"], dtype=float)
        orb_high = float(h[:3].max())  # first 3 x 5m = 15 min
        orb_low = float(low[:3].min())
        avg_vol = float(np.mean(v[:3]))
        if avg_vol <= 0 or v[-1] < 1.2 * avg_vol:
            return None
        if c[-1] > orb_high:
            return make_signal(
                ticker=symbol,
                direction="LONG",
                entry=float(c[-1]),
                sl=orb_low,
                pattern="orb_breakout_high",
                confidence=67,
            )
        if c[-1] < orb_low:
            return make_signal(
                ticker=symbol,
                direction="SHORT",
                entry=float(c[-1]),
                sl=orb_high,
                pattern="orb_breakout_low",
                confidence=67,
            )
        return None
