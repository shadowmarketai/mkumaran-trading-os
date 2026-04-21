"""
Signal Postmortem / RCA Engine

When a signal closes (WIN / LOSS), this module:

  1. Pulls the Signal + Outcome + entry feature snapshot
  2. Runs a battery of rule-based checks to find what went wrong (or right)
  3. Pulls top-K similar historical signals via vector similarity
  4. Optionally asks Claude Haiku for a human-readable narrative
  5. Persists a Postmortem row + updates Signal.rca_json

Pure Python, no heavy deps. Claude narrative is an optional enrichment —
if ANTHROPIC_API_KEY is not set, we fall back to a deterministic template.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime
from typing import Any

from mcp_server.db import SessionLocal
from mcp_server.models import Outcome, Postmortem, Signal

logger = logging.getLogger(__name__)


# ── Rule-based diagnostic checks ────────────────────────────────────────────
#
# Each check returns (name, passed, detail). `passed=False` is a red flag
# that contributed to the loss. The engine aggregates all failing checks into
# the root-cause narrative.


def _check_regime_alignment(sig: Signal) -> tuple[str, bool, str]:
    """LONG in TRENDING_DOWN or SHORT in TRENDING_UP is a regime mismatch."""
    regime = (sig.entry_regime or "").upper()
    direction = (sig.direction or "").upper()

    if direction in ("LONG", "BUY") and regime == "TRENDING_DOWN":
        return ("regime_alignment", False, f"LONG taken in {regime} regime — counter-trend")
    if direction in ("SHORT", "SELL") and regime == "TRENDING_UP":
        return ("regime_alignment", False, f"SHORT taken in {regime} regime — counter-trend")
    if regime == "VOLATILE":
        return ("regime_alignment", False, "VOLATILE regime — high whipsaw risk")
    if regime == "RANGING":
        return ("regime_alignment", True, "RANGING regime — acceptable for mean-reversion")
    return ("regime_alignment", True, f"Regime {regime} aligns with {direction}")


def _check_rsi_extreme(sig: Signal) -> tuple[str, bool, str]:
    """RSI > 75 on LONG or RSI < 25 on SHORT = chasing extremes."""
    rsi = float(sig.entry_rsi or 50)
    direction = (sig.direction or "").upper()

    if direction in ("LONG", "BUY") and rsi > 75:
        return ("rsi_extreme", False, f"RSI {rsi:.1f} > 75 on LONG — overbought chase")
    if direction in ("SHORT", "SELL") and rsi < 25:
        return ("rsi_extreme", False, f"RSI {rsi:.1f} < 25 on SHORT — oversold chase")
    if direction in ("LONG", "BUY") and rsi < 30:
        return ("rsi_extreme", True, f"RSI {rsi:.1f} on LONG — buying dip, OK")
    if direction in ("SHORT", "SELL") and rsi > 70:
        return ("rsi_extreme", True, f"RSI {rsi:.1f} on SHORT — shorting rally, OK")
    return ("rsi_extreme", True, f"RSI {rsi:.1f} neutral")


def _check_weak_trend(sig: Signal) -> tuple[str, bool, str]:
    """ADX < 15 = no trend strength, high whipsaw risk."""
    adx = float(sig.entry_adx or 20)
    if adx < 15:
        return ("weak_trend", False, f"ADX {adx:.1f} < 15 — no trend, likely chop")
    if adx < 20:
        return ("weak_trend", True, f"ADX {adx:.1f} marginal")
    return ("weak_trend", True, f"ADX {adx:.1f} — trend strength OK")


def _check_low_volume(sig: Signal) -> tuple[str, bool, str]:
    """Volume ratio < 0.7 = thin participation, fragile move."""
    vol = float(sig.entry_volume_ratio or 1.0)
    if vol < 0.7:
        return ("low_volume", False, f"Volume {vol:.2f}x avg — thin participation")
    if vol < 1.0:
        return ("low_volume", True, f"Volume {vol:.2f}x — below average but acceptable")
    return ("low_volume", True, f"Volume {vol:.2f}x — strong participation")


def _check_overextended(sig: Signal) -> tuple[str, bool, str]:
    """Momentum > 10% or < -10% in 5 days = overextended, likely mean-revert."""
    mom = float(sig.entry_momentum or 0)
    direction = (sig.direction or "").upper()

    if direction in ("LONG", "BUY") and mom > 10:
        return ("overextended", False, f"5d momentum {mom:+.1f}% — extended, reversion risk")
    if direction in ("SHORT", "SELL") and mom < -10:
        return ("overextended", False, f"5d momentum {mom:+.1f}% — extended, reversion risk")
    return ("overextended", True, f"5d momentum {mom:+.1f}% — acceptable")


def _check_wide_bb(sig: Signal) -> tuple[str, bool, str]:
    """BB width > 10% = high vol, SL likely gets hit on normal noise."""
    bbw = float(sig.entry_bb_width or 2.0)
    if bbw > 10:
        return ("wide_bb", False, f"BB width {bbw:.1f}% — very high vol, tight SL fragile")
    if bbw > 6:
        return ("wide_bb", True, f"BB width {bbw:.1f}% — elevated vol")
    return ("wide_bb", True, f"BB width {bbw:.1f}% — normal")


def _check_mwa_alignment(sig: Signal) -> tuple[str, bool, str]:
    """LONG with bear_pct > bull_pct OR SHORT with bull_pct > bear_pct = market fighting."""
    bull = float(sig.entry_mwa_bull_pct or 0)
    bear = float(sig.entry_mwa_bear_pct or 0)
    direction = (sig.direction or "").upper()

    if direction in ("LONG", "BUY") and bear > bull + 10:
        return (
            "mwa_alignment",
            False,
            f"LONG against MWA bear {bear:.0f}% > bull {bull:.0f}% — fighting market",
        )
    if direction in ("SHORT", "SELL") and bull > bear + 10:
        return (
            "mwa_alignment",
            False,
            f"SHORT against MWA bull {bull:.0f}% > bear {bear:.0f}% — fighting market",
        )
    return ("mwa_alignment", True, f"MWA bull={bull:.0f}% bear={bear:.0f}% — aligned")


def _check_single_scanner(sig: Signal) -> tuple[str, bool, str]:
    """Only 1 scanner flagging = thin confluence."""
    count = int(sig.scanner_count or 0)
    if count <= 1:
        return ("confluence", False, f"Only {count} scanner flagged — thin confluence")
    if count <= 2:
        return ("confluence", True, f"{count} scanners — moderate confluence")
    return ("confluence", True, f"{count} scanners — strong confluence")


RULE_CHECKS = [
    _check_regime_alignment,
    _check_rsi_extreme,
    _check_weak_trend,
    _check_low_volume,
    _check_overextended,
    _check_wide_bb,
    _check_mwa_alignment,
    _check_single_scanner,
]


def run_rule_checks(sig: Signal) -> list[dict[str, Any]]:
    """Execute all rules and return a list of dicts: {name, passed, detail}."""
    out: list[dict[str, Any]] = []
    for fn in RULE_CHECKS:
        try:
            name, passed, detail = fn(sig)
            out.append({"name": name, "passed": bool(passed), "detail": detail})
        except Exception as e:
            logger.debug("Rule %s crashed: %s", fn.__name__, e)
            out.append({"name": fn.__name__, "passed": True, "detail": f"skipped: {e}"})
    return out


def _failing(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [c for c in checks if not c.get("passed")]


# ── Root cause synthesis ────────────────────────────────────────────────────


def _synthesize_root_cause(
    sig: Signal,
    outcome: Outcome,
    checks: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    """
    Produce a (root_cause, contributing_factors) pair from the rule results.
    Priority order: regime > mwa > rsi/momentum > trend/volume > bb > confluence.
    """
    fail = {c["name"]: c["detail"] for c in _failing(checks)}
    factors: list[str] = [d for d in fail.values()]

    priority = [
        "regime_alignment",
        "mwa_alignment",
        "rsi_extreme",
        "overextended",
        "weak_trend",
        "low_volume",
        "wide_bb",
        "confluence",
    ]

    primary = None
    for name in priority:
        if name in fail:
            primary = fail[name]
            break

    outcome_str = (outcome.outcome or "LOSS").upper()
    if primary:
        root = f"{outcome_str}: {primary}"
    elif outcome_str == "WIN":
        root = "WIN: All rule checks passed — clean setup."
    else:
        root = "LOSS: No rule violations — loss likely random noise or exogenous event."

    return root, factors


def _suggest_filter(checks: list[dict[str, Any]]) -> str | None:
    """
    Translate failing rules into a concrete filter suggestion.
    Returns None if nothing actionable.
    """
    fail_names = {c["name"] for c in _failing(checks)}
    if not fail_names:
        return None

    suggestions = []
    if "regime_alignment" in fail_names:
        suggestions.append("Block counter-trend signals when regime is TRENDING_UP/DOWN")
    if "mwa_alignment" in fail_names:
        suggestions.append("Block signals fighting MWA bull/bear dominance > 10pp")
    if "rsi_extreme" in fail_names:
        suggestions.append("Block LONG when RSI > 75 or SHORT when RSI < 25")
    if "weak_trend" in fail_names:
        suggestions.append("Require ADX >= 15 for trend-following signals")
    if "low_volume" in fail_names:
        suggestions.append("Require volume_ratio >= 0.7 on entry")
    if "overextended" in fail_names:
        suggestions.append("Block signals when 5d momentum > 10% in direction of trade")
    if "wide_bb" in fail_names:
        suggestions.append("Skip signals when BB width > 10% — tight SL too fragile")
    if "confluence" in fail_names:
        suggestions.append("Require at least 2 scanners flagging the same ticker")

    return " | ".join(suggestions[:3])


# ── Claude narrative (optional) ────────────────────────────────────────────


def _try_claude_narrative(
    sig: Signal,
    outcome: Outcome,
    checks: list[dict[str, Any]],
    similar: list[dict[str, Any]],
) -> str | None:
    """
    Ask Claude Haiku to explain why the signal won/lost.
    Returns None if ANTHROPIC_API_KEY is missing or SDK unavailable.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None
    try:
        from mcp_server.ai_provider import call_ai
    except Exception:
        return None

    try:
        # AI provider handles client internally

        summary = {
            "ticker": sig.ticker,
            "direction": sig.direction,
            "entry": float(sig.entry_price or 0),
            "stop_loss": float(sig.stop_loss or 0),
            "target": float(sig.target or 0),
            "outcome": outcome.outcome,
            "exit_price": float(outcome.exit_price or 0),
            "pnl": float(outcome.pnl_amount or 0),
            "days_held": outcome.days_held,
            "entry_context": {
                "rsi": float(sig.entry_rsi or 0),
                "adx": float(sig.entry_adx or 0),
                "atr_pct": float(sig.entry_atr_pct or 0),
                "volume_ratio": float(sig.entry_volume_ratio or 0),
                "regime": sig.entry_regime,
                "mwa_bull_pct": float(sig.entry_mwa_bull_pct or 0),
                "mwa_bear_pct": float(sig.entry_mwa_bear_pct or 0),
                "scanners_fired": sig.scanner_count,
                "scanner_list": list(sig.scanner_list or [])[:10],
            },
            "failing_rules": [c for c in checks if not c["passed"]],
            "similar_past_trades": similar[:3],
        }

        prompt = (
            "You are a quant trading RCA assistant. Given a closed signal and its entry context, "
            "produce a 2-3 sentence explanation of WHY it worked or failed. Be specific, data-driven, "
            "and actionable. Do NOT hedge. No preamble — just the explanation.\n\n"
            f"Signal:\n{json.dumps(summary, default=str, indent=2)}"
        )

        text = call_ai(prompt, max_tokens=300, temperature=0.2)
        return text.strip() if text else None
    except Exception as e:
        logger.debug("Claude narrative unavailable: %s", e)
        return None


# ── Main entry point ───────────────────────────────────────────────────────


def run_postmortem(signal_id: int) -> dict[str, Any]:
    """
    Full postmortem pipeline for a single closed signal.
    Idempotent — if a postmortem row already exists, updates it in place.
    """
    session = SessionLocal()
    try:
        sig = session.query(Signal).filter(Signal.id == signal_id).first()
        if not sig:
            return {"status": "error", "reason": f"signal {signal_id} not found"}

        outcome = session.query(Outcome).filter(Outcome.signal_id == signal_id).first()
        if not outcome:
            return {"status": "skipped", "reason": "no outcome yet (still open)"}

        # 1) Rule checks
        checks = run_rule_checks(sig)

        # 2) Similar past trades (best-effort)
        similar: list[dict[str, Any]] = []
        try:
            from mcp_server.signal_similarity import find_similar_signals
            similar = find_similar_signals(sig, session, top_k=5, exclude_id=sig.id)
        except Exception as e:
            logger.debug("Similarity lookup skipped: %s", e)

        # 3) Synthesize root cause
        root_cause, factors = _synthesize_root_cause(sig, outcome, checks)
        suggested = _suggest_filter(checks)

        # 4) Confidence score = fraction of checks that yielded a clear signal
        total = max(1, len(checks))
        failing = len(_failing(checks))
        # If outcome is LOSS and we found failing rules, confidence is high that we identified the cause
        if outcome.outcome == "LOSS" and failing > 0:
            confidence = min(99.0, 50.0 + (failing / total) * 50.0)
        elif outcome.outcome == "WIN" and failing == 0:
            confidence = 90.0
        else:
            confidence = 50.0

        # 5) Claude narrative (optional)
        narrative = _try_claude_narrative(sig, outcome, checks, similar)

        # 6) Persist postmortem (upsert)
        existing = (
            session.query(Postmortem)
            .filter(Postmortem.signal_id == signal_id)
            .first()
        )
        if existing:
            existing.outcome = outcome.outcome
            existing.root_cause = root_cause
            existing.contributing_factors = factors
            existing.rule_checks = checks
            existing.suggested_filter = suggested
            existing.similar_signals = similar
            existing.claude_narrative = narrative
            existing.confidence_score = round(confidence, 1)
            pm = existing
        else:
            pm = Postmortem(
                signal_id=signal_id,
                outcome=outcome.outcome,
                root_cause=root_cause,
                contributing_factors=factors,
                rule_checks=checks,
                suggested_filter=suggested,
                similar_signals=similar,
                claude_narrative=narrative,
                confidence_score=round(confidence, 1),
            )
            session.add(pm)

        # 7) Mirror a compact version into Signal.rca_json for quick queries
        try:
            sig.rca_json = {
                "outcome": outcome.outcome,
                "root_cause": root_cause,
                "factors": factors,
                "suggested_filter": suggested,
                "confidence": round(confidence, 1),
                "analyzed_at": datetime.utcnow().isoformat(),
            }
        except Exception:
            pass

        session.commit()

        return {
            "status": "ok",
            "signal_id": signal_id,
            "ticker": sig.ticker,
            "outcome": outcome.outcome,
            "root_cause": root_cause,
            "factors": factors,
            "checks": checks,
            "suggested_filter": suggested,
            "similar_count": len(similar),
            "confidence": round(confidence, 1),
            "narrative": narrative,
        }

    except Exception as e:
        session.rollback()
        logger.error("Postmortem failed for signal %s: %s", signal_id, e)
        return {"status": "error", "reason": str(e)}
    finally:
        session.close()


def run_batch_postmortems(lookback_days: int = 7) -> dict[str, Any]:
    """
    Run postmortems for all closed signals in the last N days that don't
    already have one. Idempotent and safe to call repeatedly.
    """
    from datetime import timedelta

    session = SessionLocal()
    processed = 0
    errors = 0
    try:
        cutoff = date.today() - timedelta(days=lookback_days)
        outs = (
            session.query(Outcome)
            .filter(Outcome.exit_date >= cutoff)
            .all()
        )
        signal_ids = [o.signal_id for o in outs]
    finally:
        session.close()

    # Limit batch to 10 per run to avoid API timeout. The self-dev loop
    # runs daily so it catches up over time. Most important: process
    # the MOST RECENT closures first (they're freshest for learning).
    max_batch = 10
    for sid in signal_ids[-max_batch:]:
        try:
            res = run_postmortem(sid)
            if res.get("status") == "ok":
                processed += 1
        except Exception as e:
            logger.warning("Batch postmortem error for signal %s: %s", sid, e)
            errors += 1

    return {
        "status": "ok",
        "processed": processed,
        "errors": errors,
        "total_candidates": len(signal_ids),
    }
