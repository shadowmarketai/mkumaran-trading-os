"""Tests for validate_with_debate — debate routing and fallback chain."""

import pytest
from unittest.mock import patch, MagicMock

from mcp_server.validator import validate_with_debate, validate_signal


# ── Shared signal params ─────────────────────────────────────

SIGNAL_PARAMS = dict(
    ticker="NSE:RELIANCE",
    direction="LONG",
    pattern="breakout_volume",
    rrr=3.5,
    entry_price=2500,
    stop_loss=2400,
    target=2850,
    mwa_direction="BULL",
    scanner_count=5,
    tv_confirmed=True,
    sector_strength="STRONG",
    fii_net=1200,
    delivery_pct=45.0,
    confidence_boosts=["mwa_aligned", "tv_confirmed"],
    pre_confidence=55,
    exchange="NSE",
)


# ── Debate Routing Tests ─────────────────────────────────────

class TestDebateRouting:
    @patch("mcp_server.validator.settings")
    @patch("mcp_server.debate_validator.run_debate")
    @patch("mcp_server.trade_memory.TradeMemory")
    def test_uncertain_signal_routes_to_debate(self, mock_mem_cls, mock_debate, mock_settings):
        """Signals 40-75 pre_confidence should route to debate."""
        mock_settings.DEBATE_ENABLED = True
        mock_settings.ANTHROPIC_API_KEY = "sk-test-key-valid-for-testing"
        mock_settings.TRADE_MEMORY_FILE = "data/trade_memory.json"
        mock_settings.MEMORY_TOP_K = 3
        mock_settings.DEBATE_UNCERTAIN_LOW = 40
        mock_settings.DEBATE_UNCERTAIN_HIGH = 75

        # Mock memory
        mock_mem = MagicMock()
        mock_mem.find_similar_for_signal.return_value = []
        mock_mem_cls.return_value = mock_mem

        # Mock debate result
        mock_result = MagicMock()
        mock_result.final_confidence = 72
        mock_result.recommendation = "ALERT"
        mock_result.reasoning = "Strong setup"
        mock_result.validation_status = "VALIDATED"
        mock_result.boosts = ["mwa_aligned"]
        mock_result.method = "debate"
        mock_result.api_calls_used = 6
        mock_result.similar_trades = []
        mock_result.risk_assessment = "Low risk"
        mock_result.debate_transcript = []
        mock_debate.return_value = mock_result

        result = validate_with_debate(**SIGNAL_PARAMS)

        assert result["method"] == "debate"
        assert result["confidence"] == 72
        assert result["recommendation"] == "ALERT"
        mock_debate.assert_called_once()

    @patch("mcp_server.validator.settings")
    def test_high_confidence_skips_debate(self, mock_settings):
        """Signals >75 pre_confidence should skip debate (single-pass)."""
        mock_settings.DEBATE_ENABLED = True
        mock_settings.ANTHROPIC_API_KEY = ""  # No API key = BLOCKED
        mock_settings.TRADE_MEMORY_FILE = "data/trade_memory.json"
        mock_settings.MEMORY_TOP_K = 3
        mock_settings.DEBATE_UNCERTAIN_LOW = 40
        mock_settings.DEBATE_UNCERTAIN_HIGH = 75

        params = {**SIGNAL_PARAMS, "pre_confidence": 80}
        result = validate_with_debate(**params)

        # Should fall through to single-pass (which blocks without API key)
        assert result["validation_status"] in ("SKIPPED", "FAILED", "BLOCKED")

    @patch("mcp_server.validator.settings")
    def test_debate_disabled_uses_single_pass(self, mock_settings):
        """When DEBATE_ENABLED=False, always single-pass."""
        mock_settings.DEBATE_ENABLED = False
        mock_settings.ANTHROPIC_API_KEY = ""
        mock_settings.TRADE_MEMORY_FILE = "data/trade_memory.json"
        mock_settings.MEMORY_TOP_K = 3

        result = validate_with_debate(**SIGNAL_PARAMS)
        assert result["method"] == "single_pass"


# ── Fallback Chain Tests ─────────────────────────────────────

class TestFallbackChain:
    @patch("mcp_server.validator.settings")
    def test_debate_failure_falls_back_to_single_pass(self, mock_settings):
        """If debate import/call fails, falls back to single-pass."""
        mock_settings.DEBATE_ENABLED = True
        mock_settings.ANTHROPIC_API_KEY = ""
        mock_settings.TRADE_MEMORY_FILE = "data/trade_memory.json"
        mock_settings.MEMORY_TOP_K = 3
        mock_settings.DEBATE_UNCERTAIN_LOW = 40
        mock_settings.DEBATE_UNCERTAIN_HIGH = 75

        with patch("mcp_server.debate_validator.run_debate", side_effect=Exception("API down")):
            result = validate_with_debate(**SIGNAL_PARAMS)

        # Should fall through to single-pass
        assert result["method"] == "single_pass"

    @patch("mcp_server.validator.settings")
    def test_memory_failure_is_nonfatal(self, mock_settings):
        """Trade memory failure should not block validation."""
        mock_settings.DEBATE_ENABLED = False
        mock_settings.ANTHROPIC_API_KEY = ""
        mock_settings.TRADE_MEMORY_FILE = "/nonexistent/path.json"
        mock_settings.MEMORY_TOP_K = 3

        # Should not raise
        result = validate_with_debate(**SIGNAL_PARAMS)
        assert "confidence" in result


# ── Memory Integration Tests ─────────────────────────────────

class TestMemoryIntegration:
    @patch("mcp_server.validator.settings")
    def test_similar_trades_included_in_result(self, mock_settings):
        """Similar trades from BM25 should be passed through to result."""
        mock_settings.DEBATE_ENABLED = False
        mock_settings.ANTHROPIC_API_KEY = ""
        mock_settings.TRADE_MEMORY_FILE = "data/trade_memory.json"
        mock_settings.MEMORY_TOP_K = 3

        with patch("mcp_server.trade_memory.TradeMemory") as mock_cls:
            mock_mem = MagicMock()
            mock_mem.find_similar_for_signal.return_value = [
                {"ticker": "NSE:RELIANCE", "outcome": "WIN", "similarity": 0.85}
            ]
            mock_cls.return_value = mock_mem

            result = validate_with_debate(**SIGNAL_PARAMS)
            assert "similar_trades" in result
