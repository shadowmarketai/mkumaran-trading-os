"""Volume breakout — volume > 3x average + new 20-day high + ATR-based stop.

Upgrade from 2x threshold (OVERRIDE) after 365-day backtest (May 2025–May 2026):
- 2x volume original: 42.1% WR, Sharpe -0.9, only 1 target hit in 57 trades (OVERRIDE)
- 3x volume v2:       58.3% WR, Sharpe 5.4 at RRR 1.5 (TIER_2, paper trading)
Changes: stricter volume filter (3x vs 2x) + ATR-based SL (wider, avoids premature stops).
Paper trade for 30 days then promote to live.
"""

from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd
from mcp_server.agents.skills.base_skill import BaseSkill
from mcp_server.agents.skills.indicators import atr, make_signal


class VolumeBreakoutSkill(BaseSkill):
    name = "volume_breakout"
    segment = "futures"
    timeframe = "1D"
    min_bars = 25
    description = "Breakout on volume > 3x 20d average with new 20-day high, ATR stop"
    enabled = True   # TIER_2 paper trade — re-test June 13 with fresh Dhan data

    def scan(
        self, df: pd.DataFrame, symbol: str, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        c = np.asarray(df["close"], dtype=float)
        h = np.asarray(df["high"], dtype=float)
        low = np.asarray(df["low"], dtype=float)
        v = np.asarray(df["volume"], dtype=float)
        avg_vol = float(np.mean(v[-21:-1]))
        if avg_vol <= 0 or v[-1] < 3 * avg_vol:
            return None
        high_20 = float(h[-21:-1].max())
        if c[-1] <= high_20:
            return None
        cur_atr = atr(h, low, 14)
        sl = round(float(c[-1]) - 1.5 * cur_atr, 2)
        return make_signal(
            ticker=symbol,
            direction="LONG",
            entry=float(c[-1]),
            sl=sl,
            pattern="volume_breakout_3x_20d",
            confidence=68,
        )
