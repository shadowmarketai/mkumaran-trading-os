"""
Base Agent — shared interface for all segment agents.

Every agent implements:
  - scan()       → run analysis, return signal candidates
  - validate()   → AI confidence check on candidates
  - deliver()    → persist to DB, send Telegram, sync Sheets
  - learn()      → process SL/TGT hits, update internal state
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import date, time
from typing import Any

from mcp_server.market_calendar import is_market_open, now_ist

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract base for all trading segment agents."""

    name: str = "base"
    segment: str = "NSE"  # Exchange segment code
    scan_interval: int = 300  # Seconds between scans
    market_open_time: time = time(9, 15)
    market_close_time: time = time(15, 30)
    max_signals_per_cycle: int = 3
    max_signals_per_day: int = 10
    min_confidence: int = 70
    card_emoji: str = "\U0001f4ca"
    card_title: str = "Signal"

    def __init__(self):
        self._signals_today: int = 0
        self._last_date: str = ""
        self._sent_keys: set[str] = set()  # dedup within day

    def _reset_daily(self) -> None:
        today = str(date.today())
        if today != self._last_date:
            self._signals_today = 0
            self._sent_keys.clear()
            self._last_date = today

    def is_market_open(self) -> bool:
        now = now_ist().time()
        return (
            self.market_open_time <= now <= self.market_close_time
            and is_market_open(self.segment)
        )

    @abstractmethod
    def scan(self) -> list[dict[str, Any]]:
        """Run analysis and return signal candidates."""

    def validate(self, candidates: list[dict]) -> list[dict]:
        """AI confidence check with Bayesian skill-level adjustment.

        For each candidate, reads the skill's historical win rate from
        Bayesian stats and adjusts confidence up/down. Skills with high
        win rates get a boost; skills with poor track records get penalized.
        Then applies min_confidence filter.
        """
        adjusted: list[dict] = []
        for c in candidates:
            conf = c.get("confidence", 0)
            # Bayesian adjustment based on skill's historical performance
            try:
                from mcp_server.scanner_bayesian import compute_confidence_adjustment

                scanner_list = c.get("scanner_list", [])
                if scanner_list:
                    delta = compute_confidence_adjustment(scanner_list)
                    conf += delta
                    c["bayesian_adjustment"] = delta
            except Exception:
                pass
            c["confidence"] = max(0, min(100, conf))
            if c["confidence"] >= self.min_confidence:
                adjusted.append(c)
        return adjusted

    def dedup_key(self, sig: dict) -> str:
        return f"{sig.get('ticker', '')}:{sig.get('direction', '')}:{sig.get('pattern', '')}"

    def format_card(self, sig: dict) -> str:
        """Format signal for Telegram delivery."""
        sep = "\u2501" * 24
        lines = [
            f"{self.card_emoji} {self.card_title}",
            sep,
            f"Ticker: {sig.get('ticker', '?')}",
            f"Segment: {self.name}",
            f"Direction: {sig.get('direction', '?')}",
            sep,
            f"Entry: \u20b9{sig.get('entry', 0):.1f} | SL: \u20b9{sig.get('sl', 0):.1f} | TGT: \u20b9{sig.get('target', 0):.1f}",
            f"RRR: {sig.get('rrr', 0):.1f}",
            sep,
            f"Pattern: {sig.get('pattern', '?')}",
        ]
        if sig.get("confidence"):
            lines.append(f"AI Confidence: {sig['confidence']}%")
        if sig.get("rationale"):
            lines.append(sig["rationale"])
        if sig.get("warning"):
            lines.append(f"\u26a0\ufe0f {sig['warning']}")
        return "\n".join(lines)

    async def deliver(self, signals: list[dict]) -> int:
        """Persist + send to Telegram + broadcast to subscribers."""
        from mcp_server.telegram_bot import send_telegram_message

        self._reset_daily()
        delivered = 0

        for sig in signals[: self.max_signals_per_cycle]:
            if self._signals_today >= self.max_signals_per_day:
                logger.info(
                    "[%s] daily cap reached (%d)", self.name, self.max_signals_per_day
                )
                break

            key = self.dedup_key(sig)
            if key in self._sent_keys:
                continue

            try:
                msg = self.format_card(sig)
                await send_telegram_message(msg, exchange=self.segment, force=True)

                # Broadcast to subscribers
                try:
                    from mcp_server.telegram_saas import broadcast_signal_to_users

                    await broadcast_signal_to_users(msg, exchange=self.segment)
                except Exception:
                    pass

                self._sent_keys.add(key)
                self._signals_today += 1
                delivered += 1
                logger.info(
                    "[%s] delivered: %s %s %s",
                    self.name,
                    sig.get("ticker"),
                    sig.get("direction"),
                    sig.get("pattern"),
                )
            except Exception as e:
                logger.warning("[%s] delivery failed: %s", self.name, e)

        return delivered

    async def run_cycle(self) -> dict[str, Any]:
        """One full scan → validate → deliver cycle."""
        if not self.is_market_open():
            return {"status": "market_closed", "agent": self.name}

        try:
            candidates = self.scan()
            validated = self.validate(candidates)
            delivered = await self.deliver(validated)
            return {
                "status": "ok",
                "agent": self.name,
                "scanned": len(candidates),
                "validated": len(validated),
                "delivered": delivered,
            }
        except Exception as e:
            logger.error("[%s] cycle failed: %s", self.name, e)
            return {"status": "error", "agent": self.name, "error": str(e)}

    async def run_loop(self) -> None:
        """Background loop — runs scan cycles at the configured interval."""
        logger.info("[%s] agent started (interval=%ds)", self.name, self.scan_interval)
        while True:
            try:
                result = await asyncio.to_thread(lambda: None)  # yield to event loop
                result = await self.run_cycle()
                if result.get("delivered"):
                    logger.info("[%s] cycle result: %s", self.name, result)
            except asyncio.CancelledError:
                logger.info("[%s] agent stopped", self.name)
                break
            except Exception as e:
                logger.error("[%s] loop error: %s", self.name, e)
            await asyncio.sleep(self.scan_interval)
