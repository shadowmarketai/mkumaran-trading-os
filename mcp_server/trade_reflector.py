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
        """Generate lesson using Claude API (1 API call)."""
        import anthropic

        api_key = settings.ANTHROPIC_API_KEY.strip()
        client = anthropic.Anthropic(api_key=api_key)

        prompt = (
            f"You are a trading coach reviewing a closed trade. Generate a concise lesson (1-2 sentences).\n\n"
            f"TRADE:\n"
            f"- Ticker: {record.ticker} | Direction: {record.direction} | Pattern: {record.pattern}\n"
            f"- Entry: ₹{record.entry_price:.2f} | SL: ₹{record.stop_loss:.2f} | Target: ₹{record.target:.2f}\n"
            f"- RRR: {record.rrr:.2f} | Confidence at entry: {record.confidence}%\n"
            f"- Outcome: {record.outcome} | Exit: ₹{record.exit_price:.2f} | P&L: {record.pnl_pct:+.1f}%\n"
            f"- Holding days: {record.holding_days}\n\n"
            f"What's the key lesson? Focus on what to repeat (if win) or avoid (if loss).\n"
            f"Respond with just the lesson text, no JSON."
        )

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=150,
            timeout=30.0,
            messages=[{"role": "user", "content": prompt}],
        )

        return response.content[0].text.strip()

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

        if high_conf and is_win:
            return (
                f"High-confidence {record.pattern} on {record.ticker} confirmed. "
                f"RRR {record.rrr:.1f} delivered {record.pnl_pct:+.1f}%. "
                f"Trust this setup when conditions repeat."
            )
        elif high_conf and is_loss:
            return (
                f"High-confidence {record.pattern} on {record.ticker} failed despite {record.confidence}% conviction. "
                f"Loss of {record.pnl_pct:.1f}% — review if entry timing or market context was ignored. "
                f"Overconfidence risk."
            )
        elif not high_conf and is_win:
            return (
                f"Low-confidence {record.pattern} on {record.ticker} unexpectedly won ({record.pnl_pct:+.1f}%). "
                f"Consider if the system under-scored this setup. "
                f"May indicate a pattern worth upgrading in scoring."
            )
        elif not high_conf and is_loss:
            return (
                f"Low-confidence {record.pattern} on {record.ticker} lost as expected ({record.pnl_pct:.1f}%). "
                f"System correctly flagged uncertainty. "
                f"Continue filtering similar setups with caution."
            )
        else:
            # BREAKEVEN
            return (
                f"{record.pattern} on {record.ticker} ended breakeven after {record.holding_days} days. "
                f"Consider tighter exit rules for this pattern."
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
