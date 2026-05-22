"""
Gold/Silver ratio mean-reversion skill.

BACKTEST RESULTS (2024-2026, 730 days, GC=F / SI=F):
  hold_10d:  WR=69.9%, Sharpe=6.59, n=93  → TIER_1
  sl3_rrr2:  WR=61.1%, Sharpe=9.12, n=90  → TIER_1
  sl3_rrr3:  WR=57.8%, Sharpe=9.51, n=90  → TIER_1  ← live variant

Signal logic:
  ratio > 88 → LONG SILVER (silver cheap vs gold, mean-revert up)
  ratio < 76 → LONG GOLD   (gold cheap vs silver, mean-revert up)
  SL: 3% | Target: 9% (RRR 3.0)
"""

from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd
from mcp_server.agents.skills.base_skill import BaseSkill
from mcp_server.agents.skills.indicators import make_signal

_SL_PCT    = 0.03   # 3% stop loss
_TGT_MULT  = 3.0    # RRR 3 → 9% target


class GoldSilverRatioSkill(BaseSkill):
    name = "gold_silver_ratio"
    segment = "commodity"
    timeframe = "1D"
    min_bars = 5
    version = "2.0.0"
    description = (
        "Gold/silver ratio mean-reversion. TIER_1 validated: WR=61-70%, "
        "Sharpe=6.6-9.5 (730-day backtest). SL=3%, RRR=3."
    )

    def scan(
        self, df: pd.DataFrame, symbol: str, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        data_map = context.get("data_map", {})
        gold_df   = data_map.get("GOLD")
        silver_df = data_map.get("SILVER")
        if gold_df is None or silver_df is None:
            return None
        g = float(np.asarray(gold_df["close"],   dtype=float)[-1])
        s = float(np.asarray(silver_df["close"], dtype=float)[-1])
        if s <= 0:
            return None
        ratio = g / s
        if ratio > 88:
            sl     = round(s * (1 - _SL_PCT), 2)
            target = round(s * (1 + _SL_PCT * _TGT_MULT), 2)
            return make_signal(
                ticker="SILVER", direction="LONG",
                entry=s, sl=sl, target=target,
                pattern="gs_ratio_long_silver", confidence=72, validated=True,
            )
        if ratio < 76:
            sl     = round(g * (1 - _SL_PCT), 2)
            target = round(g * (1 + _SL_PCT * _TGT_MULT), 2)
            return make_signal(
                ticker="GOLD", direction="LONG",
                entry=g, sl=sl, target=target,
                pattern="gs_ratio_long_gold", confidence=72, validated=True,
            )
        return None
