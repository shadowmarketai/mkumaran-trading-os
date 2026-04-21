"""
Futures Agent — NFO Index + Stock Futures

Uses modular skills from skills/futures/ for:
  - EMA cross + ADX trend, volume breakout

Scan interval: every 15 minutes during F&O hours.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp_server.agents.base_agent import BaseAgent
from mcp_server.agents.skills import SkillRegistry

logger = logging.getLogger(__name__)


class FuturesAgent(BaseAgent):
    name = "Futures (NFO)"
    segment = "NFO"
    scan_interval = 900
    max_signals_per_cycle = 2
    max_signals_per_day = 6
    min_confidence = 0
    card_emoji = "\U0001f4c9"
    card_title = "FUTURES Signal"

    INDEX_UNIVERSE = ["NIFTY", "BANKNIFTY"]
    STOCK_UNIVERSE = [
        "RELIANCE",
        "HDFCBANK",
        "ICICIBANK",
        "INFY",
        "TCS",
        "SBIN",
        "BAJFINANCE",
        "TATAMOTORS",
        "LT",
        "AXISBANK",
    ]

    def __init__(self):
        super().__init__()
        self.registry = SkillRegistry("futures")
        self.registry.discover()

    def _fetch(self, symbol: str, exchange: str = "NSE"):
        try:
            from mcp_server.data_provider import get_provider

            df = get_provider().get_ohlcv_routed(
                symbol, interval="day", days=60, exchange=exchange
            )
            if df is not None and not df.empty:
                df.columns = [c.lower() for c in df.columns]
                return df
        except Exception:
            pass
        return None

    def scan(self) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        tickers = [(t, "NFO") for t in self.INDEX_UNIVERSE] + [
            (t, "NSE") for t in self.STOCK_UNIVERSE
        ]

        for symbol, exchange in tickers:
            df = self._fetch(symbol, exchange)
            if df is None or len(df) < 25:
                continue
            hits = self.registry.scan_all(df, f"NFO:{symbol}", {})
            signals.extend(hits)

        logger.info(
            "[%s] %d skills × %d futures → %d signals",
            self.name,
            len(self.registry.skills),
            len(tickers),
            len(signals),
        )
        return signals

    def format_card(self, sig: dict) -> str:
        sep = "\u2501" * 24
        return "\n".join(
            [
                f"{self.card_emoji} {self.card_title}",
                sep,
                f"Future: {sig.get('ticker', '?')}",
                f"Direction: {sig.get('direction', '?')}",
                sep,
                f"Entry: \u20b9{sig.get('entry', 0):.1f} | SL: \u20b9{sig.get('sl', 0):.1f} | TGT: \u20b9{sig.get('target', 0):.1f}",
                f"RRR: {sig.get('rrr', 0):.1f} | Skill: {sig.get('skill_name', '?')}",
                sep,
                f"Pattern: {sig.get('pattern', '?')}",
            ]
        )
