"""Tests for Signal Cards and Validator."""

from mcp_server.signal_cards import (
    format_buy_signal,
    format_short_signal,
    format_fo_signal,
    format_alert,
    format_mwa_briefing,
)
from mcp_server.validator import validate_signal


# ── format_buy_signal ─────────────────────────────────────────

def test_buy_signal_basic():
    card = format_buy_signal(
        signal_id=1, ticker="NSE:RELIANCE", company_name="Reliance Industries",
        entry_price=2500.0, stop_loss=2450.0, target=2650.0, rrr=3.0,
        qty=10, risk_amt=500, pattern="Bullish Engulfing",
        ai_confidence=75, ai_reasoning="Strong setup",
        mwa_direction="BULL", scanner_count=12, tv_confirmed=True,
        tier=3, source="MWA",
    )
    assert "BUY SIGNAL" in card
    assert "RELIANCE" in card
    assert "TV CONFIRMED" in card
    assert "2,500.00" in card
    assert "#001" in card


def test_buy_signal_with_ltrp():
    card = format_buy_signal(
        signal_id=5, ticker="NSE:SBIN", company_name="SBI",
        entry_price=600, stop_loss=590, target=630, rrr=3.0,
        qty=20, risk_amt=200, pattern="Double Bottom",
        ai_confidence=65, ai_reasoning="Decent",
        mwa_direction="MILD_BULL", scanner_count=8, tv_confirmed=False,
        tier=2, source="Chartink", ltrp=595,
    )
    assert "LTRP" in card
    assert "595" in card


def test_buy_signal_with_boosts():
    card = format_buy_signal(
        signal_id=10, ticker="NSE:TCS", company_name="TCS",
        entry_price=3500, stop_loss=3400, target=3800, rrr=3.0,
        qty=5, risk_amt=500, pattern="Breakout",
        ai_confidence=85, ai_reasoning="Strong",
        mwa_direction="BULL", scanner_count=15, tv_confirmed=True,
        tier=3, source="MWA", boosts=["Supertrend +15%", "FII +10%"],
    )
    assert "Supertrend +15%" in card
    assert "FII +10%" in card


def test_buy_signal_low_confidence():
    card = format_buy_signal(
        signal_id=1, ticker="NSE:TEST", company_name="Test",
        entry_price=100, stop_loss=95, target=115, rrr=3.0,
        qty=100, risk_amt=500, pattern="Test",
        ai_confidence=30, ai_reasoning="Weak",
        mwa_direction="SIDEWAYS", scanner_count=3, tv_confirmed=False,
        tier=1, source="test",
    )
    assert "LOW" in card


# ── format_short_signal ───────────────────────────────────────

def test_short_signal_basic():
    card = format_short_signal(
        signal_id=2, ticker="NSE:TATASTEEL", company_name="Tata Steel",
        entry_price=150, stop_loss=155, target=135, rrr=3.0,
        qty=100, risk_amt=500, pattern="Head & Shoulders",
        ai_confidence=70, ai_reasoning="Bearish setup",
        mwa_direction="BEAR", scanner_count=10, tv_confirmed=False,
        tier=3, source="Pattern",
    )
    assert "SHORT SIGNAL" in card
    assert "TATASTEEL" in card


# ── format_fo_signal ──────────────────────────────────────────

def test_fo_signal_bullish():
    card = format_fo_signal(
        verdict="STRONG_BULL",
        components={"oi": "BULLISH", "pcr": "BULLISH", "nifty_ema": "BUY"},
        details={},
    )
    assert "STRONG_BULL" in card
    assert "oi" in card


def test_fo_signal_neutral():
    card = format_fo_signal(
        verdict="NEUTRAL",
        components={"oi": "NEUTRAL"},
        details={},
    )
    assert "NEUTRAL" in card


# ── format_alert ──────────────────────────────────────────────

def test_alert_entry_zone():
    msg = format_alert("ENTRY_ZONE", "NSE:RELIANCE", 2500, {"ltrp": 2480, "rrr": 3.5, "qty": 10})
    assert "ENTRY ZONE" in msg
    assert "RELIANCE" in msg


def test_alert_target_hit():
    msg = format_alert("TARGET_HIT", "NSE:SBIN", 650, {"target": 640, "pnl_pct": 8.3})
    assert "TARGET HIT" in msg
    assert "+8.3%" in msg


def test_alert_stoploss_hit():
    msg = format_alert("STOPLOSS_HIT", "NSE:TCS", 3400, {"stop_loss": 3450, "pnl_pct": -2.9})
    assert "STOP LOSS" in msg


def test_alert_deteriorating():
    msg = format_alert("DETERIORATING", "NSE:TEST", 100, {"prrr": 4.0, "crrr": 1.5})
    assert "DETERIORATING" in msg
    assert "4.0" in msg


def test_alert_resistance_break():
    msg = format_alert("RESISTANCE_BREAK", "NSE:TEST", 200, {"pivot_high": 195})
    assert "RESISTANCE" in msg


def test_alert_support_break():
    msg = format_alert("SUPPORT_BREAK", "NSE:TEST", 90, {"ltrp": 95})
    assert "SUPPORT" in msg


def test_alert_unknown_type():
    msg = format_alert("CUSTOM", "NSE:TEST", 100, {})
    assert "ALERT" in msg


# ── format_mwa_briefing ──────────────────────────────────────

def test_mwa_briefing_bullish():
    card = format_mwa_briefing(
        mwa_score={"direction": "BULL", "bull_pct": 65, "bear_pct": 20},
        fii_data={"fii_net": 1500, "dii_net": 800},
        promoted_stocks=["RELIANCE", "SBIN", "TCS"],
    )
    assert "BULL" in card
    assert "1,500" in card
    assert "RELIANCE" in card


def test_mwa_briefing_no_promoted():
    card = format_mwa_briefing(
        mwa_score={"direction": "SIDEWAYS", "bull_pct": 45, "bear_pct": 40},
        fii_data={"fii_net": -500, "dii_net": 200},
        promoted_stocks=[],
    )
    assert "SIDEWAYS" in card
    assert "promoted" not in card.lower()


# ── validate_signal (without API key) ─────────────────────────

def test_validate_no_api_key_high():
    """Without API key, validator must BLOCK — never approve unvalidated signals."""
    result = validate_signal(
        ticker="RELIANCE", direction="LONG", pattern="Bullish Engulfing",
        rrr=4.0, entry_price=2500, stop_loss=2450, target=2700,
        mwa_direction="BULL", scanner_count=12, tv_confirmed=True,
        sector_strength="STRONG", fii_net=1000, delivery_pct=70,
        confidence_boosts=["TV +10%"], pre_confidence=75,
    )
    assert result["confidence"] == 0
    assert result["recommendation"] == "BLOCKED"
    assert result["validation_status"] == "SKIPPED"


def test_validate_no_api_key_medium():
    """Without API key, BLOCK regardless of pre_confidence."""
    result = validate_signal(
        ticker="TEST", direction="LONG", pattern="Test",
        rrr=3.0, entry_price=100, stop_loss=95, target=115,
        mwa_direction="MILD_BULL", scanner_count=5, tv_confirmed=False,
        sector_strength="NEUTRAL", fii_net=0, delivery_pct=40,
        confidence_boosts=[], pre_confidence=55,
    )
    assert result["recommendation"] == "BLOCKED"


def test_validate_no_api_key_low():
    """Without API key, BLOCK regardless of pre_confidence."""
    result = validate_signal(
        ticker="TEST", direction="LONG", pattern="Test",
        rrr=3.0, entry_price=100, stop_loss=95, target=115,
        mwa_direction="BEAR", scanner_count=2, tv_confirmed=False,
        sector_strength="WEAK", fii_net=-3000, delivery_pct=20,
        confidence_boosts=[], pre_confidence=30,
    )
    assert result["recommendation"] == "BLOCKED"
