"""Max-pain magnet — directional when spot is 0.5-2.5% from max pain."""

from __future__ import annotations
from typing import Any
import pandas as pd
from mcp_server.agents.skills.base_skill import BaseSkill
from mcp_server.agents.skills.indicators import make_signal


class MaxPainMagnetSkill(BaseSkill):
    name = "max_pain_magnet"
    segment = "options_index"
    timeframe = "1D"
    min_bars = 1
    description = "Directional trade when spot is 0.5-2.5% from max pain level"

    def scan(
        self, df: pd.DataFrame, symbol: str, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        spot = context.get("spot", 0)
        max_pain = context.get("max_pain", 0)
        if spot <= 0 or max_pain <= 0:
            return None
        gap_pct = (spot - max_pain) / max_pain * 100
        abs_gap = abs(gap_pct)
        if abs_gap < 0.5 or abs_gap > 2.5:
            return None
        if gap_pct > 0:  # spot above max_pain → expect pull-down
            entry = context.get("atm_pe", 0)
            if entry <= 0:
                return None
            sl = round(entry * 0.70, 2)
            return make_signal(
                ticker=symbol,
                direction="LONG",
                entry=entry,
                sl=sl,
                pattern="max_pain_bearish",
                confidence=62,
            )
        entry = context.get("atm_ce", 0)
        if entry <= 0:
            return None
        sl = round(entry * 0.70, 2)
        return make_signal(
            ticker=symbol,
            direction="LONG",
            entry=entry,
            sl=sl,
            pattern="max_pain_bullish",
            confidence=62,
        )
