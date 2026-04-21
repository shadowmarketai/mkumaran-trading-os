"""
Commodity Agent — MCX Gold/Silver/Crude/NatGas

Institutional commodity strategies:
  - Gold/Silver ratio mean reversion
  - Crude momentum (trend following)
  - Metal strength (relative performance)
  - ATR breakout on daily bars
  - Correlation with USD (DXY proxy)

MCX hours: 9:00-23:30 IST (extended session)
Scan interval: every 15 minutes.
"""

from __future__ import annotations

import logging
from datetime import time
from typing import Any

import numpy as np

from mcp_server.agents.base_agent import BaseAgent

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

    UNIVERSE = {
        "GOLD": {"lot": 1, "tick": 1},
        "GOLDM": {"lot": 1, "tick": 1},
        "SILVER": {"lot": 1, "tick": 1},
        "SILVERM": {"lot": 1, "tick": 1},
        "CRUDEOIL": {"lot": 1, "tick": 1},
        "NATURALGAS": {"lot": 1, "tick": 0.1},
    }

    def _fetch_data(self, symbol: str):
        try:
            from mcp_server.data_provider import get_provider
            df = get_provider().get_ohlcv_routed(symbol, interval="day", days=60, exchange="MCX")
            if df is not None and not df.empty:
                df.columns = [c.lower() for c in df.columns]
                return df
        except Exception as e:
            logger.debug("[%s] fetch failed for %s: %s", self.name, symbol, e)
        return None

    def scan(self) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        data_map: dict[str, Any] = {}

        for symbol in self.UNIVERSE:
            df = self._fetch_data(symbol)
            if df is not None and len(df) >= 20:
                data_map[symbol] = df

        if not data_map:
            return signals

        # ── ATR Breakout (each commodity) ──
        for symbol, df in data_map.items():
            close = df["close"].values
            high = df["high"].values
            low = df["low"].values
            atr = np.mean(high[-14:] - low[-14:])
            if atr <= 0:
                continue
            last_close = float(close[-1])
            prev_high = float(np.max(high[-20:-1]))
            prev_low = float(np.min(low[-20:-1]))

            # Breakout above 20-day high
            if last_close > prev_high:
                sl = last_close - 1.5 * atr
                target = last_close + 3.0 * atr
                signals.append({
                    "ticker": f"MCX:{symbol}",
                    "direction": "LONG",
                    "entry": round(last_close, 1),
                    "sl": round(sl, 1),
                    "target": round(target, 1),
                    "rrr": round(3.0 / 1.5, 1),
                    "pattern": f"{symbol} breakout above 20d high ({prev_high:.0f})",
                    "confidence": 70,
                })
            # Breakdown below 20-day low
            elif last_close < prev_low:
                sl = last_close + 1.5 * atr
                target = last_close - 3.0 * atr
                signals.append({
                    "ticker": f"MCX:{symbol}",
                    "direction": "SHORT",
                    "entry": round(last_close, 1),
                    "sl": round(sl, 1),
                    "target": round(target, 1),
                    "rrr": 2.0,
                    "pattern": f"{symbol} breakdown below 20d low ({prev_low:.0f})",
                    "confidence": 70,
                })

        # ── Gold/Silver Ratio ──
        if "GOLD" in data_map and "SILVER" in data_map:
            gold_close = float(data_map["GOLD"]["close"].iloc[-1])
            silver_close = float(data_map["SILVER"]["close"].iloc[-1])
            if silver_close > 0:
                ratio = gold_close / silver_close
                # Historical mean ~80-85 for MCX. Below 75 = gold cheap, above 90 = silver cheap
                if ratio > 88:
                    signals.append({
                        "ticker": "MCX:SILVER",
                        "direction": "LONG",
                        "entry": round(silver_close, 0),
                        "sl": round(silver_close * 0.97, 0),
                        "target": round(silver_close * 1.06, 0),
                        "rrr": 2.0,
                        "pattern": f"Gold/Silver ratio {ratio:.1f} (high) → Silver catch-up",
                        "confidence": 65,
                    })
                elif ratio < 76:
                    signals.append({
                        "ticker": "MCX:GOLD",
                        "direction": "LONG",
                        "entry": round(gold_close, 0),
                        "sl": round(gold_close * 0.97, 0),
                        "target": round(gold_close * 1.06, 0),
                        "rrr": 2.0,
                        "pattern": f"Gold/Silver ratio {ratio:.1f} (low) → Gold catch-up",
                        "confidence": 65,
                    })

        logger.info("[%s] scanned %d commodities → %d candidates", self.name, len(data_map), len(signals))
        return signals

    def format_card(self, sig: dict) -> str:
        sep = "\u2501" * 24
        return "\n".join([
            f"{self.card_emoji} {self.card_title}",
            sep,
            f"Commodity: {sig.get('ticker', '?')}",
            f"Direction: {sig.get('direction', '?')}",
            sep,
            f"Entry: \u20b9{sig.get('entry', 0):.0f} | SL: \u20b9{sig.get('sl', 0):.0f} | TGT: \u20b9{sig.get('target', 0):.0f}",
            f"RRR: {sig.get('rrr', 0):.1f}",
            sep,
            f"Pattern: {sig.get('pattern', '?')}",
        ])
