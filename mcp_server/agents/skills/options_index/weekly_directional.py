"""Weekly directional — PCR-based CE/PE buy with DTE >= 3."""

from __future__ import annotations
from typing import Any
import pandas as pd
from mcp_server.agents.skills.base_skill import BaseSkill
from mcp_server.agents.skills.indicators import make_signal


class WeeklyDirectionalSkill(BaseSkill):
    name = "weekly_directional"
    segment = "options_index"
    timeframe = "1D"
    min_bars = 1
    description = "Buy CE if PCR > 1.2, PE if PCR < 0.7 with DTE >= 3"

    def scan(
        self, df: pd.DataFrame, symbol: str, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        dte = context.get("dte", 0)
        pcr = context.get("pcr", 1.0)
        if dte < 3:
            return None
        if pcr > 1.2:
            entry = context.get("atm_ce", 0)
            if entry <= 0:
                return None
            sl = round(entry * 0.70, 2)
            return make_signal(
                ticker=symbol,
                direction="LONG",
                entry=entry,
                sl=sl,
                pattern="pcr_bullish_ce_buy",
                confidence=65,
            )
        if pcr < 0.7:
            entry = context.get("atm_pe", 0)
            if entry <= 0:
                return None
            sl = round(entry * 0.70, 2)
            return make_signal(
                ticker=symbol,
                direction="LONG",
                entry=entry,
                sl=sl,
                pattern="pcr_bearish_pe_buy",
                confidence=65,
            )
        return None
