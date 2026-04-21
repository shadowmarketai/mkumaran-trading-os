"""
Commodity Agent — MCX Gold/Silver/Crude/NatGas

Uses modular skills from skills/commodity/ for institutional strategies:
  - ATR breakout/breakdown
  - Gold/Silver ratio mean reversion

MCX hours: 9:00-23:30 IST (extended session)
Scan interval: every 15 minutes.
"""

from __future__ import annotations

import logging
from datetime import time
from typing import Any

from mcp_server.agents.base_agent import BaseAgent
from mcp_server.agents.skills import SkillRegistry

logger = logging.getLogger(__name__)


class CommodityAgent(BaseAgent):
    name = "Commodity (MCX)"
    segment = "MCX"
    scan_interval = 900
    market_open_time = time(9, 0)
    market_close_time = time(23, 30)
    max_signals_per_cycle = 2
    max_signals_per_day = 6
    min_confidence = 0
    card_emoji = "\U0001f4b0"
    card_title = "COMMODITY Signal"

    UNIVERSE = ["GOLD", "GOLDM", "SILVER", "SILVERM", "CRUDEOIL", "NATURALGAS"]

    def __init__(self):
        super().__init__()
        self.registry = SkillRegistry("commodity")
        self.registry.discover()

    def _fetch(self, symbol: str):
        try:
            from mcp_server.data_provider import get_provider

            df = get_provider().get_ohlcv_routed(
                symbol, interval="day", days=60, exchange="MCX"
            )
            if df is not None and not df.empty:
                df.columns = [c.lower() for c in df.columns]
                return df
        except Exception:
            pass
        return None

    def scan(self) -> list[dict[str, Any]]:
        data_map: dict[str, Any] = {}
        for symbol in self.UNIVERSE:
            df = self._fetch(symbol)
            if df is not None and len(df) >= 20:
                data_map[symbol] = df

        signals: list[dict[str, Any]] = []
        context = {"data_map": data_map}

        for symbol, df in data_map.items():
            hits = self.registry.scan_all(df, f"MCX:{symbol}", context)
            signals.extend(hits)

        logger.info(
            "[%s] %d skills × %d symbols → %d signals",
            self.name,
            len(self.registry.skills),
            len(data_map),
            len(signals),
        )
        return signals

    def format_card(self, sig: dict) -> str:
        sep = "\u2501" * 24
        return "\n".join(
            [
                f"{self.card_emoji} {self.card_title}",
                sep,
                f"Commodity: {sig.get('ticker', '?')}",
                f"Direction: {sig.get('direction', '?')}",
                sep,
                f"Entry: \u20b9{sig.get('entry', 0):.0f} | SL: \u20b9{sig.get('sl', 0):.0f} | TGT: \u20b9{sig.get('target', 0):.0f}",
                f"RRR: {sig.get('rrr', 0):.1f} | Skill: {sig.get('skill_name', '?')}",
                sep,
                f"Pattern: {sig.get('pattern', '?')}",
            ]
        )
