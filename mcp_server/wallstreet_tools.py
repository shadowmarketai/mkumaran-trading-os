"""
Wall Street Tools -- 10 AI-powered analysis functions for MKUMARAN Trading OS.
Each function wraps a Wall Street prompt template and calls AI (Grok/Kimi).
"""
import logging
import json
from mcp_server.ai_provider import call_ai, call_ai_second_opinion
from mcp_server.prompts import (
    GOLDMAN_SCREEN_PROMPT,
    MORGAN_STANLEY_DCF_PROMPT,
    BRIDGEWATER_RISK_PROMPT,
    JPMORGAN_EARNINGS_PROMPT,
    BLACKROCK_PORTFOLIO_PROMPT,
    CITADEL_TECHNICAL_PROMPT,
    HARVARD_DIVIDEND_PROMPT,
    RENAISSANCE_PATTERN_PROMPT,
    MCKINSEY_MACRO_PROMPT,
)

logger = logging.getLogger(__name__)


def _call_claude(prompt: str, max_tokens: int = 500) -> str:
    """Call primary AI provider (Grok/Kimi). Legacy name kept for compatibility."""
    return call_ai(prompt=prompt, max_tokens=max_tokens)


def _call_gpt(prompt: str, max_tokens: int = 500, model: str = "") -> str:
    """Call secondary AI provider for second opinion. Legacy name kept for compatibility."""
    return call_ai_second_opinion(prompt=prompt, max_tokens=max_tokens)


async def generate_ai_report(report_type: str, data: dict) -> str:
    """Generate an AI narrative report for morning brief or EOD."""
    from .prompts import MORNING_BRIEF_PROMPT, EOD_REPORT_PROMPT

    prompt_map = {
        "morning": MORNING_BRIEF_PROMPT,
        "eod": EOD_REPORT_PROMPT,
    }
    template = prompt_map.get(report_type)
    if not template:
        return f"Unknown report type: {report_type}"

    prompt = template.format(data=json.dumps(data, indent=2, default=str))
    return _call_claude(prompt, max_tokens=1000)


def _parse_json(text: str) -> dict:
    """Extract JSON from Claude response."""
    try:
        if "{" in text:
            json_str = text[text.index("{"):text.rindex("}") + 1]
            return json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        pass
    return {"raw_response": text}


# === Prompt 1: Goldman Sachs Fundamental Screen ===
def fundamental_screen(
    ticker: str,
    company_name: str,
    cmp: float,
    sector: str,
    signal_type: str = "LONG",
    rrr: float = 0,
    pattern: str = "",
) -> dict:
    """Run Goldman Sachs fundamental screen on a signal. Auto-triggered on every Tier 1 promotion."""
    prompt = GOLDMAN_SCREEN_PROMPT.format(
        ticker=ticker, company_name=company_name, cmp=cmp,
        sector=sector, signal_type=signal_type, rrr=rrr, pattern=pattern,
    )
    return _parse_json(_call_claude(prompt, max_tokens=500))


# === Prompt 2: Morgan Stanley DCF Valuation ===
def dcf_valuation(
    ticker: str,
    company_name: str,
    cmp: float,
    market_cap: float,
    sector: str,
) -> dict:
    """Run Morgan Stanley DCF valuation. Triggered by Cowork Dispatch 'DCF TICKER'."""
    prompt = MORGAN_STANLEY_DCF_PROMPT.format(
        ticker=ticker, company_name=company_name, cmp=cmp,
        market_cap=market_cap, sector=sector,
    )
    return _parse_json(_call_claude(prompt, max_tokens=1000))


# === Prompt 3: Bridgewater Risk Analysis ===
def portfolio_risk_report(
    positions_table: str,
    deployed: float,
    total_value: float,
    win_rate: float,
    active_count: int,
) -> dict:
    """Weekly Bridgewater risk analysis. Auto-triggered by n8n every Sunday 6 PM."""
    prompt = BRIDGEWATER_RISK_PROMPT.format(
        positions_table=positions_table, deployed=deployed,
        total_value=total_value, win_rate=win_rate, active_count=active_count,
    )
    return _parse_json(_call_claude(prompt, max_tokens=800))


# === Prompt 4: JPMorgan Pre-Earnings ===
def pre_earnings_brief(
    ticker: str,
    company_name: str,
    earnings_date: str,
    cmp: float,
    position_type: str = "WATCHING",
) -> dict:
    """Pre-earnings analysis. Auto-triggered 2 days before earnings."""
    prompt = JPMORGAN_EARNINGS_PROMPT.format(
        ticker=ticker, company_name=company_name,
        earnings_date=earnings_date, cmp=cmp, position_type=position_type,
    )
    return _parse_json(_call_claude(prompt, max_tokens=600))


# === Prompt 5: BlackRock Portfolio Construction ===
def portfolio_construction(
    trading_capital: float,
    investment_capital: float,
    monthly_savings: float,
    win_rate: float,
    tax_bracket: int = 30,
) -> dict:
    """Quarterly portfolio review. Triggered by Cowork Dispatch 'Portfolio review'."""
    prompt = BLACKROCK_PORTFOLIO_PROMPT.format(
        trading_capital=trading_capital, investment_capital=investment_capital,
        monthly_savings=monthly_savings, win_rate=win_rate, tax_bracket=tax_bracket,
    )
    return _parse_json(_call_claude(prompt, max_tokens=800))


# === Prompt 6: Citadel Technical Summary ===
def citadel_technical_summary(
    ticker: str,
    timeframe: str,
    cmp: float,
    ema20: float = 0,
    ema50: float = 0,
    ema200: float = 0,
    rsi: float = 0,
    macd: float = 0,
    macd_signal: float = 0,
    histogram: float = 0,
    volume: int = 0,
    avg_volume: int = 0,
    vol_ratio: float = 0,
    pattern: str = "",
    mwa_direction: str = "",
    scanner_count: int = 0,
    supertrend_status: str = "",
) -> str:
    """3-sentence technical summary for Telegram card. Auto-triggered on every signal."""
    prompt = CITADEL_TECHNICAL_PROMPT.format(
        ticker=ticker, timeframe=timeframe, cmp=cmp,
        ema20=ema20, ema50=ema50, ema200=ema200, rsi=rsi,
        macd=macd, macd_signal=macd_signal, histogram=histogram,
        volume=volume, avg_volume=avg_volume, vol_ratio=vol_ratio,
        pattern=pattern, mwa_direction=mwa_direction,
        scanner_count=scanner_count, supertrend_status=supertrend_status,
    )
    return _call_claude(prompt, max_tokens=200)


# === Prompt 7: Harvard Dividend Portfolio ===
def dividend_portfolio(
    investment_amount: float,
    monthly_income_goal: float,
    tax_bracket: int = 30,
    time_horizon: int = 10,
) -> dict:
    """Dividend portfolio builder. Triggered by Cowork Dispatch 'Dividend portfolio'."""
    prompt = HARVARD_DIVIDEND_PROMPT.format(
        investment_amount=investment_amount,
        monthly_income_goal=monthly_income_goal,
        tax_bracket=tax_bracket, time_horizon=time_horizon,
    )
    return _parse_json(_call_claude(prompt, max_tokens=800))


# === Prompt 9: Renaissance Quant Research ===
def quant_research(
    ticker: str,
    company_name: str,
    sector: str,
    promotion_reason: str = "",
) -> dict:
    """Quant pattern finder. Auto-triggered when stock promoted to Tier 2."""
    prompt = RENAISSANCE_PATTERN_PROMPT.format(
        ticker=ticker, company_name=company_name,
        sector=sector, promotion_reason=promotion_reason,
    )
    return _parse_json(_call_claude(prompt, max_tokens=600))


# === Prompt 10: McKinsey Macro Assessment ===
def macro_assessment(
    repo_rate: float = 6.5,
    last_change: str = "unchanged",
    cpi: float = 5.0,
    gsec_yield: float = 7.2,
    inr_rate: float = 83.5,
    fii_mtd: float = 0,
    dii_mtd: float = 0,
    nifty_mtd: float = 0,
) -> dict:
    """Monthly macro assessment. Auto-triggered by n8n on 1st of month."""
    prompt = MCKINSEY_MACRO_PROMPT.format(
        repo_rate=repo_rate, last_change=last_change, cpi=cpi,
        gsec_yield=gsec_yield, inr_rate=inr_rate,
        fii_mtd=fii_mtd, dii_mtd=dii_mtd, nifty_mtd=nifty_mtd,
    )
    return _parse_json(_call_claude(prompt, max_tokens=600))
