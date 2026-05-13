"""
MKUMARAN Trading OS — Trade Reflector

Post-trade learning system that generates lessons from closed trades.
Enriches BM25 memory so future similar-trade lookups include insights.

Two modes:
- Online: Claude generates lesson (1 API call per trade)
- Offline: Rule-based 4-quadrant analysis (0 API cost)
"""

import logging

from mcp_server.config import settings
from mcp_server.trade_memory import TradeMemory, TradeRecord

logger = logging.getLogger(__name__)

# Backtest-validated win rates by pattern layer (2021-2026, Nifty 500).
# Used to contextualise whether a loss/win is expected or surprising.
_PATTERN_WIN_RATES: dict[str, tuple[str, float]] = {
    "harmonic":      ("TIER_2",   0.541),
    "bb breakout weekly": ("TIER_1", 0.583),
    "bb breakout":   ("TIER_2",   0.432),
    "smc":           ("OVERRIDE", 0.454),
    "vsa":           ("OVERRIDE", 0.457),
    "wyckoff":       ("OVERRIDE", 0.488),
    "supertrend":    ("OVERRIDE", 0.417),
    "macd":          ("OVERRIDE", 0.320),
    "ema":           ("OVERRIDE", 0.352),
}


def _pattern_context(pattern: str) -> str:
    """Return tier + win-rate context for a given pattern name."""
    p = pattern.lower()
    for key, (tier, wr) in _PATTERN_WIN_RATES.items():
        if key in p:
            return (
                f"{tier} validated (backtest WR={wr*100:.0f}%). "
                f"{'Win is within expected range.' if tier in ('TIER_1','TIER_2') else 'Needs 5+ confluence signals.'}"
            )
    return "Unvalidated pattern — treat outcome as new data."


class TradeReflector:
    """
    Reflects on closed trades and generates lessons.

    Lessons are stored back into TradeMemory, enriching BM25 search
    results for future similar signals.
    """

    def __init__(self, memory: TradeMemory):
        self._memory = memory

    def reflect_on_trade(self, signal_id: str) -> dict:
        """
        Reflect on a single closed trade.

        Uses Claude API if available, falls back to offline rules.
        Returns dict with lesson and method used.
        """
        record = self._memory.get_record_by_id(signal_id)
        if record is None:
            return {"success": False, "error": f"Signal {signal_id} not found in memory"}

        if record.outcome not in ("WIN", "LOSS", "BREAKEVEN"):
            return {"success": False, "error": f"Signal {signal_id} still OPEN — cannot reflect"}

        if record.reflected:
            return {"success": True, "lesson": record.lesson, "method": "already_reflected"}

        # Try online reflection first, fall back to offline
        lesson = ""
        method = "offline"

        if settings.ANTHROPIC_API_KEY:
            try:
                lesson = self._generate_lesson(record)
                method = "online"
            except Exception as e:
                logger.warning("Online reflection failed for %s, using offline: %s", signal_id, e)
                lesson = self._generate_lesson_offline(record)
        else:
            lesson = self._generate_lesson_offline(record)

        # Store lesson back into memory
        self._memory.add_lesson(signal_id, lesson)

        logger.info("Reflected on %s (%s): method=%s", signal_id, record.outcome, method)
        return {"success": True, "signal_id": signal_id, "lesson": lesson, "method": method}

    def _generate_lesson(self, record: TradeRecord) -> str:
        """Generate lesson via the multi-provider AI abstraction (1 call)."""
        from mcp_server.ai_provider import call_ai

        pat_ctx = _pattern_context(record.pattern)
        prompt = (
            f"You are a trading coach reviewing a closed trade. Generate a concise lesson (1-2 sentences).\n\n"
            f"TRADE:\n"
            f"- Ticker: {record.ticker} | Direction: {record.direction} | Pattern: {record.pattern}\n"
            f"- Pattern context: {pat_ctx}\n"
            f"- Entry: ₹{record.entry_price:.2f} | SL: ₹{record.stop_loss:.2f} | Target: ₹{record.target:.2f}\n"
            f"- RRR: {record.rrr:.2f} | Confidence at entry: {record.confidence}%\n"
            f"- Outcome: {record.outcome} | Exit: ₹{record.exit_price:.2f} | P&L: {record.pnl_pct:+.1f}%\n"
            f"- Holding days: {record.holding_days}\n\n"
            f"What's the key lesson? Use the pattern context to assess if this outcome was expected or surprising.\n"
            f"If TIER_1/TIER_2 pattern won: confirm the edge. If OVERRIDE pattern won alone: flag as possible luck.\n"
            f"If TIER_1/TIER_2 pattern lost: identify what confluence was missing. If OVERRIDE lost: expected.\n"
            f"Respond with just the lesson text, no JSON."
        )

        return call_ai(prompt=prompt, max_tokens=150, temperature=0.3).strip()

    def _generate_lesson_offline(self, record: TradeRecord) -> str:
        """
        Rule-based lesson generation (0 API cost).

        4 quadrants:
        - High confidence + WIN → pattern was right, trust it
        - High confidence + LOSS → overconfidence red flag
        - Low confidence + WIN → missed opportunity / luck
        - Low confidence + LOSS → system correctly doubted
        """
        high_conf = record.confidence >= 70
        is_win = record.outcome == "WIN"
        is_loss = record.outcome == "LOSS"
        pat_ctx = _pattern_context(record.pattern)

        # Determine if this outcome was expected based on backtest tier
        p = record.pattern.lower()
        is_tier1 = any(k in p for k in ("bb breakout weekly",))
        is_tier2 = any(k in p for k in ("harmonic", "bb breakout",)) and not is_tier1
        is_override = any(k in p for k in ("smc", "vsa", "wyckoff", "supertrend", "macd", "ema"))
        expected_qualifier = (
            "Expected loss (OVERRIDE pattern, <50% WR standalone)." if is_override and is_loss
            else "Unexpected loss (TIER_1 validated pattern)." if is_tier1 and is_loss
            else "Expected win range for TIER_2 pattern." if is_tier2 and is_win
            else ""
        )

        if high_conf and is_win:
            return (
                f"High-confidence {record.pattern} on {record.ticker} confirmed ({pat_ctx}). "
                f"RRR {record.rrr:.1f} delivered {record.pnl_pct:+.1f}%. "
                f"Trust this setup when conditions repeat."
            )
        elif high_conf and is_loss:
            return (
                f"High-confidence {record.pattern} on {record.ticker} failed ({record.pnl_pct:.1f}%). "
                f"{pat_ctx} {expected_qualifier} "
                f"Review entry timing and whether 5+ scanner hits were present."
            )
        elif not high_conf and is_win:
            return (
                f"Low-confidence {record.pattern} on {record.ticker} won ({record.pnl_pct:+.1f}%). "
                f"{pat_ctx} "
                f"{'System may be under-scoring this pattern.' if not is_override else 'Possible luck — needs confluence to be reliable.'}"
            )
        elif not high_conf and is_loss:
            return (
                f"Low-confidence {record.pattern} on {record.ticker} lost ({record.pnl_pct:.1f}%). "
                f"{expected_qualifier if expected_qualifier else pat_ctx} "
                f"System correctly flagged uncertainty — continue filtering similar setups."
            )
        else:
            return (
                f"{record.pattern} on {record.ticker} ended breakeven after {record.holding_days} days. "
                f"{pat_ctx} Consider tighter exit rules for this pattern."
            )

    def reflect_batch(self, limit: int = 10) -> dict:
        """
        Reflect on up to N unreflected closed trades.

        Returns summary of reflections performed.
        """
        unreflected = self._memory.get_unreflected_trades(limit=limit)

        if not unreflected:
            return {"reflected": 0, "message": "No unreflected closed trades found"}

        results = []
        for record in unreflected:
            result = self.reflect_on_trade(record.signal_id)
            results.append(result)

        successes = [r for r in results if r.get("success")]
        return {
            "reflected": len(successes),
            "total_candidates": len(unreflected),
            "details": results,
        }

    def get_reflection_stats(self) -> dict:
        """
        Accuracy metrics from reflected trades.

        Returns win rates segmented by confidence level.
        """
        stats = self._memory.get_stats()
        records = self._memory._records

        # Segment by confidence
        high_conf_trades = [r for r in records if r.confidence >= 70 and r.outcome in ("WIN", "LOSS")]
        low_conf_trades = [r for r in records if r.confidence < 70 and r.outcome in ("WIN", "LOSS")]

        high_conf_wins = len([r for r in high_conf_trades if r.outcome == "WIN"])
        low_conf_wins = len([r for r in low_conf_trades if r.outcome == "WIN"])

        return {
            **stats,
            "high_conf_trades": len(high_conf_trades),
            "high_conf_win_rate": round(high_conf_wins / len(high_conf_trades) * 100, 1) if high_conf_trades else 0.0,
            "low_conf_trades": len(low_conf_trades),
            "low_conf_win_rate": round(low_conf_wins / len(low_conf_trades) * 100, 1) if low_conf_trades else 0.0,
        }
