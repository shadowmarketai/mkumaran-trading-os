"""Expiry-day theta sell — ATM straddle on expiry before 11 AM."""

from __future__ import annotations
from typing import Any
import pandas as pd
from mcp_server.agents.skills.base_skill import BaseSkill
from mcp_server.agents.skills.indicators import make_signal


class ExpiryThetaSellSkill(BaseSkill):
    name = "expiry_theta_sell"
    segment = "options_index"
    timeframe = "5m"
    min_bars = 1
    description = "Sell ATM straddle on expiry day before 11 AM for theta decay"

    def scan(
        self, df: pd.DataFrame, symbol: str, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        if not context.get("is_expiry"):
            return None
        straddle = context.get("straddle", 0)
        atm_strike = context.get("atm_strike", 0)
        if straddle <= 0 or atm_strike <= 0:
            return None
        entry = straddle
        sl = round(entry * 1.30, 2)
        return make_signal(
            ticker=symbol,
            direction="SHORT",
            entry=entry,
            sl=sl,
            pattern="expiry_theta_straddle_sell",
            confidence=70,
        )
