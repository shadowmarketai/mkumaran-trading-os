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
            # Pre-populate sent_keys from DB to survive restarts/deploys.
            # Without this, every deploy re-sends today's signals.
            try:
                from mcp_server.db import SessionLocal
                from mcp_server.models import Signal
                db = SessionLocal()
                try:
                    today_sigs = db.query(Signal).filter(
                        Signal.signal_date == date.today()
                    ).all()
                    for s in today_sigs:
                        key = f"{s.ticker}:{s.direction}:{s.source or ''}"
                        self._sent_keys.add(key)
                    self._signals_today = len(today_sigs)
                finally:
                    db.close()
            except Exception:
                pass

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
        Then applies min_confidence filter and market-event gates.
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

        # Apply market-event gates (earnings blackout + FII directional filter).
        # Gates are fail-open — API errors never silently drop signals.
        try:
            from mcp_server.config import settings
            from mcp_server.signal_gates import apply_signal_gates

            if settings.EARNINGS_GATE_ENABLED or settings.FII_GATE_ENABLED:
                adjusted = apply_signal_gates(
                    adjusted,
                    earnings_gate=settings.EARNINGS_GATE_ENABLED,
                    fii_gate=settings.FII_GATE_ENABLED,
                    earnings_days=settings.EARNINGS_GATE_DAYS,
                )
        except Exception as exc:
            logger.warning("[%s] signal gates failed (fail-open): %s", self.name, exc)

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
        """Persist to DB, send to Telegram, and broadcast to subscribers.

        Two gates run before Telegram send:
          1. ScannerBayesian auto-disable — skip skills flagged as
             persistent underperformers. Previously only the MWA/Chartink
             pipeline consulted this list; agent-sourced signals like
             swing_low_bounce kept firing even after being disabled.
          2. Predictor loss-probability gate (inside _persist_signal) —
             persists the signal as SUPPRESSED and returns was_suppressed
             so we skip Telegram.
        """
        from mcp_server.telegram_bot import send_telegram_message

        self._reset_daily()
        delivered = 0

        # Load auto-disable list once per delivery batch. Fail-open (empty
        # set) on any error — a broken Bayesian read must not silence live
        # signals.
        try:
            from mcp_server.scanner_bayesian import get_disabled_scanners
            disabled = get_disabled_scanners()
        except Exception as bayes_err:
            logger.debug("[%s] auto-disable list unavailable: %s", self.name, bayes_err)
            disabled = set()

        for sig in signals[: self.max_signals_per_cycle]:
            if self._signals_today >= self.max_signals_per_day:
                logger.info(
                    "[%s] daily cap reached (%d)", self.name, self.max_signals_per_day
                )
                break

            key = self.dedup_key(sig)
            if key in self._sent_keys:
                continue

            # Gate 1: Bayesian auto-disable
            scanner_key = sig.get("skill_name") or sig.get("pattern")
            if scanner_key and scanner_key in disabled:
                logger.info(
                    "[%s] SKIPPED (auto-disabled by Bayesian stats): %s %s",
                    self.name, scanner_key, sig.get("ticker"),
                )
                continue

            try:
                # ── Persist to DB first so this signal is tracked by
                # signal_monitor (SL/TGT auto-close) and shows up in
                # EOD/self-dev reporting, matching every other signal
                # source in the system. Previously this method only sent
                # a Telegram message despite its docstring claiming it
                # persisted — agent-sourced signals were untracked.
                db_signal_id, was_suppressed = self._persist_signal(sig)

                # Gate 2: predictor gate. When _persist_signal reports the
                # predictor blocked this signal, we still keep the DB row
                # (as SUPPRESSED, for self-dev learning) but skip Telegram
                # so we don't advertise a trade we won't take.
                if was_suppressed:
                    continue

                from mcp_server.config import settings
                disclaimer = "" if sig.get("validated") else getattr(settings, "UNVALIDATED_SIGNAL_DISCLAIMER", "")
                msg = disclaimer + self.format_card(sig)
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
                    "[%s] delivered: %s %s %s (signal_id=%s)",
                    self.name,
                    sig.get("ticker"),
                    sig.get("direction"),
                    sig.get("pattern"),
                    db_signal_id,
                )
            except Exception as e:
                logger.warning("[%s] delivery failed: %s", self.name, e)

        return delivered

    def _persist_signal(self, sig: dict) -> tuple[int | None, bool]:
        """Write a Signal row to the DB for this agent-generated candidate.

        Runs the self-development predictor gate (mirrors mcp_server.py's
        MWA path at line 2544-2587) so agent signals are gated against
        historical loss probability just like MWA-sourced ones.

        Returns (signal_id, suppressed):
          - signal_id is None on DB failure — delivery still proceeds so a
            DB hiccup doesn't silence Telegram alerts.
          - suppressed=True means the predictor blocked it and the caller
            must NOT send the Telegram card or add to ActiveTrade.
        """
        from datetime import date as _date

        from mcp_server.config import settings
        from mcp_server.db import SessionLocal
        from mcp_server.models import Signal

        db = SessionLocal()
        was_suppressed = False
        try:
            entry = sig.get("entry", 0)
            sl = sig.get("sl", 0)
            target = sig.get("target", 0)
            scanner_key = sig.get("pattern") or sig.get("skill_name") or self.name

            db_signal = Signal(
                signal_date=_date.today(),
                ticker=sig.get("ticker", ""),
                exchange=self.segment,
                asset_class="EQUITY",
                direction=sig.get("direction", "LONG"),
                pattern=sig.get("pattern", sig.get("skill_name", self.name)),
                entry_price=entry,
                stop_loss=sl,
                target=target,
                rrr=sig.get("rrr"),
                ai_confidence=sig.get("confidence"),
                scanner_count=1,
                tier=sig.get("tier"),
                source=self.name,
                timeframe="1D",
                status="OPEN",
                scanner_list=[scanner_key],
            )

            # ── Self-development: entry-context features ──
            # Same shape as mcp_server.py:2544. Uses whatever OHLCV the
            # skill attached (via SkillRegistry.scan_all); on missing df
            # the extractor falls back to neutral defaults.
            try:
                from mcp_server.signal_features import (
                    apply_features_to_signal,
                    extract_entry_features,
                )
                feat = extract_entry_features(
                    sig.get("_ohlcv_df"),
                    scanner_count=1,
                    scanner_list=[scanner_key],
                    ai_confidence=int(sig.get("confidence") or 0),
                    rrr=float(sig.get("rrr") or 0),
                    direction=sig.get("direction", "LONG"),
                    exchange=self.segment,
                )
                apply_features_to_signal(db_signal, feat)
            except Exception as feat_err:
                logger.debug("[%s] feature extraction skipped: %s", self.name, feat_err)

            # ── Self-development: predictive loss probability gate ──
            try:
                from mcp_server.signal_predictor import get_predictor
                predictor = get_predictor()
                if predictor.is_ready():
                    loss_prob, top_features = predictor.predict(
                        db_signal.feature_vector or [],
                    )
                    db_signal.loss_probability = round(loss_prob, 3)
                    db_signal.predictor_version = predictor.version
                    threshold = getattr(settings, "PREDICTOR_BLOCK_THRESHOLD", 0.75)
                    if loss_prob >= threshold:
                        db_signal.suppressed = True
                        db_signal.status = "SUPPRESSED"
                        db_signal.suppression_reason = (
                            f"Predictor: P(loss)={loss_prob:.2f} ≥ {threshold:.2f}. "
                            f"Top risk factors: {', '.join(top_features[:3])}"
                        )
                        was_suppressed = True
                        logger.info(
                            "[%s] Signal SUPPRESSED %s: P(loss)=%.2f reason=%s",
                            self.name, sig.get("ticker"),
                            loss_prob, db_signal.suppression_reason,
                        )
            except Exception as pred_err:
                logger.debug("[%s] predictor skipped: %s", self.name, pred_err)

            db.add(db_signal)
            db.commit()
            db.refresh(db_signal)
            return db_signal.id, was_suppressed
        except Exception as e:
            logger.warning("[%s] Signal persistence failed for %s: %s", self.name, sig.get("ticker"), e)
            db.rollback()
            return None, False
        finally:
            db.close()

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
