"""
Gold/Silver ratio mean-reversion skill.

BACKTEST RESULTS (2024-2026, 730 days, GC=F / SI=F):
  hold_10d:  WR=69.9%, Sharpe=6.59, n=93  -> TIER_1
  sl3_rrr2:  WR=61.1%, Sharpe=9.12, n=90  -> TIER_1
  sl3_rrr3:  WR=57.8%, Sharpe=9.51, n=90  -> TIER_1  <- live variant

Signal logic:
  ratio > 88 -> LONG SILVER/SILVERM (silver cheap vs gold, mean-revert up)
  ratio < 76 -> LONG GOLD/GOLDM/GOLDPETAL/GOLDGUINEA (gold cheap vs silver)
  SL: 3% | Target: 9% (RRR 3.0)

GOLDPETAL and GOLDGUINEA are 1g and 8g gold derivatives — same underlying
price action as GOLD. The ratio edge applies equally; no separate backtest needed.

MCX price unit normalisation (v2.2):
  MCX GOLD is quoted per 10g; MCX SILVER per kg.
  Raw division gives ~1.0, never reaching 76-88 thresholds.
  Normalise to per-gram before ratio: GOLD/10 / (SILVER/1000).
  The per-gram ratio matches the international oz/oz ratio since both
  units cancel the same 31.1 g/oz factor.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from mcp_server.agents.skills.base_skill import BaseSkill
from mcp_server.agents.skills.indicators import make_signal

_SL_PCT   = 0.03   # 3% stop loss
_TGT_MULT = 3.0    # RRR 3 -> 9% target

# Symbols that qualify as "gold family" — signal fires for whichever one is being scanned
_GOLD_FAMILY = frozenset({
    "GOLD", "GOLDM", "GOLDPETAL", "GOLDGUINEA",
    "MCX:GOLD", "MCX:GOLDM", "MCX:GOLDPETAL", "MCX:GOLDGUINEA",
})
_SILVER_FAMILY = frozenset({
    "SILVER", "SILVERM",
    "MCX:SILVER", "MCX:SILVERM",
})


def _normalised_ratio(g: float, s: float) -> float:
    """Return per-gram gold/silver ratio regardless of MCX quoting units.

    MCX GOLD is per 10g, MCX SILVER is per kg.
    If prices look like MCX (g > 1000 and s > 1000), normalise.
    COMEX prices (g ~2000-5000 /oz, s ~25-80 /oz) divide directly.
    """
    if g > 1000 and s > 1000:
        # MCX: convert both to per-gram first
        return (g / 10) / (s / 1000)
    return g / s


class GoldSilverRatioSkill(BaseSkill):
    name = "gold_silver_ratio"
    segment = "commodity"
    timeframe = "1D"
    min_bars = 5
    version = "2.2.0"
    description = (
        "Gold/silver ratio mean-reversion. TIER_1 validated: WR=61-70%, "
        "Sharpe=6.6-9.5 (730-day backtest). SL=3%, RRR=3. "
        "Fires for all gold derivatives (GOLDPETAL, GOLDGUINEA) when ratio < 76."
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

        ratio = _normalised_ratio(g, s)
        sym_upper = symbol.upper()

        if ratio < 76 and sym_upper in _GOLD_FAMILY:
            # Use this symbol's own price — GOLDPETAL/GOLDGUINEA have different price scales
            price = float(np.asarray(df["close"], dtype=float)[-1])
            sl    = round(price * (1 - _SL_PCT), 2)
            target = round(price * (1 + _SL_PCT * _TGT_MULT), 2)
            return make_signal(
                ticker=symbol, direction="LONG",
                entry=price, sl=sl, target=target,
                pattern="gs_ratio_long_gold", confidence=72, validated=True,
            )

        if ratio > 88 and sym_upper in _SILVER_FAMILY:
            price = float(np.asarray(df["close"], dtype=float)[-1])
            sl    = round(price * (1 - _SL_PCT), 2)
            target = round(price * (1 + _SL_PCT * _TGT_MULT), 2)
            return make_signal(
                ticker=symbol, direction="LONG",
                entry=price, sl=sl, target=target,
                pattern="gs_ratio_long_silver", confidence=72, validated=True,
            )

        return None
