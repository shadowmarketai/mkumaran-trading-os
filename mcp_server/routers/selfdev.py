"""Self-development system — postmortem + predictor + rules + reflection.

Extracted from mcp_server.mcp_server in Phase 2c of the router split.
17 routes moved verbatim.

Clusters:
  - Overall status / on-demand postmortems
  - ML loss-predictor (block threshold gate)
  - Bayesian scanner stats + underperformer list
  - Adaptive rules engine (mining + manual activate/deactivate)
  - Similarity lookup for a given signal
  - Trade-reflection batch runner + memory stats

The `_run_self_dev_pipeline_sync` helper stays in mcp_server.py
(used by both the lifespan scheduled task and /tools/run_self_development).
"""
import asyncio
import logging

from fastapi import APIRouter, Query
from pydantic import BaseModel

from mcp_server.config import settings
from mcp_server.db import SessionLocal
from mcp_server.models import AdaptiveRule, Postmortem, Signal

logger = logging.getLogger(__name__)

router = APIRouter(tags=["selfdev"])


# ── Request models ─────────────────────────────────────────────────


class ReflectTradesRequest(BaseModel):
    limit: int = 10


class ReflectSingleRequest(BaseModel):
    signal_id: str


# ── Status ─────────────────────────────────────────────────────────


@router.get("/api/selfdev/status")
async def api_selfdev_status():
    """Overall health + state of the self-development system."""
    from mcp_server.scanner_bayesian import get_all_stats
    from mcp_server.signal_predictor import get_predictor
    from mcp_server.signal_similarity import similarity_stats

    session = SessionLocal()
    try:
        postmortem_count = session.query(Postmortem).count()
        rule_count = session.query(AdaptiveRule).count()
        active_rules = session.query(AdaptiveRule).filter(AdaptiveRule.active.is_(True)).count()
        signals_with_features = (
            session.query(Signal).filter(Signal.feature_vector.isnot(None)).count()
        )
        suppressed = session.query(Signal).filter(Signal.suppressed.is_(True)).count()
        sim_stats = similarity_stats(session)
    finally:
        session.close()

    predictor = get_predictor()
    bayes = get_all_stats()

    return {
        "enabled": settings.SELF_DEV_ENABLED,
        "predictor": predictor.meta(),
        "predictor_block_threshold": settings.PREDICTOR_BLOCK_THRESHOLD,
        "rules": {"total": rule_count, "active": active_rules},
        "postmortems": postmortem_count,
        "signals_with_features": signals_with_features,
        "signals_suppressed": suppressed,
        "similarity": sim_stats,
        "bayesian": {
            "scanners_tracked": len((bayes.get("scanners") or {})),
            "updated_at": bayes.get("updated_at"),
        },
    }


@router.post("/tools/run_self_development")
async def tool_run_self_development():
    """Manual trigger for the full self-development pipeline (n8n compatible)."""
    from mcp_server import mcp_server as _ms

    result = await asyncio.to_thread(_ms._run_self_dev_pipeline_sync)
    return result


# ── Postmortem ────────────────────────────────────────────────────


@router.get("/api/selfdev/postmortem/{signal_id}")
async def api_selfdev_postmortem(signal_id: int):
    """Return the postmortem for a specific signal, running it on-demand if missing."""
    session = SessionLocal()
    try:
        pm = session.query(Postmortem).filter(Postmortem.signal_id == signal_id).first()
        if not pm:
            from mcp_server.signal_postmortem import run_postmortem
            result = run_postmortem(signal_id)
            if result.get("status") != "ok":
                return result
            pm = session.query(Postmortem).filter(Postmortem.signal_id == signal_id).first()

        if not pm:
            return {"status": "error", "reason": "postmortem not available"}

        return {
            "status": "ok",
            "signal_id": signal_id,
            "outcome": pm.outcome,
            "root_cause": pm.root_cause,
            "contributing_factors": pm.contributing_factors,
            "rule_checks": pm.rule_checks,
            "suggested_filter": pm.suggested_filter,
            "similar_signals": pm.similar_signals,
            "claude_narrative": pm.claude_narrative,
            "confidence_score": float(pm.confidence_score or 0),
            "created_at": pm.created_at.isoformat() if pm.created_at else None,
        }
    finally:
        session.close()


@router.post("/tools/run_postmortems")
async def tool_run_postmortems(lookback_days: int = Query(default=14, ge=1, le=180)):
    """Batch postmortem for recently-closed signals (n8n compatible)."""
    from mcp_server.signal_postmortem import run_batch_postmortems
    return await asyncio.to_thread(run_batch_postmortems, lookback_days)


# ── Predictor ──────────────────────────────────────────────────────


@router.post("/tools/retrain_predictor")
async def tool_retrain_predictor():
    """Manually retrain the loss predictor (n8n compatible)."""
    from mcp_server.signal_predictor import retrain_predictor
    return await asyncio.to_thread(retrain_predictor)


@router.get("/api/selfdev/predictor")
async def api_selfdev_predictor():
    """Return current predictor metadata + configured block threshold."""
    from mcp_server.signal_predictor import get_predictor
    predictor = get_predictor()
    return {
        **predictor.meta(),
        "block_threshold": settings.PREDICTOR_BLOCK_THRESHOLD,
    }


# ── Bayesian scanner stats ─────────────────────────────────────────


@router.get("/api/selfdev/bayesian")
async def api_selfdev_bayesian():
    """Return the full Bayesian scanner stats JSON."""
    from mcp_server.scanner_bayesian import get_all_stats
    return get_all_stats()


@router.get("/api/selfdev/bayesian/underperforming")
async def api_selfdev_bayesian_under():
    """Return scanners whose 90% credible interval upper bound falls below the retirement threshold."""
    from mcp_server.scanner_bayesian import get_underperforming_scanners
    return {"scanners": get_underperforming_scanners()}


@router.post("/tools/update_bayesian_stats")
async def tool_update_bayesian_stats():
    """Recompute Bayesian posteriors from current DB state."""
    from mcp_server.scanner_bayesian import update_bayesian_stats
    return await asyncio.to_thread(update_bayesian_stats)


# ── Adaptive rules engine ──────────────────────────────────────────


@router.get("/api/selfdev/rules")
async def api_selfdev_rules():
    """List all mined adaptive rules (active and inactive)."""
    from mcp_server.rules_engine import list_active_rules
    return {"rules": list_active_rules()}


@router.post("/tools/mine_rules")
async def tool_mine_rules(dry_run: bool = Query(default=True)):
    """Run the rule mining pipeline. Default dry_run=True (rules inactive by default)."""
    from mcp_server.rules_engine import mine_rules
    result = await asyncio.to_thread(mine_rules, dry_run)
    # Strip verbose evaluated list from the API response
    if isinstance(result, dict) and "evaluated" in result:
        result = {k: v for k, v in result.items() if k != "evaluated"}
    return result


@router.post("/api/selfdev/rules/{rule_key}/activate")
async def api_selfdev_activate_rule(rule_key: str):
    """Manually activate a mined rule."""
    from mcp_server.rules_engine import set_rule_active
    return set_rule_active(rule_key, True)


@router.post("/api/selfdev/rules/{rule_key}/deactivate")
async def api_selfdev_deactivate_rule(rule_key: str):
    """Manually deactivate a rule."""
    from mcp_server.rules_engine import set_rule_active
    return set_rule_active(rule_key, False)


# ── Similarity ─────────────────────────────────────────────────────


@router.get("/api/selfdev/similar/{signal_id}")
async def api_selfdev_similar(signal_id: int, top_k: int = Query(default=5, ge=1, le=20)):
    """Return the top-K historical signals most similar to a given signal."""
    from mcp_server.signal_similarity import find_similar_signals
    session = SessionLocal()
    try:
        sig = session.query(Signal).filter(Signal.id == signal_id).first()
        if not sig:
            return {"status": "error", "reason": f"signal {signal_id} not found"}
        similar = find_similar_signals(sig, session, top_k=top_k, exclude_id=signal_id)
        return {
            "status": "ok",
            "signal_id": signal_id,
            "ticker": sig.ticker,
            "similar": similar,
        }
    finally:
        session.close()


# ── Trade reflection / memory ──────────────────────────────────────


@router.post("/tools/reflect_trades")
async def tool_reflect_trades(req: ReflectTradesRequest):
    """Batch reflection on unreflected closed trades (called by n8n EOD)."""
    from mcp_server.trade_memory import TradeMemory
    from mcp_server.trade_reflector import TradeReflector
    memory = TradeMemory(filepath=settings.TRADE_MEMORY_FILE)
    reflector = TradeReflector(memory)
    return reflector.reflect_batch(limit=req.limit)


@router.post("/tools/reflect_single")
async def tool_reflect_single(req: ReflectSingleRequest):
    """Reflect on a specific closed trade."""
    from mcp_server.trade_memory import TradeMemory
    from mcp_server.trade_reflector import TradeReflector
    memory = TradeMemory(filepath=settings.TRADE_MEMORY_FILE)
    reflector = TradeReflector(memory)
    return reflector.reflect_on_trade(req.signal_id)


@router.get("/tools/trade_memory_stats")
async def tool_trade_memory_stats():
    """Get trade memory + reflection statistics."""
    from mcp_server.trade_memory import TradeMemory
    from mcp_server.trade_reflector import TradeReflector
    memory = TradeMemory(filepath=settings.TRADE_MEMORY_FILE)
    reflector = TradeReflector(memory)
    return {
        "memory": memory.get_stats(),
        "reflection": reflector.get_reflection_stats(),
    }
