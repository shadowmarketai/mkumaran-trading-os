"""
MKUMARAN Trading OS — Signal Validator (v3 — Debate-Wired Fail-Safe)

Fixes over v2:
- Debate validator automatically triggered for uncertain signals (pre_confidence 40-75)
- API timeout protection (30s per call)
- BM25 trade memory lookup before validation
- Fallback chain: debate → single-pass → BLOCK

Fixes from v1:
- API failure = BLOCK signal (not approve)
- Explicit API key validation
- validation_status field: VALIDATED / FAILED / SKIPPED / BLOCKED
- Structured error handling — never silently approves
"""

import logging
import json
from mcp_server.config import settings

logger = logging.getLogger(__name__)

# Validation status constants
STATUS_VALIDATED = "VALIDATED"     # Claude AI reviewed and scored
STATUS_FAILED = "FAILED"          # API call failed — signal BLOCKED
STATUS_SKIPPED = "SKIPPED"        # No API key — signal BLOCKED
STATUS_BLOCKED = "BLOCKED"        # Below threshold — signal rejected


def get_gpt_second_opinion(
    symbol: str,
    signal_type: str,
    claude_confidence: int,
    context: dict,
) -> dict:
    """Get GPT's second opinion on a borderline signal (confidence 60-75).

    Returns dict with confidence, agree (bool), and reason.
    Falls back gracefully if GPT is unavailable.
    """
    from .wallstreet_tools import _call_gpt, _parse_json

    prompt = (
        "You are a stock market analyst providing a second opinion.\n\n"
        f"Symbol: {symbol}\n"
        f"Signal: {signal_type}\n"
        f"Claude's confidence: {claude_confidence}/100\n"
        f"Context: {json.dumps(context, default=str)}\n\n"
        'Respond in JSON: {"confidence": <0-100>, "agree": <true/false>, "reason": "<1 line>"}'
    )

    raw = _call_gpt(prompt, max_tokens=200)
    if not raw:
        return {"confidence": claude_confidence, "agree": True, "reason": "GPT unavailable"}

    parsed = _parse_json(raw)
    if "raw_response" in parsed:
        return {"confidence": claude_confidence, "agree": True, "reason": "Parse error"}
    return parsed


def validate_signal(
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
) -> dict:
    """
    Validate a trading signal using Claude AI.

    CRITICAL SAFETY: If AI validation fails for ANY reason,
    the signal is BLOCKED (not approved). This prevents false
    signals from reaching live trading.

    Returns dict with:
        confidence (0-100), reasoning, recommendation (ALERT/WATCHLIST/SKIP/BLOCKED),
        validation_status (VALIDATED/FAILED/SKIPPED/BLOCKED)
    """

    # ── Gate 1: API key must exist ────────────────────────────
    if not settings.ANTHROPIC_API_KEY:
        logger.warning(
            "BLOCKED %s: ANTHROPIC_API_KEY not set — cannot validate signal",
            ticker,
        )
        return {
            "confidence": 0,
            "reasoning": "BLOCKED: AI validation not available — API key not configured. "
                         "Signal cannot be approved without validation.",
            "recommendation": "BLOCKED",
            "validation_status": STATUS_SKIPPED,
            "boosts": confidence_boosts,
        }

    # ── Gate 2: API key format check ──────────────────────────
    api_key = settings.ANTHROPIC_API_KEY.strip()
    if len(api_key) < 20 or not api_key.startswith("sk-"):
        logger.warning(
            "BLOCKED %s: ANTHROPIC_API_KEY appears invalid (length=%d)",
            ticker, len(api_key),
        )
        return {
            "confidence": 0,
            "reasoning": "BLOCKED: API key appears invalid. "
                         "Check ANTHROPIC_API_KEY in .env file.",
            "recommendation": "BLOCKED",
            "validation_status": STATUS_SKIPPED,
            "boosts": confidence_boosts,
        }

    # ── Gate 3: Call AI (Grok/Kimi) ──────────────────────────
    try:
        from mcp_server.ai_provider import call_ai

        # Determine RRR threshold based on asset class
        rrr_threshold = "2:1 for MCX/NFO/CDS (leveraged), 3:1 for equity"
        is_leveraged = any(
            pfx in ticker.upper() for pfx in ("MCX:", "NFO:", "CDS:", "NIFTY", "BANKNIFTY")
        )

        prompt = f"""You are MKUMARAN's trading signal validator for Indian markets. Score this signal 0-100.

SIGNAL:
- Ticker: {ticker} | Direction: {direction} | Pattern: {pattern}
- Entry: ₹{entry_price:.2f} | SL: ₹{stop_loss:.2f} | Target: ₹{target:.2f} | RRR: {rrr:.2f}

MARKET CONTEXT:
- MWA Direction: {mwa_direction} (82-scanner breadth system)
- Scanner Hits for this stock: {scanner_count}
- TradingView Confirmed: {tv_confirmed}
- Sector: {sector_strength} | FII Net: ₹{fii_net:.0f} Cr | Delivery: {delivery_pct:.1f}%
- Pre-filter Confidence: {pre_confidence}% | Boosts: {', '.join(confidence_boosts) if confidence_boosts else 'None'}

SCORING RULES:
1. RRR: {rrr_threshold}. This signal has {rrr:.2f} — {"PASS" if (rrr >= 2.0 if is_leveraged else rrr >= 3.0) else "FAIL"}
2. If MWA is UNKNOWN, do NOT penalize heavily — it means morning scan hasn't run yet, not that market is bad
3. TradingView confirmation with valid entry/SL/TGT is strong technical evidence (worth +15-20 points)
4. A well-structured signal (clear entry, SL, target) with good RRR starts at 55-60 baseline
5. MWA alignment adds +10-15. Scanner hits add +5 per hit. FII/sector add +5 each if favorable

Respond ONLY in JSON:
{{"confidence": <0-100>, "reasoning": "<2-3 sentences>", "recommendation": "ALERT|WATCHLIST|SKIP"}}

Thresholds: >= 70 = ALERT (execute), 50-69 = WATCHLIST (monitor), < 50 = SKIP"""

        text = call_ai(prompt=prompt, max_tokens=300)

        # Try to extract JSON from response
        if "{" in text and "}" in text:
            json_str = text[text.index("{"):text.rindex("}") + 1]
            result = json.loads(json_str)
        else:
            # Claude responded but not in JSON — treat as ambiguous, BLOCK
            logger.warning(
                "BLOCKED %s: Claude response not in JSON format: %s",
                ticker, text[:100],
            )
            return {
                "confidence": 0,
                "reasoning": f"BLOCKED: AI response malformed. Raw: {text[:200]}",
                "recommendation": "BLOCKED",
                "validation_status": STATUS_FAILED,
                "boosts": confidence_boosts,
            }

        # Validate the response has required fields
        confidence = result.get("confidence", 0)
        if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 100:
            confidence = 0
            result["recommendation"] = "BLOCKED"
            result["reasoning"] = "BLOCKED: Invalid confidence score from AI"

        result["confidence"] = int(confidence)
        result["validation_status"] = STATUS_VALIDATED
        result["boosts"] = confidence_boosts

        # Enforce thresholds
        if result.get("recommendation") not in ("ALERT", "WATCHLIST", "SKIP"):
            if confidence >= 70:
                result["recommendation"] = "ALERT"
            elif confidence >= 50:
                result["recommendation"] = "WATCHLIST"
            else:
                result["recommendation"] = "SKIP"

        logger.info(
            "AI Validation for %s: confidence=%d, recommendation=%s, status=%s",
            ticker, result["confidence"], result["recommendation"], STATUS_VALIDATED,
        )

        return result

    except json.JSONDecodeError as e:
        logger.error("BLOCKED %s: Failed to parse AI response as JSON: %s", ticker, e)
        return {
            "confidence": 0,
            "reasoning": f"BLOCKED: AI response parse error: {e}",
            "recommendation": "BLOCKED",
            "validation_status": STATUS_FAILED,
            "boosts": confidence_boosts,
        }

    except Exception as e:
        # CRITICAL: On ANY error, BLOCK the signal
        logger.error("BLOCKED %s: AI validation failed: %s", ticker, e)
        return {
            "confidence": 0,
            "reasoning": f"BLOCKED: AI validation error: {e}. "
                         "Signal cannot be approved without successful validation.",
            "recommendation": "BLOCKED",
            "validation_status": STATUS_FAILED,
            "boosts": confidence_boosts,
        }


# Explicit alias for single-pass fallback (used by debate_validator)
validate_signal_simple = validate_signal


def validate_with_debate(
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
    exchange: str = "NSE",
) -> dict:
    """
    Enhanced validator that routes through debate for uncertain signals.

    Flow:
    1. BM25 memory lookup (0 API cost)
    2. Triage: pre_confidence 40-75 → full debate (6 calls)
    3. Otherwise → single-pass validation (1 call)
    4. Fallback: debate fails → single-pass → BLOCK

    Returns same dict format as validate_signal() for backward compatibility.
    """
    similar_trades = []

    # ── Step 1: BM25 Memory Lookup ───────────────────────────
    try:
        from mcp_server.trade_memory import TradeMemory
        memory = TradeMemory(filepath=settings.TRADE_MEMORY_FILE)
        similar_trades = memory.find_similar_for_signal(
            ticker=ticker,
            direction=direction,
            pattern=pattern,
            rrr=rrr,
            confidence=pre_confidence,
            exchange=exchange,
            top_k=settings.MEMORY_TOP_K,
        )
        if similar_trades:
            logger.info(
                "Memory lookup for %s: found %d similar trades",
                ticker, len(similar_trades),
            )
    except Exception as e:
        logger.warning("Trade memory lookup failed (non-fatal): %s", e)

    # ── Step 2: Route to debate or single-pass ───────────────
    try:
        from mcp_server.debate_validator import run_debate, should_debate

        if settings.DEBATE_ENABLED and should_debate(pre_confidence):
            logger.info(
                "Routing %s to DEBATE (pre_confidence=%d, uncertain zone)",
                ticker, pre_confidence,
            )
            result = run_debate(
                ticker=ticker, direction=direction, pattern=pattern, rrr=rrr,
                entry_price=entry_price, stop_loss=stop_loss, target=target,
                mwa_direction=mwa_direction, scanner_count=scanner_count,
                tv_confirmed=tv_confirmed, sector_strength=sector_strength,
                fii_net=fii_net, delivery_pct=delivery_pct,
                confidence_boosts=confidence_boosts, pre_confidence=pre_confidence,
                similar_trades=similar_trades,
            )
            confidence = result.final_confidence
            gpt_opinion = None

            # GPT second opinion for borderline signals (60-75 band)
            if 60 <= confidence <= 75:
                try:
                    gpt_opinion = get_gpt_second_opinion(
                        symbol=ticker,
                        signal_type=direction,
                        claude_confidence=confidence,
                        context={
                            "pattern": pattern, "rrr": rrr,
                            "mwa_direction": mwa_direction,
                            "scanner_count": scanner_count,
                        },
                    )
                    if not gpt_opinion.get("agree", True):
                        confidence = int(
                            (confidence + gpt_opinion.get("confidence", confidence)) / 2
                        )
                        logger.info(
                            "GPT disagrees on %s: adjusted confidence %d→%d (GPT: %d, reason: %s)",
                            ticker, result.final_confidence, confidence,
                            gpt_opinion.get("confidence"), gpt_opinion.get("reason"),
                        )
                except Exception as e:
                    logger.warning("GPT second opinion failed (non-fatal): %s", e)

            return {
                "confidence": confidence,
                "reasoning": result.reasoning,
                "recommendation": result.recommendation,
                "validation_status": result.validation_status,
                "boosts": result.boosts,
                "method": result.method,
                "api_calls_used": result.api_calls_used,
                "similar_trades": result.similar_trades,
                "risk_assessment": result.risk_assessment,
                "debate_transcript": result.debate_transcript,
                "gpt_opinion": gpt_opinion,
            }
    except Exception as e:
        logger.warning("Debate routing failed, falling back to single-pass: %s", e)

    # ── Step 3: Single-pass fallback ─────────────────────────
    result = validate_signal(
        ticker=ticker, direction=direction, pattern=pattern, rrr=rrr,
        entry_price=entry_price, stop_loss=stop_loss, target=target,
        mwa_direction=mwa_direction, scanner_count=scanner_count,
        tv_confirmed=tv_confirmed, sector_strength=sector_strength,
        fii_net=fii_net, delivery_pct=delivery_pct,
        confidence_boosts=confidence_boosts, pre_confidence=pre_confidence,
    )
    result["method"] = "single_pass"
    result["similar_trades"] = similar_trades
    return result
