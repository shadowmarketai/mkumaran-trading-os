"""
BaseSkill — abstract interface for all trading skills.

Every skill is a self-contained module that:
  - Receives a DataFrame + context dict
  - Returns a signal dict or None
  - Tracks its own Bayesian win rate
  - Can be enabled/disabled via env var
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd


class BaseSkill(ABC):
    """Abstract base for all trading skills."""

    name: str = "base_skill"
    segment: str = "NSE"
    timeframe: str = "1D"
    min_bars: int = 15
    version: str = "1.0.0"
    description: str = ""

    @abstractmethod
    def scan(
        self, df: pd.DataFrame, symbol: str, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Analyze data and return a signal dict or None.

        Args:
            df: OHLCV DataFrame (lowercase columns: open, high, low, close, volume)
            symbol: Ticker symbol (e.g. "RELIANCE", "GOLD")
            context: Segment-specific data (vix, pcr, max_pain, data_map, etc.)

        Returns:
            Signal dict with keys: ticker, direction, entry, sl, target, rrr, pattern, confidence
            or None if no signal.
        """

    def backtest_stats(self) -> dict[str, Any]:
        """Fetch this skill's Bayesian win-rate stats."""
        try:
            from mcp_server.scanner_bayesian import get_scanner_stats

            return get_scanner_stats(self.name) or {}
        except Exception:
            return {}

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "segment": self.segment,
            "timeframe": self.timeframe,
            "min_bars": self.min_bars,
            "version": self.version,
            "description": self.description,
        }
