"""EMA 21/55 crossover with ADX > 25 filter and ATR-based stop-loss.

Upgrade from EMA 9/21 (OVERRIDE) after 365-day backtest (May 2025–May 2026):
- EMA 9/21 original: 29.6% WR LONG, 23.8% WR SHORT, Sharpe -2.6 (OVERRIDE)
- EMA 21/55 v2:      45.0% WR, Sharpe 4.3 at RRR 1.5 (TIER_2, paper trading)
Changes: longer EMA periods (less whipsaw) + ATR-based SL (avoids premature stops).
Paper trade for 30 days then promote to live.
"""

from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd
from mcp_server.agents.skills.base_skill import BaseSkill
from mcp_server.agents.skills.indicators import ema, adx, atr, make_signal


class EMACrossADXSkill(BaseSkill):
    name = "ema_cross_adx"
    segment = "futures"
    timeframe = "1D"
    min_bars = 60
    description = "EMA 21/55 crossover confirmed by ADX > 25, ATR-based stop"
    enabled = True   # TIER_2 paper trade — re-test June 13 with fresh Dhan data

    def scan(
        self, df: pd.DataFrame, symbol: str, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        c = np.asarray(df["close"], dtype=float)
        h = np.asarray(df["high"], dtype=float)
        low = np.asarray(df["low"], dtype=float)
        e21 = ema(c, 21)
        e55 = ema(c, 55)
        adx_arr = adx(h, low, c, 14)
        if adx_arr[-1] < 25:
            return None
        cur_atr = atr(h, low, 14)
        if e21[-1] > e55[-1] and e21[-2] <= e55[-2]:
            sl = round(float(c[-1]) - 1.5 * cur_atr, 2)
            return make_signal(
                ticker=symbol,
                direction="LONG",
                entry=float(c[-1]),
                sl=sl,
                pattern="ema21_55_bull_adx",
                confidence=65,
            )
        if e21[-1] < e55[-1] and e21[-2] >= e55[-2]:
            sl = round(float(c[-1]) + 1.5 * cur_atr, 2)
            return make_signal(
                ticker=symbol,
                direction="SHORT",
                entry=float(c[-1]),
                sl=sl,
                pattern="ema21_55_bear_adx",
                confidence=65,
            )
        return None
