"""
MKUMARAN Trading OS — Options Seller: Adjustment Engine

Evaluates an open strangle/condor position and recommends an action.
Called after each Greeks refresh cycle (every 5 min during market hours).

Five rules (from PR Sundar's framework)
────────────────────────────────────────
  Rule 1 — EVENT_PROXIMITY
    A high-impact event (RBI / FOMC / Budget / NFP / expiry) is within
    24h → close the full position to avoid event gamma risk.

  Rule 2 — STRIKE_IMMINENT
    The tested (threatened) strike is within 0.5% of spot → close
    just that leg; leave the other side open to collect remaining decay.

  Rule 3 — DELTA_BREACH
    The tested leg's absolute delta has crept above 0.30 (was sold at
    ~0.15) → roll that leg further OTM to reset delta exposure.

  Rule 4 — PREMIUM_DECAY_RELOAD
    The untested leg has decayed to < 10% of its entry premium AND there
    are ≥ 2 DTE remaining → roll the untested leg closer for more credit.

  Rule 5 — MAX_LOSS_BREACH
    Running P&L has exceeded −2× the original credit received → accept
    the loss and exit the full position.

  DEFAULT — HOLD (all conditions within parameters).

Each rule returns an AdjustmentAction enum value and a short reason
string that operators can log / send to Telegram.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class AdjustmentAction(Enum):
    HOLD               = "hold"
    CLOSE_ALL          = "close_full_position"
    CLOSE_TESTED_LEG   = "close_tested_leg_only"
    ROLL_TESTED        = "roll_tested_side_further_otm"
    ROLL_UNTESTED      = "roll_untested_side_closer"


@dataclass
class AdjustmentDecision:
    action: AdjustmentAction
    rule: str                  # "rule_1" … "rule_5" | "default"
    reason: str
    tested_leg: str = ""       # "CE" | "PE" — the leg under threat
    untested_leg: str = ""

    def as_dict(self) -> dict:
        return {
            "action":       self.action.value,
            "rule":         self.rule,
            "reason":       self.reason,
            "tested_leg":   self.tested_leg,
            "untested_leg": self.untested_leg,
        }


@dataclass
class LivePositionSnapshot:
    """Current state of one open strangle/condor, refreshed from live Greeks."""
    instrument: str
    spot: float

    short_call_strike: float
    short_put_strike: float
    short_call_delta: float    # current, NOT entry delta
    short_put_delta: float     # current, NOT entry delta (negative for PE)

    short_call_entry_premium: float
    short_put_entry_premium:  float
    short_call_current_premium: float
    short_put_current_premium:  float

    credit_received: float     # total premium at entry (both legs)
    current_pnl: float         # positive = profit, negative = loss

    dte_remaining: float       # calendar days to expiry


def _identify_tested(snap: LivePositionSnapshot) -> tuple[str, str]:
    """Return (tested_leg, untested_leg) based on which leg is closer to spot.

    The tested leg is the one whose strike is nearer to spot.
    """
    call_dist = abs(snap.spot - snap.short_call_strike)
    put_dist  = abs(snap.spot - snap.short_put_strike)
    if call_dist <= put_dist:
        return "CE", "PE"
    return "PE", "CE"


def _tested_delta(snap: LivePositionSnapshot, tested: str) -> float:
    """Return absolute delta of the tested leg."""
    if tested == "CE":
        return abs(snap.short_call_delta)
    return abs(snap.short_put_delta)


def _untested_current_premium(snap: LivePositionSnapshot, untested: str) -> float:
    if untested == "CE":
        return snap.short_call_current_premium
    return snap.short_put_current_premium


def _untested_entry_premium(snap: LivePositionSnapshot, untested: str) -> float:
    if untested == "CE":
        return snap.short_call_entry_premium
    return snap.short_put_entry_premium


def evaluate(
    snap: LivePositionSnapshot,
    delta_breach_threshold: float = 0.30,
    strike_imminent_pct: float = 0.005,
    premium_decay_threshold: float = 0.10,
    max_loss_multiple: float = 2.0,
    event_horizon_hours: float = 24.0,
) -> AdjustmentDecision:
    """Evaluate the position snapshot and return an AdjustmentDecision.

    All thresholds can be overridden per call so operators can A/B test
    tighter/looser rules without code changes.
    """
    tested, untested = _identify_tested(snap)

    # ── Rule 1: Event proximity ───────────────────────────────
    try:
        from mcp_server.event_calendar import get_calendar
        cal = get_calendar()
        if cal.high_impact_within(hours=event_horizon_hours):
            return AdjustmentDecision(
                action=AdjustmentAction.CLOSE_ALL,
                rule="rule_1",
                reason=f"High-impact event within {event_horizon_hours:.0f}h — exit to avoid gamma risk",
                tested_leg=tested,
                untested_leg=untested,
            )
    except Exception as e:
        logger.debug("Adjustment rule 1: event calendar unavailable — %s", e)

    # ── Rule 2: Strike imminent ───────────────────────────────
    if tested == "CE":
        distance_pct = (snap.short_call_strike - snap.spot) / snap.spot
    else:
        distance_pct = (snap.spot - snap.short_put_strike) / snap.spot

    if distance_pct < strike_imminent_pct:
        return AdjustmentDecision(
            action=AdjustmentAction.CLOSE_TESTED_LEG,
            rule="rule_2",
            reason=(
                f"{tested} strike {snap.short_call_strike if tested == 'CE' else snap.short_put_strike:.0f} "
                f"is {distance_pct:.2%} from spot — imminent breach"
            ),
            tested_leg=tested,
            untested_leg=untested,
        )

    # ── Rule 3: Delta breach ──────────────────────────────────
    tested_abs_delta = _tested_delta(snap, tested)
    if tested_abs_delta > delta_breach_threshold:
        return AdjustmentDecision(
            action=AdjustmentAction.ROLL_TESTED,
            rule="rule_3",
            reason=(
                f"{tested} delta {tested_abs_delta:.2f} > "
                f"breach threshold {delta_breach_threshold:.2f} — roll further OTM"
            ),
            tested_leg=tested,
            untested_leg=untested,
        )

    # ── Rule 4: Premium decay — reload untested side ──────────
    untested_current = _untested_current_premium(snap, untested)
    untested_entry   = _untested_entry_premium(snap, untested)
    if (
        untested_entry > 0
        and (untested_current / untested_entry) < premium_decay_threshold
        and snap.dte_remaining >= 2
    ):
        return AdjustmentDecision(
            action=AdjustmentAction.ROLL_UNTESTED,
            rule="rule_4",
            reason=(
                f"{untested} decayed to {untested_current:.2f} "
                f"({untested_current / untested_entry:.0%} of entry) — "
                f"roll closer for more credit ({snap.dte_remaining:.0f} DTE left)"
            ),
            tested_leg=tested,
            untested_leg=untested,
        )

    # ── Rule 5: Max loss ──────────────────────────────────────
    if snap.credit_received > 0:
        loss_multiple = -snap.current_pnl / snap.credit_received
        if loss_multiple >= max_loss_multiple:
            return AdjustmentDecision(
                action=AdjustmentAction.CLOSE_ALL,
                rule="rule_5",
                reason=(
                    f"P&L −{abs(snap.current_pnl):.2f} = "
                    f"{loss_multiple:.1f}× credit received — max loss breached"
                ),
                tested_leg=tested,
                untested_leg=untested,
            )

    # ── Default: hold ─────────────────────────────────────────
    return AdjustmentDecision(
        action=AdjustmentAction.HOLD,
        rule="default",
        reason="All parameters within tolerance",
        tested_leg=tested,
        untested_leg=untested,
    )
