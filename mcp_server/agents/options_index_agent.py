"""
Options Index Agent — Weekly Expiry Plays on NIFTY/BANKNIFTY/FINNIFTY

Uses modular skills from skills/options_index/ for:
  - Expiry day theta sell, Weekly directional, VIX premium sell, Max pain magnet

Scan interval: every 10 minutes during F&O hours.
"""

from __future__ import annotations

import logging
from datetime import date, time
from typing import Any

import pandas as pd

from mcp_server.agents.base_agent import BaseAgent
from mcp_server.agents.skills import SkillRegistry
from mcp_server.market_calendar import now_ist

logger = logging.getLogger(__name__)

EXPIRY_DAY = {"NIFTY": 3, "BANKNIFTY": 2, "FINNIFTY": 1, "MIDCPNIFTY": 0}


class OptionsIndexAgent(BaseAgent):
    name = "Options Index (Weekly)"
    segment = "NFO"
    scan_interval = 600
    market_open_time = time(9, 15)
    market_close_time = time(15, 30)
    max_signals_per_cycle = 2
    max_signals_per_day = 6
    min_confidence = 0
    card_emoji = "\U0001f3af"
    card_title = "OPTIONS INDEX Signal"

    def __init__(self):
        super().__init__()
        self.indices = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]
        self.registry = SkillRegistry("options_index")
        self.registry.discover()

    def scan(self) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        vix = None
        try:
            from mcp_server.options_signal_engine import (
                _get_vix_data,
                _get_chain_and_data,
            )

            vix = _get_vix_data()
        except Exception:
            from mcp_server.options_signal_engine import _get_chain_and_data

        for symbol in self.indices:
            try:
                data = _get_chain_and_data(symbol)
            except Exception:
                continue
            if not data:
                continue

            expiry_weekday = EXPIRY_DAY.get(symbol, 3)
            today_weekday = date.today().weekday()
            dte = (expiry_weekday - today_weekday) % 7 or 7

            context = {
                "spot": data["spot"],
                "pcr": data["pcr"],
                "max_pain": data["max_pain"],
                "atm_strike": data["atm_strike"],
                "atm_ce": data["atm_ce_ltp"],
                "atm_pe": data["atm_pe_ltp"],
                "straddle": data["atm_ce_ltp"] + data["atm_pe_ltp"],
                "dte": dte,
                "is_expiry": expiry_weekday == today_weekday,
                "vix": vix.get("vix", 0) if vix else 0,
                "now_time": now_ist().time(),
            }
            hits = self.registry.scan_all(pd.DataFrame(), symbol, context)
            signals.extend(hits)

        logger.info(
            "[%s] %d skills × %d indices → %d signals",
            self.name,
            len(self.registry.skills),
            len(self.indices),
            len(signals),
        )
        return signals

    def format_card(self, sig: dict) -> str:
        sep = "\u2501" * 24
        return "\n".join(
            [
                f"{self.card_emoji} {self.card_title}",
                sep,
                f"Index: {sig.get('ticker', '?')} | Direction: {sig.get('direction', '?')}",
                sep,
                f"Premium: \u20b9{sig.get('entry', 0):.1f} | SL: \u20b9{sig.get('sl', 0):.1f} | TGT: \u20b9{sig.get('target', 0):.1f}",
                f"Skill: {sig.get('skill_name', '?')}",
                sep,
                f"Strategy: {sig.get('pattern', '?')}",
            ]
        )
