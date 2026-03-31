"""Tests for Debate Validator — debate_validator.py"""

import json
from unittest.mock import patch, MagicMock


from mcp_server.debate_validator import (
    should_debate,
    _build_signal_context,
    _build_memory_context,
    DebateMessage,
    DebateResult,
    run_debate,
    _call_bull_analyst,
    _call_bear_analyst,
    _call_judge,
    _call_risk_assessment,
)


# ── Common fixtures ─────────────────────────────────────────────


SIGNAL_KWARGS = {
    "ticker": "NSE:RELIANCE",
    "direction": "LONG",
    "pattern": "RRMS",
    "rrr": 3.5,
    "entry_price": 2500.0,
    "stop_loss": 2450.0,
    "target": 2675.0,
    "mwa_direction": "BULL",
    "scanner_count": 5,
    "tv_confirmed": True,
    "sector_strength": "STRONG",
    "fii_net": 1200.0,
    "delivery_pct": 45.0,
    "confidence_boosts": ["TV Signal (+5%)", "MWA BULL (+10%)"],
    "pre_confidence": 60,
}


def _mock_claude_response(content: dict):
    """Create a mock Anthropic response object."""
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text=json.dumps(content))]
    return mock_resp


# ── Triage logic ─────────────────────────────────────────────────


def test_should_debate_uncertain_zone():
    """Signals with pre_confidence 40-75 should trigger debate."""
    assert should_debate(40) is True
    assert should_debate(55) is True
    assert should_debate(75) is True


def test_should_debate_clear_high():
    """High confidence signals skip debate."""
    assert should_debate(76) is False
    assert should_debate(90) is False


def test_should_debate_clear_low():
    """Low confidence signals skip debate."""
    assert should_debate(39) is False
    assert should_debate(10) is False


def test_should_debate_custom_thresholds():
    """Triage respects custom threshold settings."""
    with patch("mcp_server.debate_validator.settings") as mock_settings:
        mock_settings.DEBATE_UNCERTAIN_LOW = 30
        mock_settings.DEBATE_UNCERTAIN_HIGH = 80
        assert should_debate(30) is True
        assert should_debate(80) is True
        assert should_debate(29) is False
        assert should_debate(81) is False


# ── Context builders ─────────────────────────────────────────────


def test_build_signal_context():
    ctx = _build_signal_context(**SIGNAL_KWARGS)
    assert "NSE:RELIANCE" in ctx
    assert "LONG" in ctx
    assert "RRMS" in ctx
    assert "RRR: 3.50" in ctx
    assert "PASS" in ctx  # RRR 3.5 >= 3.0 for equity
    assert "Equity" in ctx


def test_build_signal_context_leveraged():
    kwargs = {**SIGNAL_KWARGS, "ticker": "MCX:GOLD", "rrr": 2.5}
    ctx = _build_signal_context(**kwargs)
    assert "Leveraged" in ctx
    assert "PASS" in ctx  # RRR 2.5 >= 2.0 for leveraged


def test_build_signal_context_rrr_fail():
    kwargs = {**SIGNAL_KWARGS, "rrr": 1.5}
    ctx = _build_signal_context(**kwargs)
    assert "FAIL" in ctx


def test_build_memory_context_empty():
    result = _build_memory_context([])
    assert "No similar past trades" in result


def test_build_memory_context_with_trades():
    trades = [
        {"ticker": "NSE:RELIANCE", "direction": "BUY", "rrr": 3.0,
         "confidence": 70, "outcome": "WIN", "pnl_pct": 5.2, "lesson": "Good setup"},
        {"ticker": "NSE:TCS", "direction": "BUY", "rrr": 2.5,
         "confidence": 55, "outcome": "LOSS", "pnl_pct": -2.1, "lesson": ""},
    ]
    result = _build_memory_context(trades)
    assert "SIMILAR PAST TRADES" in result
    assert "NSE:RELIANCE" in result
    assert "Good setup" in result
    assert "NSE:TCS" in result


# ── Agent calls (mocked) ────────────────────────────────────────


def test_call_bull_analyst():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_claude_response(
        {"confidence": 78, "argument": "Strong MWA alignment with breakout pattern."}
    )

    result = _call_bull_analyst(mock_client, "signal ctx", "memory ctx")
    assert result.role == "bull"
    assert result.round_num == 1
    assert result.confidence == 78
    assert "Strong MWA" in result.argument


def test_call_bull_analyst_rebuttal():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_claude_response(
        {"confidence": 82, "argument": "Bear concerns are valid but manageable."}
    )

    result = _call_bull_analyst(mock_client, "ctx", "mem", bear_argument="Weak volume")
    assert result.round_num == 2


def test_call_bear_analyst():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_claude_response(
        {"confidence": 35, "argument": "Weak delivery percentage suggests distribution."}
    )

    result = _call_bear_analyst(mock_client, "signal ctx", "memory ctx")
    assert result.role == "bear"
    assert result.round_num == 1
    assert result.confidence == 35


def test_call_judge():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_claude_response(
        {"confidence": 68, "reasoning": "Bull arguments stronger but bear has valid risk points.",
         "recommendation": "WATCHLIST"}
    )

    transcript = [
        DebateMessage(role="bull", round_num=1, argument="Strong", confidence=78),
        DebateMessage(role="bear", round_num=1, argument="Weak volume", confidence=35),
    ]
    result = _call_judge(mock_client, "ctx", transcript)
    assert result["confidence"] == 68
    assert result["recommendation"] == "WATCHLIST"


def test_call_risk_assessment():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mock_claude_response(
        {"confidence": 65, "risk_assessment": "Moderate risk. Conservative says no, aggressive says yes.",
         "adjustment": -3}
    )

    result = _call_risk_assessment(mock_client, "ctx", {"confidence": 68, "reasoning": "..."})
    assert result["adjustment"] == -3
    assert "Moderate risk" in result["risk_assessment"]


# ── Full debate flow (mocked) ───────────────────────────────────


@patch("mcp_server.debate_validator.settings")
@patch("mcp_server.debate_validator._call_risk_assessment")
@patch("mcp_server.debate_validator._call_judge")
@patch("mcp_server.debate_validator._call_bear_analyst")
@patch("mcp_server.debate_validator._call_bull_analyst")
def test_run_debate_full_flow(mock_bull, mock_bear, mock_judge, mock_risk, mock_settings):
    """Full debate should use 6 API calls and return DebateResult."""
    mock_settings.DEBATE_ENABLED = True
    mock_settings.DEBATE_UNCERTAIN_LOW = 40
    mock_settings.DEBATE_UNCERTAIN_HIGH = 75
    mock_settings.ANTHROPIC_API_KEY = "sk-test-key-1234567890abcdef"

    mock_bull.return_value = DebateMessage("bull", 1, "Bullish case", 75)
    mock_bear.return_value = DebateMessage("bear", 1, "Bearish case", 40)
    mock_judge.return_value = {"confidence": 68, "reasoning": "Balanced view", "recommendation": "WATCHLIST"}
    mock_risk.return_value = {"confidence": 65, "risk_assessment": "Moderate", "adjustment": -3}

    result = run_debate(**SIGNAL_KWARGS, similar_trades=[])

    assert isinstance(result, DebateResult)
    assert result.method == "debate"
    assert result.final_confidence == 65  # 68 + (-3)
    assert result.recommendation == "WATCHLIST"
    assert result.validation_status == "VALIDATED"
    assert len(result.debate_transcript) == 4  # bull x2, bear x2
    assert mock_bull.call_count == 2  # Round 1 + Round 2
    assert mock_bear.call_count == 2


# ── Single-pass for clear signals ────────────────────────────────


@patch("mcp_server.debate_validator.settings")
@patch("mcp_server.validator.validate_signal")
def test_run_debate_high_confidence_uses_single_pass(mock_validate, mock_settings):
    """Signals with pre_confidence > 75 should use single-pass."""
    mock_settings.DEBATE_ENABLED = True
    mock_settings.DEBATE_UNCERTAIN_LOW = 40
    mock_settings.DEBATE_UNCERTAIN_HIGH = 75

    mock_validate.return_value = {
        "confidence": 82, "recommendation": "ALERT",
        "reasoning": "Strong signal", "validation_status": "VALIDATED",
        "boosts": ["TV Signal (+5%)"],
    }

    kwargs = {**SIGNAL_KWARGS, "pre_confidence": 80}
    result = run_debate(**kwargs)

    assert result.method == "single_pass"
    assert result.final_confidence == 82
    mock_validate.assert_called_once()


@patch("mcp_server.debate_validator.settings")
@patch("mcp_server.validator.validate_signal")
def test_run_debate_low_confidence_uses_single_pass(mock_validate, mock_settings):
    """Signals with pre_confidence < 40 should use single-pass."""
    mock_settings.DEBATE_ENABLED = True
    mock_settings.DEBATE_UNCERTAIN_LOW = 40
    mock_settings.DEBATE_UNCERTAIN_HIGH = 75

    mock_validate.return_value = {
        "confidence": 25, "recommendation": "SKIP",
        "reasoning": "Weak signal", "validation_status": "VALIDATED",
        "boosts": [],
    }

    kwargs = {**SIGNAL_KWARGS, "pre_confidence": 30}
    result = run_debate(**kwargs)
    assert result.method == "single_pass"


# ── Debate disabled ──────────────────────────────────────────────


@patch("mcp_server.debate_validator.settings")
@patch("mcp_server.validator.validate_signal")
def test_run_debate_disabled(mock_validate, mock_settings):
    """When DEBATE_ENABLED=false, always use single-pass."""
    mock_settings.DEBATE_ENABLED = False

    mock_validate.return_value = {
        "confidence": 60, "recommendation": "WATCHLIST",
        "reasoning": "OK", "validation_status": "VALIDATED",
        "boosts": [],
    }

    result = run_debate(**SIGNAL_KWARGS)
    assert result.method == "single_pass"


# ── Fallback chain ───────────────────────────────────────────────


@patch("mcp_server.debate_validator.settings")
@patch("mcp_server.validator.validate_signal")
@patch("mcp_server.debate_validator._run_full_debate", side_effect=Exception("API timeout"))
def test_debate_failure_falls_back_to_single_pass(mock_full, mock_validate, mock_settings):
    """If debate fails, falls back to single-pass."""
    mock_settings.DEBATE_ENABLED = True
    mock_settings.DEBATE_UNCERTAIN_LOW = 40
    mock_settings.DEBATE_UNCERTAIN_HIGH = 75

    mock_validate.return_value = {
        "confidence": 55, "recommendation": "WATCHLIST",
        "reasoning": "Fallback", "validation_status": "VALIDATED",
        "boosts": [],
    }

    result = run_debate(**SIGNAL_KWARGS)
    assert result.method == "single_pass"
    assert result.final_confidence == 55


@patch("mcp_server.debate_validator.settings")
@patch("mcp_server.debate_validator._run_single_pass", side_effect=Exception("Total failure"))
@patch("mcp_server.debate_validator._run_full_debate", side_effect=Exception("Debate failed"))
def test_total_failure_blocks(mock_full, mock_single, mock_settings):
    """If both debate and single-pass fail, signal is BLOCKED."""
    mock_settings.DEBATE_ENABLED = True
    mock_settings.DEBATE_UNCERTAIN_LOW = 40
    mock_settings.DEBATE_UNCERTAIN_HIGH = 75

    result = run_debate(**SIGNAL_KWARGS)
    assert result.recommendation == "BLOCKED"
    assert result.final_confidence == 0
    assert result.validation_status == "FAILED"
    assert "Both debate and single-pass" in result.reasoning


# ── Result structure ─────────────────────────────────────────────


def test_debate_result_defaults():
    r = DebateResult(final_confidence=70, recommendation="ALERT", reasoning="Good")
    assert r.method == "single_pass"
    assert r.api_calls_used == 0
    assert r.similar_trades == []
    assert r.debate_transcript == []


def test_debate_message_structure():
    m = DebateMessage(role="bull", round_num=1, argument="Strong case", confidence=80)
    assert m.role == "bull"
    assert m.round_num == 1


# ── Risk adjustment bounds ───────────────────────────────────────


@patch("mcp_server.debate_validator.settings")
@patch("mcp_server.debate_validator._call_risk_assessment")
@patch("mcp_server.debate_validator._call_judge")
@patch("mcp_server.debate_validator._call_bear_analyst")
@patch("mcp_server.debate_validator._call_bull_analyst")
def test_risk_adjustment_clamped(mock_bull, mock_bear, mock_judge, mock_risk, mock_settings):
    """Risk adjustment is clamped to [-15, +10]."""
    mock_settings.DEBATE_ENABLED = True
    mock_settings.DEBATE_UNCERTAIN_LOW = 40
    mock_settings.DEBATE_UNCERTAIN_HIGH = 75
    mock_settings.ANTHROPIC_API_KEY = "sk-test-key-1234567890abcdef"

    mock_bull.return_value = DebateMessage("bull", 1, "Bull", 80)
    mock_bear.return_value = DebateMessage("bear", 1, "Bear", 30)
    mock_judge.return_value = {"confidence": 60, "reasoning": "OK", "recommendation": "WATCHLIST"}
    mock_risk.return_value = {"confidence": 40, "risk_assessment": "Very risky", "adjustment": -50}

    result = run_debate(**SIGNAL_KWARGS)
    # -50 should be clamped to -15, so 60 + (-15) = 45
    assert result.final_confidence == 45


# ── API call counting ────────────────────────────────────────────


@patch("mcp_server.debate_validator.settings")
@patch("mcp_server.validator.validate_signal")
def test_single_pass_api_call_count(mock_validate, mock_settings):
    """Single-pass should report 1 API call."""
    mock_settings.DEBATE_ENABLED = True
    mock_settings.DEBATE_UNCERTAIN_LOW = 40
    mock_settings.DEBATE_UNCERTAIN_HIGH = 75

    mock_validate.return_value = {
        "confidence": 82, "recommendation": "ALERT",
        "reasoning": "OK", "validation_status": "VALIDATED", "boosts": [],
    }

    result = run_debate(**{**SIGNAL_KWARGS, "pre_confidence": 80})
    assert result.api_calls_used == 1
