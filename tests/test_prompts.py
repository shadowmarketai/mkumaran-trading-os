"""Tests for Wall Street Prompts."""

from mcp_server.prompts import (
    GOLDMAN_SCREEN_PROMPT,
    MORGAN_STANLEY_DCF_PROMPT,
    BRIDGEWATER_RISK_PROMPT,
    JPMORGAN_EARNINGS_PROMPT,
    BLACKROCK_PORTFOLIO_PROMPT,
    CITADEL_TECHNICAL_PROMPT,
    HARVARD_DIVIDEND_PROMPT,
    BAIN_COMPETITIVE_PROMPT,
    RENAISSANCE_PATTERN_PROMPT,
    MCKINSEY_MACRO_PROMPT,
)


# ── All 10 Prompts Exist ────────────────────────────────────

def test_all_prompts_are_strings():
    prompts = [
        GOLDMAN_SCREEN_PROMPT, MORGAN_STANLEY_DCF_PROMPT,
        BRIDGEWATER_RISK_PROMPT, JPMORGAN_EARNINGS_PROMPT,
        BLACKROCK_PORTFOLIO_PROMPT, CITADEL_TECHNICAL_PROMPT,
        HARVARD_DIVIDEND_PROMPT, BAIN_COMPETITIVE_PROMPT,
        RENAISSANCE_PATTERN_PROMPT, MCKINSEY_MACRO_PROMPT,
    ]
    for p in prompts:
        assert isinstance(p, str)
        assert len(p) > 100


# ── Goldman Sachs Prompt ─────────────────────────────────────

def test_goldman_prompt_placeholders():
    result = GOLDMAN_SCREEN_PROMPT.format(
        ticker="NSE:RELIANCE", company_name="Reliance Industries",
        cmp=2500, sector="Energy", signal_type="BUY",
        rrr=3.5, pattern="Bullish Engulfing",
    )
    assert "RELIANCE" in result
    assert "Energy" in result
    assert "2500" in result


def test_goldman_prompt_requests_json():
    assert "JSON" in GOLDMAN_SCREEN_PROMPT
    assert "moat" in GOLDMAN_SCREEN_PROMPT
    assert "conviction" in GOLDMAN_SCREEN_PROMPT


# ── Morgan Stanley DCF Prompt ────────────────────────────────

def test_morgan_stanley_placeholders():
    result = MORGAN_STANLEY_DCF_PROMPT.format(
        ticker="NSE:TCS", company_name="TCS",
        cmp=3500, market_cap=1200000, sector="IT",
    )
    assert "TCS" in result
    assert "3500" in result


def test_morgan_stanley_dcf_elements():
    assert "WACC" in MORGAN_STANLEY_DCF_PROMPT
    assert "terminal" in MORGAN_STANLEY_DCF_PROMPT.lower()
    assert "sensitivity" in MORGAN_STANLEY_DCF_PROMPT.lower()


# ── Bridgewater Risk Prompt ──────────────────────────────────

def test_bridgewater_placeholders():
    result = BRIDGEWATER_RISK_PROMPT.format(
        positions_table="RELIANCE | 10 | 2500",
        deployed=250000, total_value=260000,
        win_rate=65, active_count=5,
    )
    assert "RELIANCE" in result
    assert "250000" in result


def test_bridgewater_stress_tests():
    assert "COVID" in BRIDGEWATER_RISK_PROMPT
    assert "FII" in BRIDGEWATER_RISK_PROMPT
    assert "hedging" in BRIDGEWATER_RISK_PROMPT.lower()


# ── Citadel Technical Prompt ─────────────────────────────────

def test_citadel_placeholders():
    result = CITADEL_TECHNICAL_PROMPT.format(
        ticker="NSE:SBIN", timeframe="Daily", cmp=600,
        ema20=595, ema50=580, ema200=550,
        rsi=62, macd=5.2, macd_signal=3.1, histogram=2.1,
        volume=5000000, avg_volume=3000000, vol_ratio=1.67,
        pattern="Double Bottom", mwa_direction="BULL",
        scanner_count=15, supertrend_status="BUY",
    )
    assert "SBIN" in result
    assert "3 sentences" in result


# ── McKinsey Macro Prompt ────────────────────────────────────

def test_mckinsey_placeholders():
    result = MCKINSEY_MACRO_PROMPT.format(
        repo_rate=6.5, last_change="Feb 2025",
        cpi=4.8, gsec_yield=7.1, inr_rate=83.5,
        fii_mtd=-2500, dii_mtd=3000, nifty_mtd=-1.2,
    )
    assert "6.5" in result
    assert "sector rotation" in result.lower()


# ── Harvard Dividend Prompt ──────────────────────────────────

def test_harvard_dividend_mentions_nse_stocks():
    assert "COALINDIA" in HARVARD_DIVIDEND_PROMPT
    assert "ITC" in HARVARD_DIVIDEND_PROMPT
    assert "POWERGRID" in HARVARD_DIVIDEND_PROMPT


# ── Renaissance Pattern Prompt ───────────────────────────────

def test_renaissance_mentions_seasonality():
    assert "seasonal" in RENAISSANCE_PATTERN_PROMPT.lower()
    assert "Diwali" in RENAISSANCE_PATTERN_PROMPT
    assert "Budget" in RENAISSANCE_PATTERN_PROMPT
