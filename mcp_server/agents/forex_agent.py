"""
Forex Agent — CDS Currency Futures (USDINR/EURINR/GBPINR/JPYINR)

Strategies:
  - EMA crossover on daily bars
  - RSI reversal (oversold/overbought)
  - Bollinger Band squeeze → breakout
  - DXY correlation proxy (USDINR tracks DXY inversely)

CDS hours: 9:00-17:00 IST
Scan interval: every 15 minutes.
"""

from __future__ import annotations

import logging
from datetime import time
from typing import Any

import numpy as np

from mcp_server.agents.base_agent import BaseAgent

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

    def _fetch(self, pair: str):
        try:
            from mcp_server.data_provider import get_provider
            df = get_provider().get_ohlcv_routed(pair, interval="day", days=60, exchange="CDS")
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

            close = df["close"].values
            high = df["high"].values
            low = df["low"].values

            # EMA 9/21
            ema9 = self._ema(close, 9)
            ema21 = self._ema(close, 21)

            # RSI 14
            rsi = self._rsi(close, 14)

            # Bollinger Bands
            sma20 = np.convolve(close, np.ones(20)/20, mode='valid')
            if len(sma20) < 2:
                continue
            std20 = np.std(close[-20:])
            bb_upper = sma20[-1] + 2 * std20
            bb_lower = sma20[-1] - 2 * std20
            bb_width = (bb_upper - bb_lower) / sma20[-1] * 100

            last = float(close[-1])
            atr = float(np.mean(high[-14:] - low[-14:]))
            if atr <= 0:
                continue

            # ── EMA Cross ──
            if ema9[-1] > ema21[-1] and ema9[-2] <= ema21[-2]:
                signals.append({
                    "ticker": f"CDS:{pair}",
                    "direction": "LONG",
                    "entry": round(last, 4),
                    "sl": round(last - 1.5 * atr, 4),
                    "target": round(last + 3.0 * atr, 4),
                    "rrr": 2.0,
                    "pattern": f"{pair} EMA 9/21 bullish cross",
                    "confidence": 65,
                })
            elif ema9[-1] < ema21[-1] and ema9[-2] >= ema21[-2]:
                signals.append({
                    "ticker": f"CDS:{pair}",
                    "direction": "SHORT",
                    "entry": round(last, 4),
                    "sl": round(last + 1.5 * atr, 4),
                    "target": round(last - 3.0 * atr, 4),
                    "rrr": 2.0,
                    "pattern": f"{pair} EMA 9/21 bearish cross",
                    "confidence": 65,
                })

            # ── RSI Reversal ──
            if len(rsi) >= 2:
                if rsi[-2] < 30 and rsi[-1] >= 30:
                    signals.append({
                        "ticker": f"CDS:{pair}",
                        "direction": "LONG",
                        "entry": round(last, 4),
                        "sl": round(last - 1.5 * atr, 4),
                        "target": round(last + 2.5 * atr, 4),
                        "rrr": round(2.5/1.5, 1),
                        "pattern": f"{pair} RSI oversold bounce ({rsi[-1]:.0f})",
                        "confidence": 60,
                    })
                elif rsi[-2] > 70 and rsi[-1] <= 70:
                    signals.append({
                        "ticker": f"CDS:{pair}",
                        "direction": "SHORT",
                        "entry": round(last, 4),
                        "sl": round(last + 1.5 * atr, 4),
                        "target": round(last - 2.5 * atr, 4),
                        "rrr": round(2.5/1.5, 1),
                        "pattern": f"{pair} RSI overbought reject ({rsi[-1]:.0f})",
                        "confidence": 60,
                    })

            # ── BB Squeeze Breakout ──
            if bb_width < 1.0:  # Tight squeeze
                if last > bb_upper:
                    signals.append({
                        "ticker": f"CDS:{pair}",
                        "direction": "LONG",
                        "entry": round(last, 4),
                        "sl": round(sma20[-1], 4),
                        "target": round(last + 2 * (last - sma20[-1]), 4),
                        "rrr": 2.0,
                        "pattern": f"{pair} BB squeeze breakout (width {bb_width:.2f}%)",
                        "confidence": 70,
                    })

        logger.info("[%s] scanned %d pairs → %d candidates", self.name, len(self.PAIRS), len(signals))
        return signals

    @staticmethod
    def _ema(data, span):
        alpha = 2 / (span + 1)
        ema = np.zeros_like(data, dtype=float)
        ema[0] = data[0]
        for i in range(1, len(data)):
            ema[i] = alpha * data[i] + (1 - alpha) * ema[i-1]
        return ema

    @staticmethod
    def _rsi(data, period=14):
        deltas = np.diff(data)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = np.convolve(gains, np.ones(period)/period, mode='valid')
        avg_loss = np.convolve(losses, np.ones(period)/period, mode='valid')
        rs = avg_gain / np.where(avg_loss > 0, avg_loss, 1e-10)
        return 100 - (100 / (1 + rs))

    def format_card(self, sig: dict) -> str:
        sep = "\u2501" * 24
        return "\n".join([
            f"{self.card_emoji} {self.card_title}",
            sep,
            f"Pair: {sig.get('ticker', '?')}",
            f"Direction: {sig.get('direction', '?')}",
            sep,
            f"Entry: {sig.get('entry', 0)} | SL: {sig.get('sl', 0)} | TGT: {sig.get('target', 0)}",
            f"RRR: {sig.get('rrr', 0):.1f}",
            sep,
            f"Pattern: {sig.get('pattern', '?')}",
        ])
