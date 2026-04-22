"""Volume breakout — volume > 2x average + new 20-day high."""

from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd
from mcp_server.agents.skills.base_skill import BaseSkill
from mcp_server.agents.skills.indicators import make_signal


class VolumeBreakoutSkill(BaseSkill):
    name = "volume_breakout"
    segment = "futures"
    timeframe = "1D"
    min_bars = 21
    description = "Breakout on volume > 2x 20d average with new 20-day high"

    def scan(
        self, df: pd.DataFrame, symbol: str, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        c = np.asarray(df["close"], dtype=float)
        h = np.asarray(df["high"], dtype=float)
        low = np.asarray(df["low"], dtype=float)
        v = np.asarray(df["volume"], dtype=float)
        avg_vol = float(np.mean(v[-21:-1]))
        if avg_vol <= 0 or v[-1] < 2 * avg_vol:
            return None
        high_20 = float(h[-21:-1].max())
        if c[-1] <= high_20:
            return None
        sl = float(low[-3:].min())
        return make_signal(
            ticker=symbol,
            direction="LONG",
            entry=float(c[-1]),
            sl=sl,
            pattern="volume_breakout_20d_high",
            confidence=70,
        )
