"""
MKUMARAN Trading OS — Signal Validator (v2 — Fail-Safe)

Fixes over v1:
- API failure = BLOCK signal (not approve)
- Explicit API key validation
- validation_status field: VALIDATED / FAILED / SKIPPED / BLOCKED
- Timeout protection
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

    # ── Gate 3: Call Claude AI ────────────────────────────────
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)

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

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )

        # Parse response
        text = response.content[0].text.strip()

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
