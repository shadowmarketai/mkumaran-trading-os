"""Gold/silver ratio — long silver if ratio > 88, long gold if < 76."""

from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd
from mcp_server.agents.skills.base_skill import BaseSkill
from mcp_server.agents.skills.indicators import make_signal


class GoldSilverRatioSkill(BaseSkill):
    name = "gold_silver_ratio"
    segment = "commodity"
    timeframe = "1D"
    min_bars = 5
    description = "Mean-reversion on gold/silver ratio extremes"

    def scan(
        self, df: pd.DataFrame, symbol: str, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        data_map = context.get("data_map", {})
        gold_df = data_map.get("GOLD")
        silver_df = data_map.get("SILVER")
        if gold_df is None or silver_df is None:
            return None
        g = float(np.asarray(gold_df["close"], dtype=float)[-1])
        s = float(np.asarray(silver_df["close"], dtype=float)[-1])
        if s <= 0:
            return None
        ratio = g / s
        if ratio > 88:
            sl = round(s * 0.97, 2)
            return make_signal(
                ticker="SILVER",
                direction="LONG",
                entry=s,
                sl=sl,
                pattern="gs_ratio_long_silver",
                confidence=63,
            )
        if ratio < 76:
            sl = round(g * 0.97, 2)
            return make_signal(
                ticker="GOLD",
                direction="LONG",
                entry=g,
                sl=sl,
                pattern="gs_ratio_long_gold",
                confidence=63,
            )
        return None
