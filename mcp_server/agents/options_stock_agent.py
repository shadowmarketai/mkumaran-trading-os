"""
Options Stock Agent — Directional CE/PE on liquid F&O stocks.

Uses modular skills from skills/options_stock/.
Scan interval: every 15 minutes during F&O hours.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from mcp_server.agents.base_agent import BaseAgent
from mcp_server.agents.skills import SkillRegistry

logger = logging.getLogger(__name__)


class OptionsStockAgent(BaseAgent):
    name = "Options Stock (F&O)"
    segment = "NFO"
    scan_interval = 900
    max_signals_per_cycle = 2
    max_signals_per_day = 8
    min_confidence = 0
    card_emoji = "\U0001f4c8"
    card_title = "OPTIONS STOCK Signal"

    UNIVERSE = [
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
        "KOTAKBANK",
        "MARUTI",
        "SUNPHARMA",
        "BHARTIARTL",
        "HINDUNILVR",
        "TITAN",
        "WIPRO",
        "HCLTECH",
        "ADANIENT",
        "DRREDDY",
    ]

    def __init__(self):
        super().__init__()
        self.registry = SkillRegistry("options_stock")
        self.registry.discover()

    def scan(self) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        try:
            from mcp_server.options_signal_engine import _get_chain_and_data
        except ImportError:
            return signals

        for symbol in self.UNIVERSE:
            data = _get_chain_and_data(symbol)
            if not data:
                continue
            context = {
                "pcr": data["pcr"],
                "atm_iv": data["atm_iv"],
                "atm_ce": data["atm_ce_ltp"],
                "atm_pe": data["atm_pe_ltp"],
                "atm_strike": data["atm_strike"],
                "dte": data["days_to_expiry"],
            }
            hits = self.registry.scan_all(pd.DataFrame(), symbol, context)
            signals.extend(hits)

        logger.info(
            "[%s] %d skills × %d stocks → %d signals",
            self.name,
            len(self.registry.skills),
            len(self.UNIVERSE),
            len(signals),
        )
        return signals

    def format_card(self, sig: dict) -> str:
        sep = "\u2501" * 24
        return "\n".join(
            [
                f"{self.card_emoji} {self.card_title}",
                sep,
                f"Stock: {sig.get('ticker', '?')} | Direction: {sig.get('direction', '?')}",
                sep,
                f"Premium: \u20b9{sig.get('entry', 0):.1f} | SL: \u20b9{sig.get('sl', 0):.1f} | TGT: \u20b9{sig.get('target', 0):.1f}",
                f"Skill: {sig.get('skill_name', '?')}",
                sep,
                f"Strategy: {sig.get('pattern', '?')}",
                sig.get("rationale", ""),
            ]
        )
