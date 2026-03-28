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

    def bootstrap_seed_trades(self) -> int:
        """
        Bootstrap memory with realistic seed trades for cold-start problem.

        Generates 50 diverse trades across tickers, patterns, directions,
        and outcomes to give BM25 enough corpus for discrimination.
        Only runs if memory has fewer than 10 records.

        Returns number of seed trades added.
        """
        if len(self._records) >= 10:
            logger.info("Trade memory already has %d records — skipping bootstrap", len(self._records))
            return 0

        seed_trades = _generate_seed_trades()
        added = 0
        for trade in seed_trades:
            self._records.append(trade)
            added += 1

        self._rebuild_index()
        self._save()
        logger.info("Bootstrapped trade memory with %d seed trades", added)
        return added


def _generate_seed_trades() -> list[TradeRecord]:
    """
    Generate 50 realistic seed trades based on historical Indian market patterns.

    Mix of wins, losses, breakevens across different:
    - Tickers (NSE large-cap, mid-cap, MCX, CDS)
    - Patterns (breakout, pullback, reversal, SMC, Wyckoff, harmonic)
    - Directions (LONG/SELL)
    - Confidence levels (45-85)
    - Outcomes (60% win, 30% loss, 10% breakeven — realistic distribution)
    """
    seeds = [
        # NSE Large Cap — Pattern wins
        ("SEED-001", "NSE:RELIANCE", "BUY", "breakout_volume", 2450, 2380, 2650, 2.86, 72, "ALERT", "WIN", 2640, 7.8, 8, "NSE",
         "Strong breakout with volume confirmation — trust breakout patterns on RELIANCE with 2.5+ RRR."),
        ("SEED-002", "NSE:TCS", "BUY", "ema_crossover", 3800, 3700, 4100, 3.0, 68, "WATCHLIST", "WIN", 4050, 6.6, 12, "NSE",
         "EMA crossover worked well in trending IT sector. Works best when sector is STRONG."),
        ("SEED-003", "NSE:HDFCBANK", "BUY", "pullback_support", 1680, 1650, 1770, 3.0, 75, "ALERT", "WIN", 1760, 4.8, 5, "NSE",
         "Pullback to support on HDFCBANK is reliable — banking stocks respect key levels."),
        ("SEED-004", "NSE:ICICIBANK", "BUY", "smc_bos", 1050, 1020, 1140, 3.0, 70, "ALERT", "WIN", 1130, 7.6, 10, "NSE",
         "SMC break of structure on ICICI confirmed by volume. BOS signals on banks have high win rate."),
        ("SEED-005", "NSE:INFY", "BUY", "wyckoff_spring", 1550, 1510, 1670, 3.0, 65, "WATCHLIST", "WIN", 1660, 7.1, 14, "NSE",
         "Wyckoff spring setup worked — shakeout below range then strong reversal. Good for IT stocks."),

        # NSE Large Cap — Pattern losses
        ("SEED-006", "NSE:SBIN", "BUY", "breakout_volume", 620, 600, 680, 3.0, 62, "WATCHLIST", "LOSS", 598, -3.5, 3, "NSE",
         "False breakout on SBIN — PSU banks need stronger confirmation. Volume was low relative to average."),
        ("SEED-007", "NSE:TATAMOTORS", "BUY", "rsi_oversold", 580, 560, 640, 3.0, 55, "WATCHLIST", "LOSS", 555, -4.3, 5, "NSE",
         "RSI oversold bounce failed — auto sector was in downtrend. Don't buy dips against sector trend."),
        ("SEED-008", "NSE:BAJFINANCE", "BUY", "gap_fill", 7200, 7000, 7800, 3.0, 58, "WATCHLIST", "LOSS", 6980, -3.1, 2, "NSE",
         "Gap fill strategy failed on BAJFINANCE — gap was news-driven, not technical. Avoid news gaps."),

        # NSE Mid Cap
        ("SEED-009", "NSE:BHARATFORG", "BUY", "smc_order_block", 1250, 1210, 1370, 3.0, 71, "ALERT", "WIN", 1355, 8.4, 9, "NSE",
         "SMC order block re-test on BHARATFORG delivered. Mid-caps respect SMC levels in trending markets."),
        ("SEED-010", "NSE:CDSL", "BUY", "harmonic_bat", 1400, 1350, 1550, 3.0, 66, "WATCHLIST", "WIN", 1520, 8.6, 11, "NSE",
         "Harmonic bat pattern on CDSL — financial infra stock with clean chart. Harmonics work on low-noise charts."),
        ("SEED-011", "NSE:IRCTC", "BUY", "vsa_stopping_volume", 850, 820, 940, 3.0, 63, "WATCHLIST", "LOSS", 815, -4.1, 4, "NSE",
         "VSA stopping volume on IRCTC was fake — volume spike was selling, not accumulation. Check context."),
        ("SEED-012", "NSE:BEL", "BUY", "breakout_volume", 250, 240, 280, 3.0, 74, "ALERT", "WIN", 278, 11.2, 7, "NSE",
         "Defence sector breakout on BEL — sector strength confirmed by FII flows. Sector alignment is key."),

        # SHORT trades
        ("SEED-013", "NSE:IDEA", "SELL", "breakdown", 12, 13, 10, 2.0, 60, "WATCHLIST", "WIN", 10.2, 15.0, 6, "NSE",
         "Breakdown on weak stock with heavy supply — low-priced stocks breakdown cleanly below support."),
        ("SEED-014", "NSE:TATAMOTORS", "SELL", "smc_choch", 650, 670, 610, 2.0, 55, "WATCHLIST", "LOSS", 675, -3.8, 3, "NSE",
         "Short on TATA MOTORS failed — market was in bull regime. Don't short in strong MWA BULL direction."),
        ("SEED-015", "NSE:HINDALCO", "SELL", "vsa_climax", 520, 540, 480, 2.0, 67, "WATCHLIST", "WIN", 485, 6.7, 8, "NSE",
         "VSA climactic volume marked top on HINDALCO. Metals top on volume spikes — trust the VSA signal."),

        # MCX Commodity
        ("SEED-016", "MCX:GOLD", "BUY", "breakout_volume", 58000, 57200, 59600, 2.0, 73, "ALERT", "WIN", 59400, 2.4, 5, "MCX",
         "Gold breakout with safe-haven demand. MCX gold respects breakout levels — use 2:1 RRR for commodities."),
        ("SEED-017", "MCX:SILVER", "BUY", "ema_crossover", 72000, 70000, 78000, 3.0, 60, "WATCHLIST", "LOSS", 69500, -3.5, 4, "MCX",
         "Silver EMA crossover failed — silver is more volatile than gold. Need wider SL for silver trades."),
        ("SEED-018", "MCX:CRUDEOIL", "BUY", "pullback_support", 6200, 6050, 6500, 2.0, 65, "WATCHLIST", "WIN", 6480, 4.5, 6, "MCX",
         "Crude pullback to support held — commodity pullbacks work when global trend is up."),
        ("SEED-019", "MCX:NATURALGAS", "SELL", "breakdown", 180, 190, 160, 2.0, 58, "WATCHLIST", "WIN", 162, 10.0, 7, "MCX",
         "Natural gas breakdown — highly volatile, but clean breakdowns work. Use tight SL on NG."),
        ("SEED-020", "MCX:COPPER", "BUY", "smc_bos", 750, 730, 790, 2.0, 64, "WATCHLIST", "BREAKEVEN", 751, 0.1, 10, "MCX",
         "Copper BOS was flat — base metals can range for weeks. Be patient or use time-based exit."),

        # CDS Currency
        ("SEED-021", "CDS:USDINR", "BUY", "breakout_volume", 83.50, 83.20, 84.10, 2.0, 66, "WATCHLIST", "WIN", 84.05, 0.7, 5, "CDS",
         "USDINR breakout during FII outflow. Currency moves are small but reliable on FII flow confirmation."),
        ("SEED-022", "CDS:EURINR", "SELL", "ema_crossover", 90.50, 91.20, 89.10, 2.0, 55, "WATCHLIST", "LOSS", 91.30, -0.9, 3, "CDS",
         "EURINR short failed — RBI intervention risk. Don't trade currency against central bank sentiment."),

        # NFO Derivatives
        ("SEED-023", "NFO:NIFTY", "BUY", "pullback_support", 22500, 22300, 23000, 2.5, 70, "ALERT", "WIN", 22950, 2.0, 2, "NFO",
         "Nifty pullback to 20EMA — index supports are highly reliable. 2:1 RRR sufficient for Nifty options."),
        ("SEED-024", "NFO:BANKNIFTY", "SELL", "smc_choch", 48000, 48500, 47000, 2.0, 62, "WATCHLIST", "WIN", 47200, 1.7, 1, "NFO",
         "BankNifty CHoCH on hourly — expiry day momentum is strong. Short only with SMC confirmation."),
        ("SEED-025", "NFO:NIFTY", "BUY", "gap_fill", 22200, 22050, 22500, 2.0, 57, "WATCHLIST", "LOSS", 22030, -0.8, 1, "NFO",
         "Nifty gap fill failed on expiry — expiry day is unpredictable. Avoid gap fills on Thursday/expiry."),

        # More NSE diversity — various patterns
        ("SEED-026", "NSE:SUNPHARMA", "BUY", "harmonic_gartley", 1200, 1160, 1320, 3.0, 69, "WATCHLIST", "WIN", 1310, 9.2, 13, "NSE",
         "Harmonic Gartley on pharma — defensive sector harmonics are reliable in volatile markets."),
        ("SEED-027", "NSE:WIPRO", "BUY", "pullback_support", 450, 435, 495, 3.0, 64, "WATCHLIST", "BREAKEVEN", 452, 0.4, 8, "NSE",
         "WIPRO pullback was tepid — IT under pressure. Pullbacks don't work when sector is WEAK."),
        ("SEED-028", "NSE:MARUTI", "BUY", "breakout_volume", 10500, 10200, 11400, 3.0, 76, "ALERT", "WIN", 11350, 8.1, 15, "NSE",
         "Maruti breakout with auto sector rotation. High conviction breakouts on leaders deliver."),
        ("SEED-029", "NSE:LT", "BUY", "smc_order_block", 3200, 3100, 3500, 3.0, 71, "ALERT", "WIN", 3460, 8.1, 11, "NSE",
         "L&T order block re-test — infra sector strong. Infra stocks respect institutional levels."),
        ("SEED-030", "NSE:TATASTEEL", "SELL", "vsa_climax", 130, 135, 120, 2.0, 63, "WATCHLIST", "WIN", 121, 6.9, 9, "NSE",
         "Steel sector reversal marked by volume climax. Metals are cyclical — trust sector cycle tops."),

        # More losses for realistic distribution
        ("SEED-031", "NSE:ASIANPAINT", "BUY", "pullback_support", 3200, 3100, 3500, 3.0, 60, "WATCHLIST", "LOSS", 3090, -3.4, 4, "NSE",
         "ASIANPAINT pullback broke through support — FMCG in distribution phase. Verify accumulation first."),
        ("SEED-032", "NSE:NESTLEIND", "BUY", "ema_crossover", 24000, 23400, 25800, 3.0, 56, "WATCHLIST", "LOSS", 23350, -2.7, 6, "NSE",
         "Nestleind EMA crossover in rangebound market — crossovers fail in ranges. Need trending context."),
        ("SEED-033", "NSE:TITAN", "BUY", "harmonic_butterfly", 3100, 3000, 3400, 3.0, 62, "WATCHLIST", "LOSS", 2990, -3.5, 5, "NSE",
         "Harmonic butterfly on TITAN failed — consumer discretionary weakness. Harmonics need sector support."),
        ("SEED-034", "NSE:CIPLA", "SELL", "breakdown", 1400, 1430, 1340, 2.0, 54, "WATCHLIST", "LOSS", 1435, -2.5, 3, "NSE",
         "Pharma short failed — defensive sector doesn't break down easily in volatile markets."),
        ("SEED-035", "NSE:ADANIPORTS", "BUY", "breakout_volume", 800, 770, 870, 2.3, 58, "WATCHLIST", "LOSS", 765, -4.4, 3, "NSE",
         "Adani group breakout was speculative — avoid high-volatility group momentum. Wait for confirmation."),

        # More wins
        ("SEED-036", "NSE:NTPC", "BUY", "smc_bos", 280, 270, 310, 3.0, 73, "ALERT", "WIN", 308, 10.0, 12, "NSE",
         "Power sector BOS — PSU power stocks in structural uptrend. Government capex thesis intact."),
        ("SEED-037", "NSE:COALINDIA", "BUY", "pullback_support", 420, 405, 465, 3.0, 67, "WATCHLIST", "WIN", 460, 9.5, 14, "NSE",
         "Coal India pullback in energy sector bull run. PSU energy names respect support levels well."),
        ("SEED-038", "NSE:KOTAKBANK", "BUY", "wyckoff_spring", 1800, 1750, 1950, 3.0, 71, "ALERT", "WIN", 1940, 7.8, 9, "NSE",
         "Wyckoff spring on Kotak — private banks accumulate at key levels. Spring signals reliable for PVTBANKS."),
        ("SEED-039", "NSE:BHARTIARTL", "BUY", "breakout_volume", 1500, 1450, 1650, 3.0, 78, "ALERT", "WIN", 1640, 9.3, 10, "NSE",
         "Telecom monopoly breakout — limited competition means reliable breakouts. Sector structure matters."),
        ("SEED-040", "NSE:DRREDDY", "BUY", "harmonic_bat", 5500, 5350, 5950, 3.0, 65, "WATCHLIST", "WIN", 5900, 7.3, 16, "NSE",
         "Harmonic bat on DR REDDY — pharma harmonics work in stable market conditions. Patience needed."),

        # Breakevens
        ("SEED-041", "NSE:EICHERMOT", "BUY", "pullback_support", 4200, 4080, 4560, 3.0, 63, "WATCHLIST", "BREAKEVEN", 4210, 0.2, 12, "NSE",
         "Eicher pullback went nowhere — auto stock in consolidation. Don't force trades in sideways markets."),
        ("SEED-042", "NSE:GRASIM", "BUY", "ema_crossover", 2200, 2130, 2410, 3.0, 59, "WATCHLIST", "BREAKEVEN", 2205, 0.2, 10, "NSE",
         "Grasim EMA crossover flat — cement in neutral regime. Time-based exit saved capital."),
        ("SEED-043", "MCX:GOLD", "SELL", "vsa_climax", 59000, 59800, 57400, 2.0, 61, "WATCHLIST", "BREAKEVEN", 58950, 0.1, 5, "MCX",
         "Gold short breakeven — safe haven demand absorbed selling. Don't short gold in uncertainty."),

        # More MCX
        ("SEED-044", "MCX:SILVER", "BUY", "smc_bos", 73000, 71500, 77000, 2.7, 68, "WATCHLIST", "WIN", 76500, 4.8, 8, "MCX",
         "Silver BOS with gold correlation — trade silver when gold is trending. Correlation adds conviction."),
        ("SEED-045", "MCX:CRUDEOIL", "SELL", "breakdown", 6400, 6550, 6100, 2.0, 59, "WATCHLIST", "WIN", 6150, 3.9, 4, "MCX",
         "Crude breakdown on global demand concerns. Follow geopolitical context for commodity shorts."),

        # More CDS
        ("SEED-046", "CDS:USDINR", "SELL", "pullback_support", 84.00, 84.30, 83.40, 2.0, 63, "WATCHLIST", "WIN", 83.50, 0.6, 4, "CDS",
         "USDINR short during FII inflow + RBI selling. Currency with flow confirmation is reliable."),

        # More NFO
        ("SEED-047", "NFO:BANKNIFTY", "BUY", "breakout_volume", 47500, 47000, 48500, 2.0, 72, "ALERT", "WIN", 48400, 1.9, 1, "NFO",
         "BankNifty breakout with banking sector strength. Index options need sector confirmation."),

        # Edge cases
        ("SEED-048", "NSE:DABUR", "BUY", "ema_crossover", 560, 545, 600, 2.7, 52, "WATCHLIST", "LOSS", 542, -3.2, 5, "NSE",
         "Low conviction FMCG trade lost — don't take WATCHLIST signals on defensive stocks. Need ALERT level."),
        ("SEED-049", "NSE:JINDALSTEL", "BUY", "breakout_volume", 680, 650, 770, 3.0, 80, "ALERT", "WIN", 760, 11.8, 7, "NSE",
         "High conviction metal breakout — Jindal Steel with strong volume and FII buying. Trust high conviction."),
        ("SEED-050", "NSE:ITC", "BUY", "wyckoff_spring", 440, 425, 485, 3.0, 69, "WATCHLIST", "WIN", 478, 8.6, 18, "NSE",
         "ITC Wyckoff spring — slow-moving FMCG accumulates patiently. Spring signals need time to play out."),
    ]

    records = []
    for s in seeds:
        records.append(TradeRecord(
            signal_id=s[0],
            ticker=s[1],
            direction=s[2],
            pattern=s[3],
            entry_price=s[4],
            stop_loss=s[5],
            target=s[6],
            rrr=s[7],
            confidence=s[8],
            recommendation=s[9],
            outcome=s[10],
            exit_price=s[11],
            pnl_pct=s[12],
            holding_days=s[13],
            exchange=s[14],
            lesson=s[15],
            reflected=True,
            timestamp="2026-01-15T09:30:00",
        ))

    return records
