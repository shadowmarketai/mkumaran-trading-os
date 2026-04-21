"""
Forex Agent — CDS Currency Futures (USDINR/EURINR/GBPINR/JPYINR)

Uses modular skills from skills/forex/ for:
  - EMA crossover, RSI reversal, Bollinger squeeze

CDS hours: 9:00-17:00 IST. Scan interval: every 15 minutes.
"""

from __future__ import annotations

import logging
from datetime import time
from typing import Any

from mcp_server.agents.base_agent import BaseAgent
from mcp_server.agents.skills import SkillRegistry

logger = logging.getLogger(__name__)


class ForexAgent(BaseAgent):
    name = "Forex (CDS)"
    segment = "CDS"
    scan_interval = 900
    market_open_time = time(9, 0)
    market_close_time = time(17, 0)
    max_signals_per_cycle = 2
    max_signals_per_day = 4
    min_confidence = 0
    card_emoji = "\U0001f4b1"
    card_title = "FOREX Signal"

    PAIRS = ["USDINR", "EURINR", "GBPINR", "JPYINR"]

    def __init__(self):
        super().__init__()
        self.registry = SkillRegistry("forex")
        self.registry.discover()

    def _fetch(self, pair: str):
        try:
            from mcp_server.data_provider import get_provider

            df = get_provider().get_ohlcv_routed(
                pair, interval="day", days=60, exchange="CDS"
            )
            if df is not None and not df.empty:
                df.columns = [c.lower() for c in df.columns]
                return df
        except Exception:
            pass
        return None

    def scan(self) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        for pair in self.PAIRS:
            df = self._fetch(pair)
            if df is None or len(df) < 25:
                continue
            hits = self.registry.scan_all(df, f"CDS:{pair}", {})
            signals.extend(hits)

        logger.info(
            "[%s] %d skills × %d pairs → %d signals",
            self.name,
            len(self.registry.skills),
            len(self.PAIRS),
            len(signals),
        )
        return signals

    def format_card(self, sig: dict) -> str:
        sep = "\u2501" * 24
        return "\n".join(
            [
                f"{self.card_emoji} {self.card_title}",
                sep,
                f"Pair: {sig.get('ticker', '?')}",
                f"Direction: {sig.get('direction', '?')}",
                sep,
                f"Entry: {sig.get('entry', 0)} | SL: {sig.get('sl', 0)} | TGT: {sig.get('target', 0)}",
                f"RRR: {sig.get('rrr', 0):.1f} | Skill: {sig.get('skill_name', '?')}",
                sep,
                f"Pattern: {sig.get('pattern', '?')}",
            ]
        )
