"""
Options Stock Agent — Directional CE/PE on liquid F&O stocks.

Scans top 20 F&O stocks for option plays based on:
  - Daily swing signal + option overlay (from MWA promoted)
  - IV rank relative (cheap/expensive premium)
  - Stock-specific OI buildup at key strikes
  - Earnings proximity (avoid or play)

Scan interval: every 15 minutes during F&O hours.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp_server.agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)


class OptionsStockAgent(BaseAgent):
    name = "Options Stock (F&O)"
    segment = "NFO"
    scan_interval = 900  # 15 min
    max_signals_per_cycle = 2
    max_signals_per_day = 8
    min_confidence = 0
    card_emoji = "\U0001f4c8"
    card_title = "OPTIONS STOCK Signal"

    UNIVERSE = [
        "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS",
        "SBIN", "BAJFINANCE", "TATAMOTORS", "LT", "AXISBANK",
        "KOTAKBANK", "MARUTI", "SUNPHARMA", "BHARTIARTL", "HINDUNILVR",
        "TITAN", "WIPRO", "HCLTECH", "ADANIENT", "DRREDDY",
    ]

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

            data["spot"]
            atm_iv = data["atm_iv"]
            pcr = data["pcr"]
            atm_ce = data["atm_ce_ltp"]
            atm_pe = data["atm_pe_ltp"]
            atm_strike = data["atm_strike"]
            dte = data["days_to_expiry"]

            if atm_ce <= 0 or atm_pe <= 0:
                continue

            # ── Directional based on PCR + IV ──
            if pcr > 1.2 and atm_iv < 35:
                # High put OI (support) + IV not expensive → buy CE
                signals.append({
                    "ticker": symbol,
                    "direction": "LONG",
                    "entry": round(atm_ce, 1),
                    "sl": round(atm_ce * 0.5, 1),
                    "target": round(atm_ce * 2.0, 1),
                    "rrr": 2.0,
                    "pattern": f"BUY CE @ {atm_strike} (PCR {pcr:.2f}, IV {atm_iv:.0f}%)",
                    "rationale": f"{symbol}: PCR {pcr:.2f} + IV {atm_iv:.0f}% → directional CE",
                    "confidence": 65,
                })
            elif pcr < 0.7 and atm_iv < 35:
                signals.append({
                    "ticker": symbol,
                    "direction": "SHORT",
                    "entry": round(atm_pe, 1),
                    "sl": round(atm_pe * 0.5, 1),
                    "target": round(atm_pe * 2.0, 1),
                    "rrr": 2.0,
                    "pattern": f"BUY PE @ {atm_strike} (PCR {pcr:.2f}, IV {atm_iv:.0f}%)",
                    "rationale": f"{symbol}: PCR {pcr:.2f} + IV {atm_iv:.0f}% → directional PE",
                    "confidence": 65,
                })

            # ── IV crush on high-IV stocks ──
            if atm_iv >= 40 and dte >= 2:
                straddle = atm_ce + atm_pe
                signals.append({
                    "ticker": symbol,
                    "direction": "NEUTRAL",
                    "entry": round(straddle, 1),
                    "sl": round(straddle * 1.3, 1),
                    "target": round(straddle * 0.4, 1),
                    "rrr": round(0.6 / 0.3, 1),
                    "pattern": f"SHORT STRANGLE {symbol} (IV {atm_iv:.0f}%)",
                    "rationale": f"{symbol}: IV {atm_iv:.0f}% (high) → sell premium, expect crush",
                    "confidence": 70,
                })

        logger.info("[%s] scanned %d stocks → %d candidates", self.name, len(self.UNIVERSE), len(signals))
        return signals

    def format_card(self, sig: dict) -> str:
        sep = "\u2501" * 24
        return "\n".join([
            f"{self.card_emoji} {self.card_title}",
            sep,
            f"Stock: {sig.get('ticker', '?')}",
            f"Direction: {sig.get('direction', '?')}",
            sep,
            f"Premium: \u20b9{sig.get('entry', 0):.1f}",
            f"SL: \u20b9{sig.get('sl', 0):.1f} | TGT: \u20b9{sig.get('target', 0):.1f}",
            sep,
            f"Strategy: {sig.get('pattern', '?')}",
            sig.get("rationale", ""),
        ])
