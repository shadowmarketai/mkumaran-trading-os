"""
Volume spike — volume > 2x 10-day average + green candle.

BACKTEST (730-day, Nifty 100, daily): OVERRIDE on all RRR variants.
  RRR 1.5: WR=43.1%, Sharpe=-0.379 → OVERRIDE
  RRR 2.0: WR=40.6%, Sharpe=-0.303 → OVERRIDE
Disabled. Volume alone without breakout has no edge standalone.
"""

from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd
from mcp_server.agents.skills.base_skill import BaseSkill
from mcp_server.agents.skills.indicators import make_signal


class VolumeSpikeSkill(BaseSkill):
    name = "volume_spike"
    segment = "equity_swing"
    timeframe = "1D"
    min_bars = 12
    enabled = False  # OVERRIDE — backtest: Sharpe -0.38 at best, no standalone edge
    description = "Volume spike above 2x 10-day average with bullish close"

    def scan(
        self, df: pd.DataFrame, symbol: str, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        c = np.asarray(df["close"], dtype=float)
        o = np.asarray(df["open"], dtype=float)
        low = np.asarray(df["low"], dtype=float)
        v = np.asarray(df["volume"], dtype=float)
        avg_vol = float(np.mean(v[-11:-1]))
        if avg_vol <= 0 or v[-1] < 2 * avg_vol:
            return None
        if c[-1] <= o[-1]:
            return None
        sl = float(low[-3:].min())
        return make_signal(
            ticker=symbol,
            direction="LONG",
            entry=float(c[-1]),
            sl=sl,
            pattern="volume_spike_2x",
            confidence=65,
        )
