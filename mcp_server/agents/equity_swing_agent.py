"""
Equity Swing Agent — NSE Nifty 500 daily swing signals.

Runs two TIER_2 validated skills on daily bars:
  - breakout_200dma: close crosses above 200-day SMA (WR=44%, Sharpe=0.94)
  - swing_low_bounce: close near 20d low + green candle (WR=43%, Sharpe=1.33)

Scans Nifty 500 universe in batches every 30 minutes during market hours.
Capped at 3 signals per cycle and 8 per day to avoid alert fatigue.
"""

from __future__ import annotations

import logging
from datetime import time
from pathlib import Path
from typing import Any

import pandas as pd

from mcp_server.agents.base_agent import BaseAgent
from mcp_server.agents.skills import SkillRegistry

logger = logging.getLogger(__name__)

_NIFTY500_PATH = Path("data/nifty500.json")

# Liquid subset scanned every cycle — rotate through full 500 weekly
_LIQUID_100 = [
    "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "BHARTIARTL",
    "SBIN", "KOTAKBANK", "LT", "AXISBANK", "WIPRO", "HCLTECH",
    "MARUTI", "SUNPHARMA", "TITAN", "BAJFINANCE", "BAJAJFINSV", "ULTRACEMCO",
    "NTPC", "POWERGRID", "ONGC", "BPCL", "COALINDIA", "GRASIM",
    "JSWSTEEL", "TATASTEEL", "TATAMOTORS", "TATACONSUM", "NESTLEIND",
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "BRITANNIA",
    "CIPLA", "DRREDDY", "EICHERMOT", "HEROMOTOCO", "HDFCLIFE", "HINDUNILVR",
    "INDUSINDBK", "ITC", "SHRIRAMFIN", "SBILIFE", "TECHM", "TRENT",
    "ZOMATO", "BEL", "DIXONS", "HAVELLS", "SIEMENS", "MOTHERSON",
    "PIIND", "TORNTPHARM", "PERSISTENT", "MPHASIS", "COFORGE",
    "VOLTAS", "CUMMINSIND", "AAVAS", "ABCAPITAL", "ALKEM",
    "BANKBARODA", "CANBK", "PNB", "UNIONBANK", "IDFCFIRSTB",
    "LTIM", "OFSS", "KPIT", "LTTS", "HEXAWARE",
    "DMART", "ZYDUSLIFE", "LUPIN", "BIOCON", "GLENMARK",
    "APLAPOLLO", "HINDALCO", "VEDL", "NMDC", "SAIL",
    "CONCOR", "IRCTC", "RECLTD", "PFC", "IOC",
    "PIDILITIND", "BERGEPAINT", "KANSAINER", "ASTRAL", "SUPREMEIND",
    "BAJAJHLDNG", "GODREJCP", "MARICO", "DABUR", "COLPAL",
    "APOLLOTYRE", "MRF", "EXIDEIND", "BALKRISIND", "CEATLTD",
    "MUTHOOTFIN", "CHOLAFIN", "M&MFIN", "SUNDARMFIN", "LICHSGFIN",
]


def _load_nifty500() -> list[str]:
    try:
        import json
        data = json.loads(_NIFTY500_PATH.read_text())
        return data.get("symbols", [])
    except Exception:
        return _LIQUID_100


class EquitySwingAgent(BaseAgent):
    """
    Swing signal agent for NSE equities — daily bars, Nifty 500 universe.
    Skills: breakout_200dma (TIER_2) + swing_low_bounce (TIER_2).
    """

    name = "Equity Swing (NSE)"
    segment = "NSE"
    scan_interval = 1800          # 30 min — daily signals don't need faster
    market_open_time = time(9, 30)
    market_close_time = time(15, 15)
    max_signals_per_cycle = 3
    max_signals_per_day = 8
    min_confidence = 0            # skills set validated=True; base_agent handles disclaimer
    card_emoji = "\U0001f4c8"
    card_title = "EQUITY SWING Signal"

    def __init__(self):
        super().__init__()
        self.registry = SkillRegistry("equity_swing")
        self.registry.discover()
        self._universe = _load_nifty500() or _LIQUID_100
        self._batch_idx = 0         # rotate through universe each cycle
        self._batch_size = 50       # scan 50 stocks per cycle

    def _fetch(self, symbol: str) -> pd.DataFrame | None:
        try:
            from mcp_server.data_provider import get_provider
            df = get_provider().get_ohlcv_routed(
                symbol, interval="day", days=260, exchange="NSE"
            )
            if df is not None and not df.empty:
                df.columns = [c.lower() for c in df.columns]
                return df
        except Exception:
            pass
        return None

    def scan(self) -> list[dict[str, Any]]:
        if not self.registry.skills:
            logger.warning("[%s] no skills loaded", self.name)
            return []

        # Rotate through universe in batches — full 500 covered every ~5h
        n = len(self._universe)
        start = (self._batch_idx * self._batch_size) % n
        batch = self._universe[start: start + self._batch_size]
        # Wrap around if batch extends past end
        if start + self._batch_size > n:
            batch += self._universe[: (start + self._batch_size) - n]
        self._batch_idx += 1

        signals: list[dict[str, Any]] = []
        fetched = 0

        for symbol in batch:
            df = self._fetch(symbol)
            if df is None or len(df) < 210:
                continue
            fetched += 1
            hits = self.registry.scan_all(df, symbol, context={})
            signals.extend(hits)

        logger.info(
            "[%s] batch %d/%d — %d stocks fetched → %d signals (%d skills)",
            self.name,
            self._batch_idx,
            (n + self._batch_size - 1) // self._batch_size,
            fetched,
            len(signals),
            len(self.registry.skills),
        )
        return signals

    def format_card(self, sig: dict) -> str:
        sep = "━" * 24
        entry = sig.get("entry", 0)
        sl    = sig.get("sl", 0)
        tgt   = sig.get("target", 0)
        rrr   = sig.get("rrr", 0)
        risk_pct = abs(entry - sl) / entry * 100 if entry > 0 else 0
        return "\n".join([
            f"{self.card_emoji} {self.card_title}",
            sep,
            f"Ticker: {sig.get('ticker', '?')} | Direction: {sig.get('direction', '?')}",
            sep,
            f"Entry: ₹{entry:.2f} | SL: ₹{sl:.2f} | TGT: ₹{tgt:.2f}",
            f"RRR: {rrr:.1f} | Risk: {risk_pct:.1f}% | Skill: {sig.get('skill_name', '?')}",
            sep,
            f"Pattern: {sig.get('pattern', '?')}",
        ])
