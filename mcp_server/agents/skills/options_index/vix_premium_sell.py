"""
VIX premium sell — sell straddle when VIX >= 18 and DTE <= 2.

PROXY BACKTEST (730-day, Nifty + VIX):
  VIX >= 20, DTE <= 2: WR=41.7%, Sharpe=6.0, n=12 → OVERRIDE
  VIX >= 18, DTE <= 2: WR=63.6%, Sharpe=12.2, n=33 → TIER_1

Original threshold VIX>=20 is OVERRIDE: when VIX is very high, Nifty
actually moves more (correlation), breaking the straddle. VIX>=18 is
the validated range — elevated but not panic-level premium.
"""

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
        if vix < 18 or dte > 2 or straddle <= 0:  # 18 validated; >=20 is OVERRIDE
            return None
        entry = straddle
        sl = round(entry * 1.35, 2)
        return make_signal(
            ticker=symbol, direction="SHORT",
            entry=entry, sl=sl,
            pattern="vix_premium_straddle_sell",
            confidence=68, validated=True,
        )
