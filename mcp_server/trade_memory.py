"""
MKUMARAN Trading OS — BM25 Trade Memory

Offline similar-trade retrieval using BM25 ranking.
Zero API cost — searches past trades by situation text similarity.

Gracefully degrades if rank-bm25 is not installed (returns empty results).
"""

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Graceful BM25 import
try:
    from rank_bm25 import BM25Okapi
    _HAS_BM25 = True
except ImportError:
    _HAS_BM25 = False
    logger.warning("rank-bm25 not installed — trade memory search disabled (pip install rank-bm25)")


@dataclass
class TradeRecord:
    """A single trade record stored in memory."""
    signal_id: str
    ticker: str
    direction: str  # BUY / SELL
    pattern: str
    entry_price: float
    stop_loss: float
    target: float
    rrr: float
    confidence: int
    recommendation: str  # ALERT / WATCHLIST / SKIP / BLOCKED
    exchange: str = "NSE"
    timestamp: str = ""
    # Outcome fields (filled after trade closes)
    outcome: str = ""  # WIN / LOSS / BREAKEVEN / OPEN
    exit_price: float = 0.0
    pnl_pct: float = 0.0
    holding_days: int = 0
    # Reflection
    lesson: str = ""
    reflected: bool = False

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    def to_situation_text(self) -> str:
        """Convert to searchable text for BM25 indexing."""
        parts = [
            self.ticker,
            self.direction,
            self.pattern,
            f"rrr_{self.rrr:.1f}",
            f"conf_{self.confidence}",
            self.recommendation,
            self.exchange,
        ]
        if self.outcome:
            parts.append(f"outcome_{self.outcome}")
        if self.lesson:
            parts.append(self.lesson)
        return " ".join(parts)


class TradeMemory:
    """
    BM25-based trade memory for similar-trade retrieval.

    Stores trades as JSON, builds BM25 index for fast similarity search.
    All operations are offline — zero API cost.
    """

    def __init__(self, filepath: str = "data/trade_memory.json"):
        self._filepath = filepath
        self._records: list[TradeRecord] = []
        self._index = None
        self._corpus: list[list[str]] = []
        self._load()

    def _load(self):
        """Load records from JSON file."""
        if not os.path.exists(self._filepath):
            self._records = []
            return
        try:
            with open(self._filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._records = [TradeRecord(**r) for r in data]
            self._rebuild_index()
            logger.info("Trade memory loaded: %d records", len(self._records))
        except Exception as e:
            logger.error("Failed to load trade memory: %s", e)
            self._records = []

    def _save(self):
        """Persist records to JSON file."""
        os.makedirs(os.path.dirname(self._filepath) or ".", exist_ok=True)
        try:
            with open(self._filepath, "w", encoding="utf-8") as f:
                json.dump([asdict(r) for r in self._records], f, indent=2)
        except Exception as e:
            logger.error("Failed to save trade memory: %s", e)

    def _rebuild_index(self):
        """Rebuild BM25 index from current records."""
        if not _HAS_BM25 or not self._records:
            self._index = None
            self._corpus = []
            return
        self._corpus = [r.to_situation_text().lower().split() for r in self._records]
        self._index = BM25Okapi(self._corpus)

    def add_record(self, record: TradeRecord):
        """Add a new trade record and rebuild index."""
        self._records.append(record)
        self._rebuild_index()
        self._save()
        logger.info("Trade memory: added %s (%s)", record.signal_id, record.ticker)

    def update_outcome(
        self,
        signal_id: str,
        outcome: str,
        exit_price: float = 0.0,
        pnl_pct: float = 0.0,
        holding_days: int = 0,
    ) -> bool:
        """Update outcome for a closed trade. Returns True if found."""
        for record in self._records:
            if record.signal_id == signal_id:
                record.outcome = outcome
                record.exit_price = exit_price
                record.pnl_pct = pnl_pct
                record.holding_days = holding_days
                self._rebuild_index()
                self._save()
                logger.info("Trade memory: updated outcome for %s → %s", signal_id, outcome)
                return True
        logger.warning("Trade memory: signal_id %s not found", signal_id)
        return False

    def add_lesson(self, signal_id: str, lesson: str) -> bool:
        """Store a reflection lesson for a trade. Returns True if found."""
        for record in self._records:
            if record.signal_id == signal_id:
                record.lesson = lesson
                record.reflected = True
                self._rebuild_index()
                self._save()
                return True
        return False

    def find_similar_for_signal(
        self,
        ticker: str,
        direction: str,
        pattern: str,
        rrr: float,
        confidence: int = 50,
        exchange: str = "NSE",
        top_k: int = 3,
    ) -> list[dict]:
        """
        Find top-k similar past trades using BM25 similarity.

        Returns list of dicts with trade info + similarity score.
        Returns empty list if BM25 not available or no records.
        """
        if not _HAS_BM25 or self._index is None or not self._records:
            return []

        query_text = f"{ticker} {direction} {pattern} rrr_{rrr:.1f} conf_{confidence} {exchange}"
        query_tokens = query_text.lower().split()

        scores = self._index.get_scores(query_tokens)

        # Get top-k indices sorted by score descending
        # Note: BM25 can return negative scores for small corpora (IDF effect),
        # so we filter only exact-zero scores (no token overlap at all)
        scored_indices = sorted(
            enumerate(scores), key=lambda x: x[1], reverse=True
        )[:top_k]

        # Find the max score to determine if there's any discrimination
        max_score = max(scores) if len(scores) > 0 else 0

        results = []
        for idx, score in scored_indices:
            # Skip only if score equals the minimum (no discrimination)
            # For small corpora, all scores may be negative but relative ranking matters
            if max_score == min(scores) and score <= 0:
                continue
            record = self._records[idx]
            results.append({
                "signal_id": record.signal_id,
                "ticker": record.ticker,
                "direction": record.direction,
                "pattern": record.pattern,
                "rrr": record.rrr,
                "confidence": record.confidence,
                "outcome": record.outcome,
                "pnl_pct": record.pnl_pct,
                "lesson": record.lesson,
                "similarity": round(float(score), 4),
            })

        return results

    def get_stats(self) -> dict:
        """Get memory statistics."""
        total = len(self._records)
        if total == 0:
            return {"total": 0, "with_outcome": 0, "reflected": 0, "win_rate": 0.0}

        with_outcome = [r for r in self._records if r.outcome in ("WIN", "LOSS", "BREAKEVEN")]
        wins = [r for r in with_outcome if r.outcome == "WIN"]
        reflected = [r for r in self._records if r.reflected]

        return {
            "total": total,
            "with_outcome": len(with_outcome),
            "wins": len(wins),
            "losses": len([r for r in with_outcome if r.outcome == "LOSS"]),
            "win_rate": round(len(wins) / len(with_outcome) * 100, 1) if with_outcome else 0.0,
            "reflected": len(reflected),
            "bm25_available": _HAS_BM25,
        }

    def get_unreflected_trades(self, limit: int = 10) -> list[TradeRecord]:
        """Get closed trades that haven't been reflected on yet."""
        return [
            r for r in self._records
            if r.outcome in ("WIN", "LOSS", "BREAKEVEN") and not r.reflected
        ][:limit]

    def get_record_by_id(self, signal_id: str) -> Optional[TradeRecord]:
        """Get a single record by signal_id."""
        for record in self._records:
            if record.signal_id == signal_id:
                return record
        return None
