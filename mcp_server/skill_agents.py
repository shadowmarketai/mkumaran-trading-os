"""
MKUMARAN Trading OS — Multi-Specialist Debate Agents

Each agent is a specialist with unique skills:

  1. SMC Agent     — Smart Money Concepts (Order Blocks, FVG, BOS, ChoCH)
  2. ICT Agent     — Inner Circle Trader (OTE, Kill Zones, Judas Swing, Displacement)
  3. VSA Agent     — Volume Spread Analysis (Climax, No Demand, Stopping Volume)
  4. Wyckoff Agent — Wyckoff Method (Accumulation, Distribution, Spring, Upthrust)
  5. Classical Agent — Technical Analysis (EMA, RSI, MACD, Breakout, Support/Resistance)
  6. Harmonic Agent — Harmonic Patterns (Gartley, Bat, Butterfly, Crab, ABCD)
  7. Judge Agent   — Weighs all specialist scores → final confidence
  8. Risk Agent    — Position sizing, exposure, portfolio risk

Self-Learning: Each agent's weights adjust based on WIN/LOSS outcomes.
Target: 90% accuracy — below this, agents auto-tighten their filters.
ZERO API calls. Pure algorithmic debate.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

WEIGHTS_PATH = Path("data/agent_weights.json")
TARGET_ACCURACY = 90.0
MIN_SIGNALS_FOR_LEARNING = 10


@dataclass
class AgentScore:
    agent: str
    skill: str
    score: float
    max_score: float
    verdict: str  # BULLISH, BEARISH, NEUTRAL
    factors: list[dict] = field(default_factory=list)
    reasoning: str = ""


@dataclass
class DebateResult:
    final_confidence: int
    recommendation: str
    reasoning: str
    bull_score: float = 0
    bear_score: float = 0
    judge_score: float = 0
    risk_grade: str = "B"
    method: str = "skill_debate"
    api_calls_used: int = 0
    validation_status: str = "VALIDATED"
    debate_transcript: list[dict] = field(default_factory=list)
    similar_trades: list[dict] = field(default_factory=list)
    risk_assessment: str = ""
    boosts: list[str] = field(default_factory=list)
    agents_used: list[str] = field(default_factory=list)


# ── Default Weights per Agent ─────────────────────────────────

DEFAULT_WEIGHTS = {
    "smc": {
        "order_block": 14.0, "fvg": 10.0, "bos": 15.0,
        "choch": 16.0, "demand_zone": 12.0, "supply_zone": 12.0,
        "liquidity_sweep": 14.0, "mitigation_block": 10.0,
        "premium_discount": 8.0, "version": 1,
    },
    "ict": {
        "ote": 13.0, "killzone_london": 8.0, "killzone_ny": 10.0,
        "judas_swing": 12.0, "displacement": 14.0, "institutional_candle": 9.0,
        "turtle_soup": 12.0, "breaker_block": 11.0, "smt_divergence": 10.0,
        "fair_value_gap": 11.0, "version": 1,
    },
    "vsa": {
        "stopping_volume": 12.0, "no_supply": 9.0, "no_demand": 9.0,
        "climax_volume": 13.0, "effort_result": 10.0, "upthrust": 12.0,
        "test_supply": 10.0, "shakeout": 11.0, "absorption": 12.0,
        "version": 1,
    },
    "wyckoff": {
        "spring": 15.0, "upthrust_dist": 15.0, "sos": 13.0, "sow": 13.0,
        "test": 11.0, "lpsy": 10.0, "lps": 10.0, "creek_jump": 12.0,
        "phase_a": 8.0, "phase_c": 14.0, "version": 1,
    },
    "classical": {
        "ema_alignment": 10.0, "rsi_signal": 8.0, "macd_cross": 7.0,
        "breakout_20d": 14.0, "volume_surge": 9.0, "support_bounce": 11.0,
        "resistance_reject": 11.0, "delivery_high": 6.0,
        "sector_strong": 6.0, "fii_aligned": 5.0, "mwa_aligned": 15.0,
        "version": 1,
    },
    "harmonic": {
        "gartley": 13.0, "bat": 12.0, "butterfly": 11.0, "crab": 14.0,
        "abcd": 10.0, "shark": 11.0, "deep_crab": 12.0, "three_drives": 10.0,
        "version": 1,
    },
    "judge": {
        "min_confidence": 55.0, "rrr_multiplier": 1.3, "mwa_weight": 1.4,
        "scanner_threshold": 3, "multi_agent_bonus": 5.0,
        "consensus_threshold": 4, "version": 1,
    },
    "risk": {
        "max_risk_pct": 2.0, "max_positions": 5, "min_rrr": 2.0,
        "min_rrr_smc": 1.5, "version": 1,
    },
    "accuracy": {
        "total": 0, "wins": 0, "losses": 0,
        "current_rate": 0.0, "adjustments": 0, "last_adjustment": "",
        "per_agent": {},
    },
}


def _load_weights() -> dict:
    if WEIGHTS_PATH.exists():
        try:
            data = json.loads(WEIGHTS_PATH.read_text())
            for k in DEFAULT_WEIGHTS:
                if k not in data:
                    data[k] = DEFAULT_WEIGHTS[k].copy()
                else:
                    for kk, vv in DEFAULT_WEIGHTS[k].items():
                        if kk not in data[k]:
                            data[k][kk] = vv
            return data
        except Exception:
            pass
    return json.loads(json.dumps(DEFAULT_WEIGHTS))


def _save_weights(w):
    WEIGHTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    WEIGHTS_PATH.write_text(json.dumps(w, indent=2, default=str))


# ── Helper: which scanner groups fired for this ticker ────────

def _get_fired_groups(scanner_results: dict, ticker: str) -> dict:
    """Returns {group: {"bull": count, "bear": count}} for this ticker."""
    tc = ticker.replace("NSE:", "").replace("NFO:", "").replace("MCX:", "").replace("CDS:", "")
    groups: dict[str, dict] = {}
    for sname, sdata in scanner_results.items():
        stocks = sdata.get("stocks", [])
        if tc in stocks or ticker in stocks:
            g = sdata.get("group", "Other")
            d = sdata.get("direction", "NEUTRAL")
            if g not in groups:
                groups[g] = {"bull": 0, "bear": 0, "neutral": 0}
            groups[g][d.lower() if d.lower() in ("bull", "bear") else "neutral"] += 1
    return groups


# ── SPECIALIST AGENTS ─────────────────────────────────────────

def _run_specialist(agent_name: str, skill: str, scanner_results: dict,
                     ticker: str, direction: str, fired_groups: dict,
                     mwa_direction: str, scanner_count: int,
                     sector_strength: str, fii_net: float,
                     delivery_pct: float) -> AgentScore:
    """Generic specialist agent — checks if its skill-group scanners fired."""
    w = _load_weights()[agent_name]
    is_long = direction.upper() in ("LONG", "BUY")
    score = 0.0
    max_score = 0.0
    factors = []

    # Map agent to scanner group names
    GROUP_MAP = {
        "smc": ["SMC"], "ict": ["SMC", "Filter"],  # ICT uses SMC + Filter scanners
        "vsa": ["VSA", "Volume"], "wyckoff": ["Wyckoff"],
        "classical": ["Trend", "Breakout", "RSI", "MA", "Gap"],
        "harmonic": ["Harmonic"],
    }

    target_groups = GROUP_MAP.get(agent_name, [])
    matched = {g: fired_groups[g] for g in target_groups if g in fired_groups}

    # Score based on how many scanners from this skill fired
    bull_hits = sum(v["bull"] for v in matched.values())
    bear_hits = sum(v["bear"] for v in matched.values())

    # Get relevant weight keys (first 8 non-version keys)
    weight_keys = [k for k in w if k != "version"][:8]
    pts_per_hit = sum(w.get(k, 10) for k in weight_keys[:3]) / 3 if weight_keys else 10

    max_score = pts_per_hit * 5  # assume max 5 hits

    if is_long:
        signal_hits = bull_hits
        counter_hits = bear_hits
    else:
        signal_hits = bear_hits
        counter_hits = bull_hits

    if signal_hits > 0:
        pts = signal_hits * pts_per_hit
        score += pts
        factors.append({"factor": f"{skill}_signal_aligned", "hits": signal_hits,
                         "pts": round(pts, 1), "skill": skill})

    if counter_hits > 0:
        penalty = counter_hits * (pts_per_hit * 0.5)
        score -= penalty
        factors.append({"factor": f"{skill}_counter_signal", "hits": counter_hits,
                         "pts": round(-penalty, 1), "skill": skill})

    # MWA alignment bonus for classical agent
    if agent_name == "classical":
        mwa_pts = w.get("mwa_aligned", 15)
        max_score += mwa_pts
        mwa_ok = (is_long and mwa_direction in ("BULL", "MILD_BULL")) or \
                 (not is_long and mwa_direction in ("BEAR", "MILD_BEAR"))
        if mwa_ok:
            score += mwa_pts
            factors.append({"factor": "mwa_aligned", "pts": mwa_pts, "skill": "Classical"})

        # Sector + FII
        if sector_strength == "STRONG":
            score += w.get("sector_strong", 6)
            factors.append({"factor": "sector_strong", "pts": 6, "skill": "Classical"})
        if (is_long and fii_net > 0) or (not is_long and fii_net < 0):
            score += w.get("fii_aligned", 5)
            factors.append({"factor": "fii_aligned", "pts": 5, "skill": "Classical"})
        max_score += 11

    score = max(0, score)

    # Verdict
    if score > max_score * 0.6:
        verdict = "BULLISH" if is_long else "BEARISH"
    elif score > max_score * 0.3:
        verdict = "NEUTRAL"
    else:
        verdict = "BEARISH" if is_long else "BULLISH"

    return AgentScore(
        agent=agent_name, skill=skill, score=round(score, 1),
        max_score=round(max_score, 1), verdict=verdict, factors=factors,
        reasoning=f"{skill}: {score:.0f}/{max_score:.0f} ({signal_hits} aligned, {counter_hits} against) → {verdict}",
    )


# ── JUDGE AGENT ───────────────────────────────────────────────

def _run_judge(agents: list[AgentScore], rrr: float, scanner_count: int,
                mwa_direction: str, direction: str) -> tuple[int, str, str, list[str]]:
    w = _load_weights()["judge"]
    is_long = direction.upper() in ("LONG", "BUY")

    # Count agent verdicts
    bullish_agents = [a for a in agents if a.verdict == ("BULLISH" if is_long else "BEARISH")]
    bearish_agents = [a for a in agents if a.verdict == ("BEARISH" if is_long else "BULLISH")]
    neutral_agents = [a for a in agents if a.verdict == "NEUTRAL"]

    # Weighted score from all agents
    total_score = sum(a.score for a in agents)
    max_total = sum(a.max_score for a in agents if a.max_score > 0)
    ratio = total_score / max_total if max_total > 0 else 0.5

    confidence = int(30 + ratio * 45)

    # Consensus bonus — multiple specialists agree
    consensus = len(bullish_agents)
    if consensus >= w["consensus_threshold"]:
        confidence += int(consensus * w["multi_agent_bonus"])
    elif consensus >= 3:
        confidence += int(3 * w["multi_agent_bonus"])

    # RRR
    if rrr >= 3.0:
        confidence += int(10 * w["rrr_multiplier"])
    elif rrr >= 2.0:
        confidence += int(5 * w["rrr_multiplier"])
    elif rrr < 1.5:
        confidence -= 15

    # MWA
    mwa_ok = (is_long and mwa_direction in ("BULL", "MILD_BULL")) or \
             (not is_long and mwa_direction in ("BEAR", "MILD_BEAR"))
    if mwa_ok:
        confidence += int(8 * w["mwa_weight"])
    elif mwa_direction not in ("SIDEWAYS", "UNKNOWN", "N/A", ""):
        confidence -= int(6 * w["mwa_weight"])

    # Scanner count
    if scanner_count >= w["scanner_threshold"]:
        confidence += (scanner_count - int(w["scanner_threshold"])) * 2

    confidence = max(0, min(100, confidence))

    # Build agent consensus string
    agreed = [a.skill for a in bullish_agents]
    disagreed = [a.skill for a in bearish_agents]

    if confidence >= 75:
        rec = "ALERT"
        reasoning = f"Strong ({confidence}%) — {len(agreed)} agents agree: {', '.join(agreed)}"
    elif confidence >= w["min_confidence"]:
        rec = "WATCHLIST"
        reasoning = f"Moderate ({confidence}%) — {len(agreed)} agree, {len(disagreed)} disagree"
    else:
        rec = "SKIP"
        reasoning = f"Weak ({confidence}%) — {len(disagreed)} agents against: {', '.join(disagreed)}"

    return confidence, rec, reasoning, agreed


# ── RISK AGENT ────────────────────────────────────────────────

def _run_risk(entry: float, sl: float, target: float, rrr: float,
               direction: str, has_smc: bool) -> tuple[str, str]:
    w = _load_weights()["risk"]
    pts = 100
    issues = []
    is_long = direction.upper() in ("LONG", "BUY")
    min_rrr = w["min_rrr_smc"] if has_smc else w["min_rrr"]

    if rrr < min_rrr:
        pts -= 30; issues.append(f"RRR {rrr:.1f} < {min_rrr}")
    risk_pct = abs(entry - sl) / entry * 100 if entry > 0 else 0
    if risk_pct > 5:
        pts -= 20; issues.append(f"Wide SL {risk_pct:.1f}%")
    if is_long and sl >= entry:
        pts -= 50; issues.append("SL above entry")
    if is_long and target <= entry:
        pts -= 50; issues.append("Target below entry")

    pts = max(0, pts)
    grade = "A" if pts >= 80 else "B" if pts >= 60 else "C" if pts >= 40 else "D"
    return grade, f"Risk {grade} ({pts}/100)" + (f" — {'; '.join(issues)}" if issues else "")


# ══════════════════════════════════════════════════════════════
# FULL DEBATE — runs all 6 specialists + judge + risk
# ══════════════════════════════════════════════════════════════

AGENTS = [
    ("smc", "SMC"),
    ("ict", "ICT"),
    ("vsa", "VSA"),
    ("wyckoff", "Wyckoff"),
    ("classical", "Classical"),
    ("harmonic", "Harmonic"),
]


def run_skill_debate(
    ticker: str, direction: str, pattern: str, rrr: float,
    entry_price: float, stop_loss: float, target: float,
    mwa_direction: str = "UNKNOWN", scanner_count: int = 0,
    scanner_results: dict | None = None,
    sector_strength: str = "NEUTRAL", fii_net: float = 0,
    delivery_pct: float = 0, **kwargs,
) -> DebateResult:
    """Run 8-agent debate — ZERO API calls."""
    sr = scanner_results or {}
    fired = _get_fired_groups(sr, ticker)

    # Run all 6 specialists
    agent_scores: list[AgentScore] = []
    for agent_name, skill in AGENTS:
        score = _run_specialist(agent_name, skill, sr, ticker, direction,
                                 fired, mwa_direction, scanner_count,
                                 sector_strength, fii_net, delivery_pct)
        agent_scores.append(score)

    # Judge
    confidence, rec, reasoning, agreed = _run_judge(
        agent_scores, rrr, scanner_count, mwa_direction, direction)

    # Risk
    has_smc = any(a.skill == "SMC" and a.verdict != "NEUTRAL" for a in agent_scores)
    risk_grade, risk_assessment = _run_risk(entry_price, stop_loss, target,
                                             rrr, direction, has_smc)

    if risk_grade == "D":
        confidence = max(0, confidence - 20)
        rec = "SKIP"
    elif risk_grade == "C" and rec == "ALERT":
        confidence = max(0, confidence - 10)
        rec = "WATCHLIST"

    # Build transcript
    transcript = [
        {"agent": a.agent, "skill": a.skill, "score": a.score,
         "max": a.max_score, "verdict": a.verdict,
         "factors": a.factors, "reasoning": a.reasoning}
        for a in agent_scores
    ]
    transcript.append({"agent": "judge", "confidence": confidence,
                        "recommendation": rec, "reasoning": reasoning})
    transcript.append({"agent": "risk", "grade": risk_grade,
                        "assessment": risk_assessment})

    bull_total = sum(a.score for a in agent_scores if a.verdict in ("BULLISH",))
    bear_total = sum(a.score for a in agent_scores if a.verdict in ("BEARISH",))

    return DebateResult(
        final_confidence=confidence, recommendation=rec, reasoning=reasoning,
        bull_score=bull_total, bear_score=bear_total,
        judge_score=float(confidence), risk_grade=risk_grade,
        risk_assessment=risk_assessment, method="skill_debate",
        api_calls_used=0, debate_transcript=transcript,
        boosts=agreed, agents_used=[a.skill for a in agent_scores],
    )


# ── SELF-LEARNING ─────────────────────────────────────────────

def record_outcome(signal_id: int = 0, outcome: str = "",
                    scanner_count: int = 0, confidence: int = 0, **kwargs):
    w = _load_weights()
    a = w["accuracy"]
    a["total"] = a.get("total", 0) + 1
    if outcome == "WIN":
        a["wins"] = a.get("wins", 0) + 1
    else:
        a["losses"] = a.get("losses", 0) + 1

    rate = round(a["wins"] / a["total"] * 100, 1) if a["total"] > 0 else 0
    a["current_rate"] = rate

    logger.info("Learning: %s | accuracy=%.1f%% (%d/%d)", outcome, rate, a["wins"], a["total"])

    if a["total"] >= MIN_SIGNALS_FOR_LEARNING and rate < TARGET_ACCURACY:
        j = w["judge"]
        r = w["risk"]
        if outcome == "LOSS":
            j["min_confidence"] = min(82, j["min_confidence"] + 1.5)
            j["scanner_threshold"] = min(5, j["scanner_threshold"] + 0.3)
            j["consensus_threshold"] = min(5, j["consensus_threshold"] + 0.2)
            r["min_rrr"] = min(4.0, r["min_rrr"] + 0.15)
            j["version"] = j.get("version", 1) + 1
            logger.info("LOSS: tightened min_conf=%.1f thresh=%.1f rrr=%.1f",
                         j["min_confidence"], j["scanner_threshold"], r["min_rrr"])
        elif outcome == "WIN" and confidence < 60:
            j["min_confidence"] = max(50, j["min_confidence"] - 0.5)
            j["multi_agent_bonus"] = min(8, j["multi_agent_bonus"] + 0.2)
        a["adjustments"] = a.get("adjustments", 0) + 1
        a["last_adjustment"] = str(date.today())

    _save_weights(w)


def get_agent_stats() -> dict:
    w = _load_weights()
    a = w["accuracy"]
    return {
        "total": a.get("total", 0), "wins": a.get("wins", 0),
        "losses": a.get("losses", 0), "accuracy": a.get("current_rate", 0),
        "target": TARGET_ACCURACY,
        "adjustments": a.get("adjustments", 0),
        "judge_version": w["judge"].get("version", 1),
        "min_confidence": w["judge"]["min_confidence"],
        "consensus_needed": w["judge"]["consensus_threshold"],
        "min_rrr": w["risk"]["min_rrr"],
        "agents": ["SMC", "ICT", "VSA", "Wyckoff", "Classical", "Harmonic", "Judge", "Risk"],
    }
