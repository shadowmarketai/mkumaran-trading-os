"""
Options Index Agent — Weekly Expiry Plays on NIFTY/BANKNIFTY/FINNIFTY

Institutional-grade weekly options strategies based on:
  - Day of week relative to expiry (Mon=directional, Thu=theta)
  - VIX level + trend (high→sell, low→buy, spike→sell aggressively)
  - PCR extreme → contrarian
  - Max pain magnet → mean reversion
  - OI buildup → support/resistance
  - Straddle premium decay curve

Weekly expiry schedule (NSE):
  NIFTY      → Thursday
  BANKNIFTY  → Wednesday (moved from Tuesday)
  FINNIFTY   → Tuesday
  MIDCPNIFTY → Monday

Scan interval: every 10 minutes during F&O hours.
"""

from __future__ import annotations

import logging
from datetime import date, time
from typing import Any

from mcp_server.agents.base_agent import BaseAgent
from mcp_server.market_calendar import now_ist

logger = logging.getLogger(__name__)

EXPIRY_DAY = {
    "NIFTY": 3,       # Thursday (0=Mon)
    "BANKNIFTY": 2,   # Wednesday
    "FINNIFTY": 1,     # Tuesday
    "MIDCPNIFTY": 0,   # Monday
}


class OptionsIndexAgent(BaseAgent):
    name = "Options Index (Weekly)"
    segment = "NFO"
    scan_interval = 600  # 10 min
    market_open_time = time(9, 15)
    market_close_time = time(15, 30)
    max_signals_per_cycle = 2
    max_signals_per_day = 6
    min_confidence = 0  # options signals are rule-based, not AI-scored
    card_emoji = "\U0001f3af"
    card_title = "OPTIONS INDEX Signal"

    def __init__(self):
        super().__init__()
        self.indices = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]

    def _get_data(self, symbol: str) -> dict[str, Any] | None:
        try:
            from mcp_server.options_signal_engine import _get_chain_and_data
            return _get_chain_and_data(symbol)
        except Exception as e:
            logger.debug("[%s] data failed for %s: %s", self.name, symbol, e)
            return None

    def _get_vix(self) -> dict[str, float] | None:
        try:
            from mcp_server.options_signal_engine import _get_vix_data
            return _get_vix_data()
        except Exception:
            return None

    def _days_to_expiry(self, symbol: str) -> int:
        """Days until this symbol's weekly expiry."""
        expiry_weekday = EXPIRY_DAY.get(symbol, 3)
        today_weekday = date.today().weekday()
        diff = (expiry_weekday - today_weekday) % 7
        return diff if diff > 0 else 7  # if today IS expiry, next is 7 days

    def _is_expiry_day(self, symbol: str) -> bool:
        return EXPIRY_DAY.get(symbol, -1) == date.today().weekday()

    def scan(self) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        vix = self._get_vix()
        vix_val = vix.get("vix", 0) if vix else 0
        vix.get("pct_change", 0) if vix else 0

        for symbol in self.indices:
            data = self._get_data(symbol)
            if not data:
                continue

            dte = self._days_to_expiry(symbol)
            is_expiry = self._is_expiry_day(symbol)
            spot = data["spot"]
            pcr = data["pcr"]
            max_pain = data["max_pain"]
            atm_ce = data["atm_ce_ltp"]
            atm_pe = data["atm_pe_ltp"]
            atm_strike = data["atm_strike"]
            straddle = atm_ce + atm_pe

            if straddle <= 0:
                continue

            # ── Strategy 1: Expiry Day Theta Sell ──
            if is_expiry and now_ist().time() < time(11, 0):
                signals.append({
                    "ticker": symbol,
                    "direction": "NEUTRAL",
                    "entry": straddle,
                    "sl": round(straddle * 1.3, 1),
                    "target": round(straddle * 0.2, 1),
                    "rrr": round(0.8 / 0.3, 1),
                    "pattern": f"Expiry day SHORT STRADDLE @ {atm_strike}",
                    "rationale": f"{symbol} expiry today — sell ATM straddle, theta decay accelerates",
                    "confidence": 75,
                })

            # ── Strategy 2: Early Week Directional ──
            if dte >= 3 and not is_expiry:
                if pcr > 1.2:
                    # High PCR = excess puts = bullish contrarian
                    signals.append({
                        "ticker": symbol,
                        "direction": "LONG",
                        "entry": round(atm_ce, 1),
                        "sl": round(atm_ce * 0.5, 1),
                        "target": round(atm_ce * 2.0, 1),
                        "rrr": 2.0,
                        "pattern": f"Weekly BUY CE @ {atm_strike} (PCR {pcr:.2f})",
                        "rationale": f"PCR {pcr:.2f} (bullish bias) + {dte}d to expiry → buy CE",
                        "confidence": 65,
                    })
                elif pcr < 0.7:
                    signals.append({
                        "ticker": symbol,
                        "direction": "SHORT",
                        "entry": round(atm_pe, 1),
                        "sl": round(atm_pe * 0.5, 1),
                        "target": round(atm_pe * 2.0, 1),
                        "rrr": 2.0,
                        "pattern": f"Weekly BUY PE @ {atm_strike} (PCR {pcr:.2f})",
                        "rationale": f"PCR {pcr:.2f} (bearish bias) + {dte}d to expiry → buy PE",
                        "confidence": 65,
                    })

            # ── Strategy 3: VIX-based ──
            if vix_val >= 20 and dte <= 2:
                signals.append({
                    "ticker": symbol,
                    "direction": "NEUTRAL",
                    "entry": round(straddle, 1),
                    "sl": round(straddle * 1.5, 1),
                    "target": round(straddle * 0.3, 1),
                    "rrr": round(0.7 / 0.5, 1),
                    "pattern": f"VIX {vix_val:.0f} SHORT STRANGLE ({dte}DTE)",
                    "rationale": f"VIX {vix_val:.0f} (high) + {dte}DTE → sell inflated premium",
                    "confidence": 70,
                })

            # ── Strategy 4: Max Pain Magnet ──
            if max_pain and spot:
                dist_pct = abs(spot - max_pain) / spot * 100
                if 0.5 <= dist_pct <= 2.5:
                    direction = "LONG" if spot < max_pain else "SHORT"
                    opt_type = "CE" if direction == "LONG" else "PE"
                    premium = atm_ce if direction == "LONG" else atm_pe
                    if premium > 0:
                        signals.append({
                            "ticker": symbol,
                            "direction": direction,
                            "entry": round(premium, 1),
                            "sl": round(premium * 0.5, 1),
                            "target": round(premium * 1.8, 1),
                            "rrr": round(0.8 / 0.5, 1),
                            "pattern": f"Max pain {max_pain:.0f} → BUY {opt_type} ({dist_pct:.1f}% away)",
                            "rationale": f"Spot {spot:.0f} vs max pain {max_pain:.0f} → mean reversion",
                            "confidence": 60,
                        })

        logger.info("[%s] scanned %d indices → %d candidates", self.name, len(self.indices), len(signals))
        return signals

    def format_card(self, sig: dict) -> str:
        sep = "\u2501" * 24
        lines = [
            f"{self.card_emoji} {self.card_title}",
            sep,
            f"Index: {sig.get('ticker', '?')}",
            f"Direction: {sig.get('direction', '?')}",
            sep,
            f"Premium: \u20b9{sig.get('entry', 0):.1f}",
            f"SL: \u20b9{sig.get('sl', 0):.1f} | TGT: \u20b9{sig.get('target', 0):.1f}",
            sep,
            f"Strategy: {sig.get('pattern', '?')}",
        ]
        if sig.get("rationale"):
            lines.append(sig["rationale"])
        return "\n".join(lines)
