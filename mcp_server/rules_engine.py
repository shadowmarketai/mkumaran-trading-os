"""
Adaptive Rules Learning Engine

Mines AdaptiveRule candidates from historical Signal + Outcome data,
back-tests each against the historical record, and persists the winning
rules to the `adaptive_rules` table.

Each rule is a simple condition on one of the entry-time features. We
enumerate candidates across indicators × thresholds × directions × regimes
and score each by:

    hit_rate_before = wins / (wins + losses) over ALL signals
    hit_rate_after  = wins / (wins + losses) after removing signals the rule
                      would have blocked

A rule is promoted to "active" when all of the following hold:

    sample_size  >= MIN_SAMPLE
    hit_rate_after  > hit_rate_before + MIN_LIFT
    wins_lost    / losses_prevented  < MAX_COLLATERAL

Rules can be applied at entry time via `apply_active_rules(features)` —
returns a list of rule hits and an overall block/reduce recommendation.

Pure Python, numpy-only. No heavy deps.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable

from mcp_server.db import SessionLocal
from mcp_server.models import AdaptiveRule, Outcome, Signal

logger = logging.getLogger(__name__)


# ── Tunables ────────────────────────────────────────────────────────────────

MIN_SAMPLE = 20            # require at least 20 closed signals to fit rule
MIN_LIFT = 0.05            # 5 percentage-point improvement in hit rate
MAX_COLLATERAL = 0.5       # for every 2 losses prevented, at most 1 win lost
DRY_RUN_DEFAULT = True     # newly-discovered rules are inactive by default


# ── Candidate rule generators ───────────────────────────────────────────────
#
# Each generator yields (rule_key, description, condition_fn, suggested_action)
# where condition_fn takes a Signal and returns True if the rule FIRES (meaning
# we would block / penalize that signal).


def _ge(val: Any, thr: float) -> bool:
    try:
        return val is not None and float(val) >= thr
    except Exception:
        return False


def _le(val: Any, thr: float) -> bool:
    try:
        return val is not None and float(val) <= thr
    except Exception:
        return False


def _candidate_rules() -> list[dict[str, Any]]:
    """Enumerate all candidate rules we want to back-test."""
    cands: list[dict[str, Any]] = []

    # RSI extremes by direction
    for thr in (70, 75, 80):
        cands.append({
            "key": f"block_long_when_rsi_ge_{thr}",
            "description": f"Block LONG signals when entry_rsi >= {thr}",
            "condition": {"field": "entry_rsi", "op": "ge", "value": thr, "direction": "LONG"},
            "predicate": (lambda sig, t=thr: (sig.direction or "").upper() in ("LONG", "BUY") and _ge(sig.entry_rsi, t)),
            "action": "block",
        })
    for thr in (20, 25, 30):
        cands.append({
            "key": f"block_short_when_rsi_le_{thr}",
            "description": f"Block SHORT signals when entry_rsi <= {thr}",
            "condition": {"field": "entry_rsi", "op": "le", "value": thr, "direction": "SHORT"},
            "predicate": (lambda sig, t=thr: (sig.direction or "").upper() in ("SHORT", "SELL") and _le(sig.entry_rsi, t)),
            "action": "block",
        })

    # Weak trend (ADX)
    for thr in (12, 15, 18):
        cands.append({
            "key": f"block_when_adx_lt_{thr}",
            "description": f"Block all signals when entry_adx < {thr}",
            "condition": {"field": "entry_adx", "op": "lt", "value": thr},
            "predicate": (lambda sig, t=thr: _le(sig.entry_adx, t - 0.001)),
            "action": "block",
        })

    # Low volume
    for thr in (0.5, 0.7):
        cands.append({
            "key": f"block_when_vol_lt_{int(thr*100)}pct",
            "description": f"Block when entry_volume_ratio < {thr}",
            "condition": {"field": "entry_volume_ratio", "op": "lt", "value": thr},
            "predicate": (lambda sig, t=thr: _le(sig.entry_volume_ratio, t - 1e-6)),
            "action": "block",
        })

    # Overextended momentum
    for thr in (8, 10, 12):
        cands.append({
            "key": f"block_long_when_mom5d_ge_{thr}",
            "description": f"Block LONG when 5d momentum >= {thr}%",
            "condition": {"field": "entry_momentum", "op": "ge", "value": thr, "direction": "LONG"},
            "predicate": (lambda sig, t=thr: (sig.direction or "").upper() in ("LONG", "BUY") and _ge(sig.entry_momentum, t)),
            "action": "block",
        })
        cands.append({
            "key": f"block_short_when_mom5d_le_{-thr}",
            "description": f"Block SHORT when 5d momentum <= {-thr}%",
            "condition": {"field": "entry_momentum", "op": "le", "value": -thr, "direction": "SHORT"},
            "predicate": (lambda sig, t=thr: (sig.direction or "").upper() in ("SHORT", "SELL") and _le(sig.entry_momentum, -t)),
            "action": "block",
        })

    # Regime mismatch
    cands.append({
        "key": "block_long_in_trending_down",
        "description": "Block LONG signals in TRENDING_DOWN regime",
        "condition": {"field": "entry_regime", "op": "eq", "value": "TRENDING_DOWN", "direction": "LONG"},
        "predicate": (lambda sig: (sig.direction or "").upper() in ("LONG", "BUY") and (sig.entry_regime or "") == "TRENDING_DOWN"),
        "action": "block",
    })
    cands.append({
        "key": "block_short_in_trending_up",
        "description": "Block SHORT signals in TRENDING_UP regime",
        "condition": {"field": "entry_regime", "op": "eq", "value": "TRENDING_UP", "direction": "SHORT"},
        "predicate": (lambda sig: (sig.direction or "").upper() in ("SHORT", "SELL") and (sig.entry_regime or "") == "TRENDING_UP"),
        "action": "block",
    })

    # MWA fighting
    cands.append({
        "key": "block_long_when_bear_dominant",
        "description": "Block LONG when mwa_bear_pct - mwa_bull_pct >= 15",
        "condition": {"field": "mwa_bear_minus_bull", "op": "ge", "value": 15, "direction": "LONG"},
        "predicate": (lambda sig: (
            (sig.direction or "").upper() in ("LONG", "BUY")
            and sig.entry_mwa_bear_pct is not None
            and sig.entry_mwa_bull_pct is not None
            and float(sig.entry_mwa_bear_pct) - float(sig.entry_mwa_bull_pct) >= 15
        )),
        "action": "block",
    })
    cands.append({
        "key": "block_short_when_bull_dominant",
        "description": "Block SHORT when mwa_bull_pct - mwa_bear_pct >= 15",
        "condition": {"field": "mwa_bull_minus_bear", "op": "ge", "value": 15, "direction": "SHORT"},
        "predicate": (lambda sig: (
            (sig.direction or "").upper() in ("SHORT", "SELL")
            and sig.entry_mwa_bull_pct is not None
            and sig.entry_mwa_bear_pct is not None
            and float(sig.entry_mwa_bull_pct) - float(sig.entry_mwa_bear_pct) >= 15
        )),
        "action": "block",
    })

    # Wide BB (SL too fragile)
    cands.append({
        "key": "block_when_bb_width_ge_10",
        "description": "Block signals when entry_bb_width >= 10%",
        "condition": {"field": "entry_bb_width", "op": "ge", "value": 10},
        "predicate": (lambda sig: _ge(sig.entry_bb_width, 10)),
        "action": "block",
    })

    # Single-scanner confluence
    cands.append({
        "key": "block_when_scanner_count_le_1",
        "description": "Block signals with only 1 scanner firing",
        "condition": {"field": "scanner_count", "op": "le", "value": 1},
        "predicate": (lambda sig: _le(sig.scanner_count, 1)),
        "action": "block",
    })

    return cands


# ── Back-test engine ────────────────────────────────────────────────────────


def _backtest_rule(
    predicate: Callable[[Any], bool],
    labeled: list[tuple[Signal, Outcome]],
) -> dict[str, Any]:
    """
    Score a rule against the historical labeled set.

    Returns a dict with hit_rate_before/after + wins_lost + losses_prevented.
    """
    if not labeled:
        return {
            "sample_size": 0,
            "hit_rate_before": 0.0,
            "hit_rate_after": 0.0,
            "wins_lost": 0,
            "losses_prevented": 0,
            "lift": 0.0,
        }

    wins_total = 0
    losses_total = 0
    wins_blocked = 0
    losses_blocked = 0
    fired_samples = 0

    for sig, out in labeled:
        label = (out.outcome or "").upper()
        is_win = label == "WIN"
        is_loss = label == "LOSS"

        if is_win:
            wins_total += 1
        elif is_loss:
            losses_total += 1

        try:
            fires = bool(predicate(sig))
        except Exception:
            fires = False

        if fires:
            fired_samples += 1
            if is_win:
                wins_blocked += 1
            elif is_loss:
                losses_blocked += 1

    total = wins_total + losses_total
    hr_before = wins_total / total if total else 0.0

    wins_after = wins_total - wins_blocked
    losses_after = losses_total - losses_blocked
    total_after = wins_after + losses_after
    hr_after = (wins_after / total_after) if total_after else 0.0

    return {
        "sample_size": fired_samples,
        "total_signals": total,
        "hit_rate_before": round(hr_before, 4),
        "hit_rate_after": round(hr_after, 4),
        "wins_lost": wins_blocked,
        "losses_prevented": losses_blocked,
        "lift": round(hr_after - hr_before, 4),
    }


def _load_labeled() -> list[tuple[Signal, Outcome]]:
    session = SessionLocal()
    try:
        rows = (
            session.query(Signal, Outcome)
            .join(Outcome, Outcome.signal_id == Signal.id)
            .all()
        )
        return rows
    finally:
        session.close()


def mine_rules(dry_run: bool | None = None) -> dict[str, Any]:
    """
    Enumerate candidates, back-test each, persist the ones that beat the
    thresholds. If `dry_run` is True (default), new rules are persisted with
    `active=False` so an operator can review before they start firing.
    """
    if dry_run is None:
        dry_run = DRY_RUN_DEFAULT

    labeled = _load_labeled()
    if len(labeled) < MIN_SAMPLE:
        return {
            "status": "insufficient_data",
            "total_labeled": len(labeled),
            "required": MIN_SAMPLE,
        }

    candidates = _candidate_rules()
    promoted: list[dict[str, Any]] = []
    evaluated: list[dict[str, Any]] = []

    session = SessionLocal()
    try:
        for cand in candidates:
            bt = _backtest_rule(cand["predicate"], labeled)
            evaluated.append({"key": cand["key"], **bt})

            # Promotion gate
            if bt["sample_size"] < MIN_SAMPLE:
                continue
            if bt["lift"] < MIN_LIFT:
                continue
            collateral = (bt["wins_lost"] / bt["losses_prevented"]) if bt["losses_prevented"] else 1.0
            if collateral > MAX_COLLATERAL:
                continue

            existing = (
                session.query(AdaptiveRule)
                .filter(AdaptiveRule.rule_key == cand["key"])
                .first()
            )
            if existing:
                existing.description = cand["description"]
                existing.condition_json = cand["condition"]
                existing.action = cand["action"]
                existing.sample_size = bt["sample_size"]
                existing.historical_hit_rate_before = round(bt["hit_rate_before"] * 100, 2)
                existing.historical_hit_rate_after = round(bt["hit_rate_after"] * 100, 2)
                existing.estimated_losses_prevented = bt["losses_prevented"]
                existing.estimated_wins_lost = bt["wins_lost"]
                existing.auto_generated = True
                rec = existing
            else:
                rec = AdaptiveRule(
                    rule_key=cand["key"],
                    description=cand["description"],
                    condition_json=cand["condition"],
                    action=cand["action"],
                    action_params={},
                    sample_size=bt["sample_size"],
                    historical_hit_rate_before=round(bt["hit_rate_before"] * 100, 2),
                    historical_hit_rate_after=round(bt["hit_rate_after"] * 100, 2),
                    estimated_losses_prevented=bt["losses_prevented"],
                    estimated_wins_lost=bt["wins_lost"],
                    active=not dry_run,
                    auto_generated=True,
                    activated_at=datetime.utcnow() if not dry_run else None,
                )
                session.add(rec)
            promoted.append({
                "key": cand["key"],
                "lift": bt["lift"],
                "losses_prevented": bt["losses_prevented"],
                "wins_lost": bt["wins_lost"],
                "sample": bt["sample_size"],
            })
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error("Rule mining failed: %s", e)
        return {"status": "error", "reason": str(e)}
    finally:
        session.close()

    return {
        "status": "ok",
        "dry_run": dry_run,
        "candidates": len(candidates),
        "evaluated": evaluated,
        "promoted": promoted,
        "total_labeled": len(labeled),
    }


# ── Entry-time rule application ─────────────────────────────────────────────


class _SignalShim:
    """Adapter so _candidate_rules() predicates work on a feature-dict."""

    def __init__(self, features: dict[str, Any]) -> None:
        self.direction = features.get("direction", "LONG")
        self.entry_rsi = features.get("rsi")
        self.entry_adx = features.get("adx")
        self.entry_atr_pct = features.get("atr_pct")
        self.entry_volume_ratio = features.get("volume_ratio")
        self.entry_momentum = features.get("momentum_5d")
        self.entry_bb_width = features.get("bb_width")
        self.entry_regime = features.get("regime")
        self.entry_mwa_bull_pct = features.get("mwa_bull_pct")
        self.entry_mwa_bear_pct = features.get("mwa_bear_pct")
        self.scanner_count = features.get("scanner_count")


def apply_active_rules(features: dict[str, Any]) -> dict[str, Any]:
    """
    Check all ACTIVE adaptive rules against a feature dict. Returns:

        {
          "fired": [ {key, action, description}, ... ],
          "block": bool,
          "confidence_penalty": int,
        }
    """
    session = SessionLocal()
    try:
        rules = (
            session.query(AdaptiveRule)
            .filter(AdaptiveRule.active.is_(True))
            .all()
        )
    finally:
        session.close()

    if not rules:
        return {"fired": [], "block": False, "confidence_penalty": 0}

    shim = _SignalShim(features)
    # We need to re-derive the predicate for each rule from its condition_json
    # so we can apply it even after restart. We do this by looking up the
    # candidate bank and matching by key (cheap — bank is ~30 rules).
    bank = {c["key"]: c for c in _candidate_rules()}

    fired: list[dict[str, Any]] = []
    block = False
    penalty = 0

    for rule in rules:
        cand = bank.get(rule.rule_key)
        if not cand:
            continue
        try:
            if cand["predicate"](shim):
                fired.append({
                    "key": rule.rule_key,
                    "action": rule.action,
                    "description": rule.description,
                })
                if rule.action == "block":
                    block = True
                elif rule.action == "reduce_confidence":
                    penalty += int((rule.action_params or {}).get("penalty", 10))
        except Exception as e:
            logger.debug("Rule %s apply failed: %s", rule.rule_key, e)

    return {"fired": fired, "block": block, "confidence_penalty": min(penalty, 40)}


def list_active_rules() -> list[dict[str, Any]]:
    session = SessionLocal()
    try:
        rules = (
            session.query(AdaptiveRule)
            .order_by(AdaptiveRule.historical_hit_rate_after.desc().nullslast())
            .all()
        )
        out = []
        for r in rules:
            out.append({
                "key": r.rule_key,
                "description": r.description,
                "action": r.action,
                "active": bool(r.active),
                "auto_generated": bool(r.auto_generated),
                "sample_size": r.sample_size,
                "hit_rate_before": float(r.historical_hit_rate_before or 0),
                "hit_rate_after": float(r.historical_hit_rate_after or 0),
                "losses_prevented": r.estimated_losses_prevented,
                "wins_lost": r.estimated_wins_lost,
                "fire_count": r.fire_count,
                "last_fired_at": r.last_fired_at.isoformat() if r.last_fired_at else None,
            })
        return out
    finally:
        session.close()


def set_rule_active(rule_key: str, active: bool) -> dict[str, Any]:
    """Manually activate or deactivate a rule by key."""
    session = SessionLocal()
    try:
        rule = session.query(AdaptiveRule).filter(AdaptiveRule.rule_key == rule_key).first()
        if not rule:
            return {"status": "not_found", "key": rule_key}
        rule.active = bool(active)
        if active and not rule.activated_at:
            rule.activated_at = datetime.utcnow()
        session.commit()
        return {"status": "ok", "key": rule_key, "active": rule.active}
    except Exception as e:
        session.rollback()
        return {"status": "error", "reason": str(e)}
    finally:
        session.close()
