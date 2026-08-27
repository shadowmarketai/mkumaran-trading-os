"""Tests for the predictor gate + Bayesian auto-disable on the agent path.

Regression for two bugs on the same code path in BaseAgent:
  1. Agent-generated Signal rows had loss_probability=NULL because the
     predictor block was never ported from mcp_server.py's MWA path.
  2. The Bayesian auto-disable list was never consulted, so scanners
     flagged as underperformers (e.g. swing_low_bounce) kept firing.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

from mcp_server.agents.base_agent import BaseAgent
from mcp_server.db import SessionLocal
from mcp_server.models import Signal


class _FixtureAgent(BaseAgent):
    """Concrete agent for tests — bypasses market-open gate and Telegram."""

    name = "test_agent"
    segment = "NSE"
    min_confidence = 0
    max_signals_per_cycle = 5
    max_signals_per_day = 10

    def is_market_open(self) -> bool:
        return True

    def scan(self):
        return []


class _FakePredictor:
    """Stand-in for SignalPredictor with configurable P(loss)."""

    def __init__(self, ready: bool = True, loss_prob: float = 0.9):
        self._ready = ready
        self._loss_prob = loss_prob
        self.version = "test-v1"

    def is_ready(self) -> bool:
        return self._ready

    def predict(self, feature_vector):
        return self._loss_prob, ["feat_a", "feat_b", "feat_c"]


def _sig() -> dict[str, Any]:
    return {
        "ticker": "TESTX",
        "direction": "LONG",
        "entry": 100.0,
        "sl": 95.0,
        "target": 110.0,
        "rrr": 2.0,
        "confidence": 70,
        "pattern": "swing_low_bounce_20d",
        "skill_name": "swing_low_bounce",
        "validated": True,
    }


class TestPredictorGate:
    def test_high_loss_prob_marks_status_suppressed(self, db_session):
        agent = _FixtureAgent()
        fake_pred = _FakePredictor(ready=True, loss_prob=0.9)  # ≥ 0.75 default

        with patch(
            "mcp_server.signal_predictor.get_predictor", return_value=fake_pred,
        ):
            sid, was_suppressed = agent._persist_signal(_sig())

        assert sid is not None
        assert was_suppressed is True

        s = SessionLocal()
        try:
            row = s.query(Signal).filter(Signal.id == sid).one()
            assert row.status == "SUPPRESSED"
            assert row.suppressed is True
            assert row.loss_probability is not None
            assert float(row.loss_probability) == 0.9
            assert row.predictor_version == "test-v1"
            assert "P(loss)=0.90" in (row.suppression_reason or "")
        finally:
            s.close()

    def test_low_loss_prob_stays_open_but_records_probability(self, db_session):
        agent = _FixtureAgent()
        fake_pred = _FakePredictor(ready=True, loss_prob=0.2)  # < 0.75

        with patch(
            "mcp_server.signal_predictor.get_predictor", return_value=fake_pred,
        ):
            sid, was_suppressed = agent._persist_signal(_sig())

        assert sid is not None
        assert was_suppressed is False

        s = SessionLocal()
        try:
            row = s.query(Signal).filter(Signal.id == sid).one()
            assert row.status == "OPEN"
            assert row.suppressed is False
            assert row.loss_probability is not None
            assert float(row.loss_probability) == 0.2
        finally:
            s.close()

    def test_predictor_not_ready_leaves_probability_null(self, db_session):
        # A cold-start deploy with no trained predictor must not crash and
        # must not silently pretend it gated the signal.
        agent = _FixtureAgent()
        fake_pred = _FakePredictor(ready=False)

        with patch(
            "mcp_server.signal_predictor.get_predictor", return_value=fake_pred,
        ):
            sid, was_suppressed = agent._persist_signal(_sig())

        assert sid is not None
        assert was_suppressed is False

        s = SessionLocal()
        try:
            row = s.query(Signal).filter(Signal.id == sid).one()
            assert row.status == "OPEN"
            assert row.loss_probability is None
            assert row.predictor_version is None
        finally:
            s.close()


class TestBayesianAutoDisable:
    def test_disabled_skill_skips_delivery_and_persistence(self, db_session):
        agent = _FixtureAgent()
        # Sneak a persist counter into _persist_signal to verify it wasn't reached.
        calls: list[dict] = []

        def _spy_persist(sig):
            calls.append(sig)
            return (1, False)

        agent._persist_signal = _spy_persist  # type: ignore[method-assign]

        with patch(
            "mcp_server.scanner_bayesian.get_disabled_scanners",
            return_value={"swing_low_bounce"},
        ):
            delivered = asyncio.run(agent.deliver([_sig()]))

        assert delivered == 0
        assert calls == [], "disabled skill must not reach persistence"

    def test_enabled_skill_reaches_persistence(self, db_session):
        agent = _FixtureAgent()
        calls: list[dict] = []

        def _spy_persist(sig):
            calls.append(sig)
            return (1, False)

        agent._persist_signal = _spy_persist  # type: ignore[method-assign]

        # Also stub Telegram + broadcast so the test doesn't hit the network.
        async def _noop(*a, **k): return None
        with patch(
            "mcp_server.scanner_bayesian.get_disabled_scanners",
            return_value=set(),
        ), patch(
            "mcp_server.telegram_bot.send_telegram_message", _noop,
        ), patch(
            "mcp_server.telegram_saas.broadcast_signal_to_users", _noop,
        ):
            delivered = asyncio.run(agent.deliver([_sig()]))

        assert delivered == 1
        assert len(calls) == 1
        assert calls[0]["skill_name"] == "swing_low_bounce"

    def test_suppressed_signal_still_persists_but_skips_telegram(self, db_session):
        agent = _FixtureAgent()
        sent: list[str] = []

        # _persist_signal reports suppression → deliver must skip Telegram.
        def _persist_returns_suppressed(sig):
            return (42, True)

        agent._persist_signal = _persist_returns_suppressed  # type: ignore[method-assign]

        async def _capture(*a, **k):
            sent.append("sent")

        with patch(
            "mcp_server.scanner_bayesian.get_disabled_scanners", return_value=set(),
        ), patch(
            "mcp_server.telegram_bot.send_telegram_message", _capture,
        ):
            delivered = asyncio.run(agent.deliver([_sig()]))

        assert delivered == 0
        assert sent == [], "suppressed signals must not send Telegram"
