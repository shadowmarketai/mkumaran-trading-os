"""
MKUMARAN Trading OS — Debate Validator (Multi-Agent)

Adversarial bull/bear debate for uncertain signals (pre_confidence 40-75).
Clear signals bypass debate and use single-pass validation (1 API call).

Signal Flow:
  BM25 Memory lookup (0 API calls)
  → Triage: uncertain zone?
  → YES: Bull(1) → Bear(1) → Bull rebuttal(1) → Bear rebuttal(1) → Judge(1) → Risk(1) = 6 calls
  → NO: single-pass validation = 1 call

Fallback chain: debate fails → single-pass → BLOCK (fail-safe preserved).
"""

import logging
from dataclasses import dataclass, field

from mcp_server.config import settings

logger = logging.getLogger(__name__)

# ── Result dataclasses ──────────────────────────────────────────────


@dataclass
class DebateMessage:
    """A single message in the bull/bear debate."""
    role: str          # "bull", "bear", "judge", "risk"
    round_num: int
    argument: str
    confidence: int    # 0-100


@dataclass
class DebateResult:
    """Final output of the debate validator."""
    final_confidence: int
    recommendation: str  # ALERT / WATCHLIST / SKIP / BLOCKED
    reasoning: str
    debate_transcript: list[dict] = field(default_factory=list)
    method: str = "single_pass"  # "debate" or "single_pass"
    validation_status: str = "VALIDATED"
    similar_trades: list[dict] = field(default_factory=list)
    risk_assessment: str = ""
    api_calls_used: int = 0
    boosts: list[str] = field(default_factory=list)


# ── Triage logic ────────────────────────────────────────────────────


def should_debate(pre_confidence: int) -> bool:
    """
    Returns True if the signal is in the uncertain zone and needs debate.

    Signals with clear conviction (>75 or <40) go single-pass.
    Uncertain signals (40-75) get the full debate treatment.
    """
    low = settings.DEBATE_UNCERTAIN_LOW
    high = settings.DEBATE_UNCERTAIN_HIGH
    return low <= pre_confidence <= high


# ── Context builders ────────────────────────────────────────────────


def _build_signal_context(
    ticker: str,
    direction: str,
    pattern: str,
    rrr: float,
    entry_price: float,
    stop_loss: float,
    target: float,
    mwa_direction: str,
    scanner_count: int,
    tv_confirmed: bool,
    sector_strength: str,
    fii_net: float,
    delivery_pct: float,
    confidence_boosts: list[str],
    pre_confidence: int,
) -> str:
    """Build shared signal context string for all debate agents."""
    is_leveraged = any(
        pfx in ticker.upper() for pfx in ("MCX:", "NFO:", "CDS:", "NIFTY", "BANKNIFTY")
    )
    rrr_status = "PASS" if (rrr >= 2.0 if is_leveraged else rrr >= 3.0) else "FAIL"

    return (
        f"SIGNAL FOR ANALYSIS:\n"
        f"- Ticker: {ticker} | Direction: {direction} | Pattern: {pattern}\n"
        f"- Entry: ₹{entry_price:.2f} | SL: ₹{stop_loss:.2f} | Target: ₹{target:.2f} | RRR: {rrr:.2f} ({rrr_status})\n"
        f"- MWA Direction: {mwa_direction} | Scanner Hits: {scanner_count}\n"
        f"- TradingView Confirmed: {tv_confirmed}\n"
        f"- Sector: {sector_strength} | FII Net: ₹{fii_net:.0f} Cr | Delivery: {delivery_pct:.1f}%\n"
        f"- Pre-filter Confidence: {pre_confidence}% | Boosts: {', '.join(confidence_boosts) if confidence_boosts else 'None'}\n"
        f"- Asset Type: {'Leveraged (NFO/MCX/CDS)' if is_leveraged else 'Equity'}"
    )


def _build_memory_context(similar_trades: list[dict]) -> str:
    """Format past similar trades for prompt injection."""
    if not similar_trades:
        return "No similar past trades found in memory."

    lines = ["SIMILAR PAST TRADES (from memory):"]
    for i, t in enumerate(similar_trades, 1):
        outcome_str = t.get("outcome", "OPEN") or "OPEN"
        pnl = t.get("pnl_pct", 0)
        lesson = t.get("lesson", "")
        lines.append(
            f"{i}. {t['ticker']} {t['direction']} — RRR:{t['rrr']:.1f}, "
            f"Conf:{t['confidence']}%, Outcome:{outcome_str} ({pnl:+.1f}%)"
            f"{f' | Lesson: {lesson}' if lesson else ''}"
        )
    return "\n".join(lines)


# ── Agent calls (each = 1 API call) ────────────────────────────────


def _call_claude(client, system_prompt: str, user_prompt: str) -> dict:
    """
    Make a single AI call (Grok/Kimi) and parse JSON response.

    The `client` parameter is ignored — we use the unified ai_provider.
    Returns parsed dict or raises on failure.
    """
    from mcp_server.ai_provider import call_ai_with_system
    return call_ai_with_system(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=400,
        temperature=0.3,
    )


def _call_bull_analyst(client, ctx: str, memory_ctx: str, bear_argument: str = "") -> DebateMessage:
    """Bull analyst: argues FOR taking the trade."""
    system = (
        "You are a BULL analyst for Indian stock markets. "
        "Your job is to find every reason this trade SHOULD be taken. "
        "Be specific about technical, fundamental, and market context evidence. "
        "Respond ONLY in JSON: {\"confidence\": <50-95>, \"argument\": \"<2-3 sentences>\"}"
    )
    rebuttal = f"\n\nBEAR COUNTERARGUMENT TO ADDRESS:\n{bear_argument}" if bear_argument else ""
    user = f"{ctx}\n\n{memory_ctx}{rebuttal}\n\nProvide your BULLISH analysis."

    result = _call_claude(client, system, user)
    return DebateMessage(
        role="bull",
        round_num=2 if bear_argument else 1,
        argument=result.get("argument", ""),
        confidence=int(result.get("confidence", 50)),
    )


def _call_bear_analyst(client, ctx: str, memory_ctx: str, bull_argument: str = "") -> DebateMessage:
    """Bear analyst: argues AGAINST taking the trade."""
    system = (
        "You are a BEAR analyst for Indian stock markets. "
        "Your job is to find every reason this trade SHOULD NOT be taken. "
        "Look for red flags in RRR, market context, pattern reliability, and risk. "
        "Respond ONLY in JSON: {\"confidence\": <5-50>, \"argument\": \"<2-3 sentences>\"}"
    )
    rebuttal = f"\n\nBULL COUNTERARGUMENT TO ADDRESS:\n{bull_argument}" if bull_argument else ""
    user = f"{ctx}\n\n{memory_ctx}{rebuttal}\n\nProvide your BEARISH analysis."

    result = _call_claude(client, system, user)
    return DebateMessage(
        role="bear",
        round_num=2 if bull_argument else 1,
        argument=result.get("argument", ""),
        confidence=int(result.get("confidence", 50)),
    )


def _call_judge(client, ctx: str, transcript: list[DebateMessage]) -> dict:
    """Judge synthesizes the debate into a final score."""
    system = (
        "You are an impartial JUDGE for a trading signal debate. "
        "You've heard bull and bear arguments. Synthesize both sides into a final verdict. "
        "Weight the strength of arguments, not just confidence numbers. "
        "Respond ONLY in JSON: {\"confidence\": <0-100>, \"reasoning\": \"<2-3 sentences>\", "
        "\"recommendation\": \"ALERT|WATCHLIST|SKIP\"}"
    )

    debate_text = "\n\n".join(
        f"{'BULL' if m.role == 'bull' else 'BEAR'} (Round {m.round_num}, conf={m.confidence}%):\n{m.argument}"
        for m in transcript
    )

    user = f"{ctx}\n\nDEBATE TRANSCRIPT:\n{debate_text}\n\nDeliver your verdict."
    return _call_claude(client, system, user)


def _call_risk_assessment(client, ctx: str, judge_result: dict) -> dict:
    """
    3-way risk assessment in a single call.

    Evaluates from aggressive, conservative, and neutral perspectives.
    """
    system = (
        "You are a 3-way risk assessor for Indian market trades. "
        "Evaluate from three perspectives:\n"
        "1. AGGRESSIVE: Would a risk-seeking trader take this? Why?\n"
        "2. CONSERVATIVE: Would a risk-averse trader take this? Why?\n"
        "3. NEUTRAL: What's the balanced view?\n\n"
        "Based on all three perspectives, provide a final risk-adjusted confidence.\n"
        "Respond ONLY in JSON: {\"confidence\": <0-100>, \"risk_assessment\": \"<summary>\", "
        "\"adjustment\": <-15 to +10>}"
    )
    user = (
        f"{ctx}\n\n"
        f"JUDGE VERDICT: confidence={judge_result.get('confidence', 50)}%, "
        f"reasoning: {judge_result.get('reasoning', '')}\n\n"
        f"Provide 3-way risk assessment."
    )
    return _call_claude(client, system, user)


# ── Main orchestrator ───────────────────────────────────────────────


def run_debate(
    ticker: str,
    direction: str,
    pattern: str,
    rrr: float,
    entry_price: float,
    stop_loss: float,
    target: float,
    mwa_direction: str,
    scanner_count: int,
    tv_confirmed: bool,
    sector_strength: str,
    fii_net: float,
    delivery_pct: float,
    confidence_boosts: list[str],
    pre_confidence: int,
    similar_trades: list[dict] | None = None,
) -> DebateResult:
    """
    Main debate validator orchestrator.

    Decides between debate (6 API calls) and single-pass (1 API call)
    based on pre_confidence triage.

    Fallback chain: debate → single-pass → BLOCK.
    """
    if similar_trades is None:
        similar_trades = []

    # ── Primary: Use skill-based agents (ZERO API calls) ─────────
    try:
        from mcp_server.skill_agents import run_skill_debate
        skill_result = run_skill_debate(
            ticker=ticker, direction=direction, pattern=pattern, rrr=rrr,
            entry_price=entry_price, stop_loss=stop_loss, target=target,
            mwa_direction=mwa_direction, scanner_count=scanner_count,
            sector_strength=sector_strength, fii_net=fii_net,
            delivery_pct=delivery_pct,
        )
        # Convert to our DebateResult format
        return DebateResult(
            final_confidence=skill_result.final_confidence,
            recommendation=skill_result.recommendation,
            reasoning=skill_result.reasoning,
            method=skill_result.method,
            api_calls_used=0,
            debate_transcript=skill_result.debate_transcript,
            risk_assessment=skill_result.risk_assessment,
            boosts=skill_result.boosts,
            validation_status="VALIDATED",
        )
    except Exception as skill_err:
        logger.warning("Skill agents failed, falling back to LLM: %s", skill_err)

    # ── Fallback: LLM debate (only if skill agents fail) ──────────
    if not settings.DEBATE_ENABLED:
        return _run_single_pass(
            ticker=ticker, direction=direction, pattern=pattern, rrr=rrr,
            entry_price=entry_price, stop_loss=stop_loss, target=target,
            mwa_direction=mwa_direction, scanner_count=scanner_count,
            tv_confirmed=tv_confirmed, sector_strength=sector_strength,
            fii_net=fii_net, delivery_pct=delivery_pct,
            confidence_boosts=confidence_boosts, pre_confidence=pre_confidence,
            similar_trades=similar_trades,
        )

    # ── Triage: debate or single-pass? ──────────────────────────
    if not should_debate(pre_confidence):
        logger.info(
            "Debate triage: %s pre_confidence=%d — outside uncertain zone, using single-pass",
            ticker, pre_confidence,
        )
        return _run_single_pass(
            ticker=ticker, direction=direction, pattern=pattern, rrr=rrr,
            entry_price=entry_price, stop_loss=stop_loss, target=target,
            mwa_direction=mwa_direction, scanner_count=scanner_count,
            tv_confirmed=tv_confirmed, sector_strength=sector_strength,
            fii_net=fii_net, delivery_pct=delivery_pct,
            confidence_boosts=confidence_boosts, pre_confidence=pre_confidence,
            similar_trades=similar_trades,
        )

    # ── Run full debate ─────────────────────────────────────────
    logger.info(
        "Debate triage: %s pre_confidence=%d — uncertain zone, running debate",
        ticker, pre_confidence,
    )

    try:
        return _run_full_debate(
            ticker=ticker, direction=direction, pattern=pattern, rrr=rrr,
            entry_price=entry_price, stop_loss=stop_loss, target=target,
            mwa_direction=mwa_direction, scanner_count=scanner_count,
            tv_confirmed=tv_confirmed, sector_strength=sector_strength,
            fii_net=fii_net, delivery_pct=delivery_pct,
            confidence_boosts=confidence_boosts, pre_confidence=pre_confidence,
            similar_trades=similar_trades,
        )
    except Exception as e:
        logger.error("Debate failed for %s, falling back to single-pass: %s", ticker, e)
        try:
            return _run_single_pass(
                ticker=ticker, direction=direction, pattern=pattern, rrr=rrr,
                entry_price=entry_price, stop_loss=stop_loss, target=target,
                mwa_direction=mwa_direction, scanner_count=scanner_count,
                tv_confirmed=tv_confirmed, sector_strength=sector_strength,
                fii_net=fii_net, delivery_pct=delivery_pct,
                confidence_boosts=confidence_boosts, pre_confidence=pre_confidence,
                similar_trades=similar_trades,
            )
        except Exception as e2:
            logger.error("Single-pass also failed for %s — BLOCKING: %s", ticker, e2)
            return DebateResult(
                final_confidence=0,
                recommendation="BLOCKED",
                reasoning=f"BLOCKED: Both debate and single-pass validation failed. "
                          f"Debate error: {e}. Single-pass error: {e2}.",
                method="blocked",
                validation_status="FAILED",
                similar_trades=similar_trades,
                boosts=confidence_boosts,
            )


def _run_single_pass(
    ticker: str, direction: str, pattern: str, rrr: float,
    entry_price: float, stop_loss: float, target: float,
    mwa_direction: str, scanner_count: int, tv_confirmed: bool,
    sector_strength: str, fii_net: float, delivery_pct: float,
    confidence_boosts: list[str], pre_confidence: int,
    similar_trades: list[dict],
) -> DebateResult:
    """Single-pass validation — wraps existing validator.validate_signal()."""
    from mcp_server.validator import validate_signal

    result = validate_signal(
        ticker=ticker, direction=direction, pattern=pattern, rrr=rrr,
        entry_price=entry_price, stop_loss=stop_loss, target=target,
        mwa_direction=mwa_direction, scanner_count=scanner_count,
        tv_confirmed=tv_confirmed, sector_strength=sector_strength,
        fii_net=fii_net, delivery_pct=delivery_pct,
        confidence_boosts=confidence_boosts, pre_confidence=pre_confidence,
    )

    return DebateResult(
        final_confidence=result.get("confidence", 0),
        recommendation=result.get("recommendation", "BLOCKED"),
        reasoning=result.get("reasoning", ""),
        method="single_pass",
        validation_status=result.get("validation_status", "FAILED"),
        similar_trades=similar_trades,
        api_calls_used=1 if result.get("validation_status") == "VALIDATED" else 0,
        boosts=result.get("boosts", confidence_boosts),
    )


def _run_full_debate(
    ticker: str, direction: str, pattern: str, rrr: float,
    entry_price: float, stop_loss: float, target: float,
    mwa_direction: str, scanner_count: int, tv_confirmed: bool,
    sector_strength: str, fii_net: float, delivery_pct: float,
    confidence_boosts: list[str], pre_confidence: int,
    similar_trades: list[dict],
) -> DebateResult:
    """
    Full 2-round debate + judge + risk assessment.

    API call budget: bull(1) + bear(1) + bull_rebuttal(1) + bear_rebuttal(1) + judge(1) + risk(1) = 6
    """
    # ── API key gates (same as validator.py) ────────────────────
    if not settings.ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set")

    # Client is no longer needed — ai_provider handles it internally
    # But we pass None to maintain function signatures
    client = None

    ctx = _build_signal_context(
        ticker=ticker, direction=direction, pattern=pattern, rrr=rrr,
        entry_price=entry_price, stop_loss=stop_loss, target=target,
        mwa_direction=mwa_direction, scanner_count=scanner_count,
        tv_confirmed=tv_confirmed, sector_strength=sector_strength,
        fii_net=fii_net, delivery_pct=delivery_pct,
        confidence_boosts=confidence_boosts, pre_confidence=pre_confidence,
    )
    memory_ctx = _build_memory_context(similar_trades)
    api_calls = 0
    transcript: list[DebateMessage] = []

    # Round 1: Bull opens, Bear responds
    bull_r1 = _call_bull_analyst(client, ctx, memory_ctx)
    api_calls += 1
    transcript.append(bull_r1)

    bear_r1 = _call_bear_analyst(client, ctx, memory_ctx, bull_argument=bull_r1.argument)
    api_calls += 1
    transcript.append(bear_r1)

    # Round 2: Bull rebuts, Bear rebuts
    bull_r2 = _call_bull_analyst(client, ctx, memory_ctx, bear_argument=bear_r1.argument)
    api_calls += 1
    transcript.append(bull_r2)

    bear_r2 = _call_bear_analyst(client, ctx, memory_ctx, bull_argument=bull_r2.argument)
    api_calls += 1
    transcript.append(bear_r2)

    # Judge synthesizes
    judge_result = _call_judge(client, ctx, transcript)
    api_calls += 1

    # Risk assessment (3-way)
    risk_result = _call_risk_assessment(client, ctx, judge_result)
    api_calls += 1

    # ── Compute final confidence ────────────────────────────────
    judge_conf = int(judge_result.get("confidence", 50))
    risk_adj = int(risk_result.get("adjustment", 0))
    # Clamp risk adjustment to [-15, +10]
    risk_adj = max(-15, min(10, risk_adj))

    final_confidence = max(0, min(100, judge_conf + risk_adj))

    # Enforce recommendation thresholds
    if final_confidence >= 70:
        recommendation = "ALERT"
    elif final_confidence >= 50:
        recommendation = "WATCHLIST"
    else:
        recommendation = "SKIP"

    reasoning = judge_result.get("reasoning", "")
    risk_assessment = risk_result.get("risk_assessment", "")

    logger.info(
        "Debate complete for %s: judge=%d, risk_adj=%+d, final=%d → %s (%d API calls)",
        ticker, judge_conf, risk_adj, final_confidence, recommendation, api_calls,
    )

    return DebateResult(
        final_confidence=final_confidence,
        recommendation=recommendation,
        reasoning=reasoning,
        debate_transcript=[
            {"role": m.role, "round": m.round_num, "confidence": m.confidence, "argument": m.argument}
            for m in transcript
        ],
        method="debate",
        validation_status="VALIDATED",
        similar_trades=similar_trades,
        risk_assessment=risk_assessment,
        api_calls_used=api_calls,
        boosts=confidence_boosts,
    )
