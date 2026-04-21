"""IV crush strangle — sell strangle when IV >= 40 and DTE >= 2."""

from __future__ import annotations
from typing import Any
import pandas as pd
from mcp_server.agents.skills.base_skill import BaseSkill
from mcp_server.agents.skills.indicators import make_signal


class IVCrushStrangleSkill(BaseSkill):
    name = "iv_crush_strangle"
    segment = "options_stock"
    timeframe = "1D"
    min_bars = 1
    description = "Sell strangle when IV >= 40 and DTE >= 2 for IV crush"

    def scan(
        self, df: pd.DataFrame, symbol: str, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        atm_iv = context.get("atm_iv", 0)
        dte = context.get("dte", 0)
        if atm_iv < 40 or dte < 2:
            return None
        ce = context.get("atm_ce", 0)
        pe = context.get("atm_pe", 0)
        if ce <= 0 or pe <= 0:
            return None
        entry = round(ce + pe, 2)
        sl = round(entry * 1.35, 2)
        return make_signal(
            ticker=symbol,
            direction="SHORT",
            entry=entry,
            sl=sl,
            pattern="iv_crush_strangle_sell",
            confidence=67,
        )
