"""
Futures Agent — NFO Index + Stock Futures

Trend-following strategies on futures contracts:
  - NIFTY/BANKNIFTY futures trend (EMA + ADX)
  - Stock futures breakout (high volume + range expansion)
  - Basis premium/discount plays (futures premium → trend confirmation)

Scan interval: every 15 minutes during F&O hours.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from mcp_server.agents.base_agent import BaseAgent

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
        "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS",
        "SBIN", "BAJFINANCE", "TATAMOTORS", "LT", "AXISBANK",
    ]

    def _fetch(self, symbol: str, exchange: str = "NSE"):
        try:
            from mcp_server.data_provider import get_provider
            df = get_provider().get_ohlcv_routed(symbol, interval="day", days=60, exchange=exchange)
            if df is not None and not df.empty:
                df.columns = [c.lower() for c in df.columns]
                return df
        except Exception:
            pass
        return None

    def scan(self) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []

        all_tickers = [(t, "NFO") for t in self.INDEX_UNIVERSE] + [(t, "NSE") for t in self.STOCK_UNIVERSE]

        for symbol, exchange in all_tickers:
            df = self._fetch(symbol, exchange)
            if df is None or len(df) < 25:
                continue

            close = df["close"].values
            high = df["high"].values
            low = df["low"].values
            volume = df["volume"].values

            # EMA 9/21
            ema9 = self._ema(close, 9)
            ema21 = self._ema(close, 21)

            # ADX
            adx = self._adx(high, low, close, 14)

            last = float(close[-1])
            atr = float(np.mean(high[-14:] - low[-14:]))
            if atr <= 0:
                continue

            # ── EMA Cross + Strong Trend (ADX > 25) ──
            if len(adx) >= 1 and adx[-1] > 25:
                if ema9[-1] > ema21[-1] and ema9[-2] <= ema21[-2]:
                    signals.append({
                        "ticker": f"NFO:{symbol}",
                        "direction": "LONG",
                        "entry": round(last, 1),
                        "sl": round(last - 1.5 * atr, 1),
                        "target": round(last + 3.0 * atr, 1),
                        "rrr": 2.0,
                        "pattern": f"{symbol} FUT EMA cross + ADX {adx[-1]:.0f}",
                        "confidence": 70,
                    })
                elif ema9[-1] < ema21[-1] and ema9[-2] >= ema21[-2]:
                    signals.append({
                        "ticker": f"NFO:{symbol}",
                        "direction": "SHORT",
                        "entry": round(last, 1),
                        "sl": round(last + 1.5 * atr, 1),
                        "target": round(last - 3.0 * atr, 1),
                        "rrr": 2.0,
                        "pattern": f"{symbol} FUT EMA cross + ADX {adx[-1]:.0f}",
                        "confidence": 70,
                    })

            # ── Volume Breakout (2x avg + new 20d high) ──
            avg_vol = float(np.mean(volume[-20:-1])) if len(volume) > 20 else 1
            if avg_vol > 0 and volume[-1] > 2 * avg_vol:
                prev_high = float(np.max(high[-20:-1]))
                if last > prev_high:
                    signals.append({
                        "ticker": f"NFO:{symbol}",
                        "direction": "LONG",
                        "entry": round(last, 1),
                        "sl": round(last - 1.5 * atr, 1),
                        "target": round(last + 3.0 * atr, 1),
                        "rrr": 2.0,
                        "pattern": f"{symbol} FUT volume breakout ({volume[-1]/avg_vol:.1f}x avg)",
                        "confidence": 72,
                    })

        logger.info("[%s] scanned %d futures → %d candidates", self.name, len(all_tickers), len(signals))
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
    def _adx(high, low, close, period=14):
        """Simplified ADX calculation."""
        n = len(close)
        if n < period + 1:
            return np.array([0.0])
        tr = np.maximum(high[1:] - low[1:], np.abs(high[1:] - close[:-1]))
        tr = np.maximum(tr, np.abs(low[1:] - close[:-1]))
        plus_dm = np.where((high[1:] - high[:-1]) > (low[:-1] - low[1:]),
                           np.maximum(high[1:] - high[:-1], 0), 0)
        minus_dm = np.where((low[:-1] - low[1:]) > (high[1:] - high[:-1]),
                            np.maximum(low[:-1] - low[1:], 0), 0)
        atr = np.convolve(tr, np.ones(period)/period, mode='valid')
        plus_di = np.convolve(plus_dm, np.ones(period)/period, mode='valid') / np.where(atr > 0, atr, 1) * 100
        minus_di = np.convolve(minus_dm, np.ones(period)/period, mode='valid') / np.where(atr > 0, atr, 1) * 100
        dx = np.abs(plus_di - minus_di) / np.where((plus_di + minus_di) > 0, plus_di + minus_di, 1) * 100
        if len(dx) >= period:
            adx = np.convolve(dx, np.ones(period)/period, mode='valid')
            return adx
        return dx

    def format_card(self, sig: dict) -> str:
        sep = "\u2501" * 24
        return "\n".join([
            f"{self.card_emoji} {self.card_title}",
            sep,
            f"Future: {sig.get('ticker', '?')}",
            f"Direction: {sig.get('direction', '?')}",
            sep,
            f"Entry: \u20b9{sig.get('entry', 0):.1f} | SL: \u20b9{sig.get('sl', 0):.1f} | TGT: \u20b9{sig.get('target', 0):.1f}",
            f"RRR: {sig.get('rrr', 0):.1f}",
            sep,
            f"Pattern: {sig.get('pattern', '?')}",
        ])
