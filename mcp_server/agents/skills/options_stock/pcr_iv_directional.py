"""PCR + IV directional — CE/PE buy based on PCR and low IV."""

from __future__ import annotations
from typing import Any
import pandas as pd
from mcp_server.agents.skills.base_skill import BaseSkill
from mcp_server.agents.skills.indicators import make_signal


class PCRIVDirectionalSkill(BaseSkill):
    name = "pcr_iv_directional"
    segment = "options_stock"
    timeframe = "1D"
    min_bars = 1
    description = "Buy CE when PCR > 1.2 and IV < 35, buy PE when PCR < 0.7"

    def scan(
        self, df: pd.DataFrame, symbol: str, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        pcr = context.get("pcr", 1.0)
        atm_iv = context.get("atm_iv", 50)
        if pcr > 1.2 and atm_iv < 35:
            entry = context.get("atm_ce", 0)
            if entry <= 0:
                return None
            sl = round(entry * 0.70, 2)
            return make_signal(
                ticker=symbol,
                direction="LONG",
                entry=entry,
                sl=sl,
                pattern="pcr_iv_bullish_ce",
                confidence=66,
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
                pattern="pcr_bearish_pe",
                confidence=64,
            )
        return None
