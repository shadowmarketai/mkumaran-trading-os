"""VIX premium sell — sell straddle when VIX >= 20 and DTE <= 2."""

from __future__ import annotations
from typing import Any
import pandas as pd
from mcp_server.agents.skills.base_skill import BaseSkill
from mcp_server.agents.skills.indicators import make_signal


class VixPremiumSellSkill(BaseSkill):
    name = "vix_premium_sell"
    segment = "options_index"
    timeframe = "1D"
    min_bars = 1
    description = "Sell straddle when VIX >= 20 and DTE <= 2 for premium decay"

    def scan(
        self, df: pd.DataFrame, symbol: str, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        vix = context.get("vix", 0)
        dte = context.get("dte", 99)
        straddle = context.get("straddle", 0)
        if vix < 20 or dte > 2 or straddle <= 0:
            return None
        entry = straddle
        sl = round(entry * 1.35, 2)
        return make_signal(
            ticker=symbol,
            direction="SHORT",
            entry=entry,
            sl=sl,
            pattern="vix_premium_straddle_sell",
            confidence=68,
        )
