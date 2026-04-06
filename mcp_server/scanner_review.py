"""
MKUMARAN Trading OS — Scanner Review Engine

EOD analysis that cross-references scanner predictions against actual
market results.  Runs at 15:45 IST (after NSE close) and computes
per-scanner hit rates, missed opportunities, false positives, and
promoted-stock accuracy.

Persistence: PostgreSQL (ScannerReview table), JSON file, Google Sheets.
Notification: Telegram EOD summary.
"""

import asyncio
import json
import logging
import re
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from mcp_server.config import settings
from mcp_server.db import SessionLocal
from mcp_server.market_calendar import is_weekend, is_market_holiday, now_ist
from mcp_server.mwa_scanner import SCANNERS, SIGNAL_CHAINS

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────
_REVIEW_JSON_PATH = Path("data/scanner_review.json")
_MAX_JSON_DAYS = 90
_review_cache: dict[str, bool] = {}  # date-str → True (idempotency guard)


# ══════════════════════════════════════════════════════════════
# Helper utilities
# ══════════════════════════════════════════════════════════════

def _normalize_ticker(ticker: str) -> str:
    """Strip exchange prefixes/suffixes for matching: NSE:RELIANCE, RELIANCE.NS → RELIANCE."""
    t = ticker.strip().upper()
    t = re.sub(r"^(NSE|BSE|MCX|CDS|NFO):", "", t)
    t = re.sub(r"\.(NS|BO|MC)$", "", t)
    t = re.sub(r"=X$", "", t)
    return t


def _classify_scanner(key: str) -> str:
    """Return BULL / BEAR / FILTER from SCANNERS dict."""
    cfg = SCANNERS.get(key, {})
    return cfg.get("type", "UNKNOWN")


def _get_scanner_segment(key: str) -> str:
    """Return primary segment for a scanner (NSE/MCX/CDS/NFO)."""
    cfg = SCANNERS.get(key, {})
    layer = cfg.get("layer", "")
    if layer == "Forex":
        return "CDS"
    if layer == "Commodity":
        return "MCX"
    # Check scanner key prefix conventions
    if key.startswith("forex_") or key.startswith("cds_"):
        return "CDS"
    if key.startswith("mcx_") or key.startswith("commodity_"):
        return "MCX"
    return "NSE"


# ══════════════════════════════════════════════════════════════
# ScannerReviewEngine
# ══════════════════════════════════════════════════════════════

class ScannerReviewEngine:
    """EOD cross-reference engine: scanners vs market actuals."""

    # ── Phase A — Data Collection ────────────────────────────

    @staticmethod
    def _get_scanner_predictions(db: Session, review_date: date) -> dict | None:
        """Read today's MWAScore from DB."""
        from mcp_server.models import MWAScore

        row = db.query(MWAScore).filter(MWAScore.score_date == review_date).first()
        if not row:
            return None
        return {
            "direction": row.direction,
            "bull_pct": float(row.bull_pct or 0),
            "bear_pct": float(row.bear_pct or 0),
            "scanner_results": row.scanner_results or {},
            "promoted_stocks": row.promoted_stocks or [],
        }

    @staticmethod
    def _get_market_actuals() -> dict:
        """Fetch gainers/losers/most_active via existing market-movers helper."""
        from mcp_server.mcp_server import _fetch_market_movers

        try:
            return _fetch_market_movers()
        except Exception as exc:
            logger.error("Failed to fetch market movers for review: %s", exc)
            return {}

    @staticmethod
    def _get_todays_signals(db: Session, review_date: date) -> list[dict]:
        from mcp_server.models import Signal

        rows = db.query(Signal).filter(Signal.signal_date == review_date).all()
        return [
            {
                "ticker": _normalize_ticker(r.ticker or ""),
                "direction": r.direction,
                "pattern": r.pattern,
                "ai_confidence": r.ai_confidence,
                "status": r.status,
            }
            for r in rows
        ]

    @staticmethod
    def _get_todays_outcomes(db: Session, review_date: date) -> list[dict]:
        from mcp_server.models import Outcome

        rows = db.query(Outcome).filter(Outcome.exit_date == review_date).all()
        return [
            {
                "signal_id": r.signal_id,
                "outcome": r.outcome,
                "pnl_amount": float(r.pnl_amount or 0),
                "exit_reason": r.exit_reason,
            }
            for r in rows
        ]

    # ── Phase B — Cross-Reference Analysis ───────────────────

    @staticmethod
    def _extract_tickers_from_result(result) -> set[str]:
        """Extract normalized ticker set from a scanner result (list or dict)."""
        tickers: set[str] = set()
        if isinstance(result, list):
            for item in result:
                if isinstance(item, str):
                    tickers.add(_normalize_ticker(item))
                elif isinstance(item, dict):
                    t = item.get("ticker") or item.get("symbol") or item.get("name", "")
                    if t:
                        tickers.add(_normalize_ticker(t))
        elif isinstance(result, dict):
            stocks = result.get("stocks", [])
            for s in stocks:
                if isinstance(s, str):
                    tickers.add(_normalize_ticker(s))
                elif isinstance(s, dict):
                    t = s.get("ticker") or s.get("symbol") or s.get("name", "")
                    if t:
                        tickers.add(_normalize_ticker(t))
        return tickers

    @staticmethod
    def _calculate_scanner_hit_rates(
        scanner_results: dict,
        gainers: list[dict],
        losers: list[dict],
    ) -> dict:
        """Per-scanner: hit_rate, precision, false_positive_rate."""
        gainer_tickers = {_normalize_ticker(g["ticker"]) for g in gainers}
        loser_tickers = {_normalize_ticker(lo["ticker"]) for lo in losers}

        hit_rates: dict[str, dict] = {}

        for key in SCANNERS:
            result = scanner_results.get(key)
            flagged = ScannerReviewEngine._extract_tickers_from_result(result)
            total_flagged = len(flagged)
            scanner_type = _classify_scanner(key)

            if scanner_type == "BULL":
                caught = flagged & gainer_tickers
                false_pos = flagged & loser_tickers
            elif scanner_type == "BEAR":
                caught = flagged & loser_tickers
                false_pos = flagged & gainer_tickers
            else:
                # FILTER / UNKNOWN — skip hit rate
                hit_rates[key] = {
                    "type": scanner_type,
                    "segment": _get_scanner_segment(key),
                    "total_flagged": total_flagged,
                    "hit_rate": None,
                    "precision": None,
                    "false_positive_rate": None,
                }
                continue

            hit_count = len(caught)
            fp_count = len(false_pos)

            if total_flagged > 0:
                hit_rate = round(hit_count / total_flagged * 100, 1)
                precision = round(hit_count / total_flagged * 100, 1)
                fp_rate = round(fp_count / total_flagged * 100, 1)
            else:
                hit_rate = None
                precision = None
                fp_rate = None

            hit_rates[key] = {
                "type": scanner_type,
                "segment": _get_scanner_segment(key),
                "total_flagged": total_flagged,
                "caught": list(caught),
                "false_positives": list(false_pos),
                "hit_rate": hit_rate,
                "precision": precision,
                "false_positive_rate": fp_rate,
            }

        return hit_rates

    @staticmethod
    def _find_missed_opportunities(
        scanner_results: dict,
        gainers: list[dict],
    ) -> list[dict]:
        """Top gainers not flagged by ANY bull scanner."""
        # Collect all tickers flagged by at least one BULL scanner
        all_bull_flagged: set[str] = set()
        for key, cfg in SCANNERS.items():
            if cfg.get("type") != "BULL":
                continue
            result = scanner_results.get(key)
            all_bull_flagged |= ScannerReviewEngine._extract_tickers_from_result(result)

        missed = []
        for g in gainers[:10]:  # Top 10 gainers
            ticker = _normalize_ticker(g["ticker"])
            if ticker not in all_bull_flagged:
                missed.append({
                    "ticker": g["ticker"],
                    "pct_change": g.get("pct_change", 0),
                    "exchange": g.get("exchange", "NSE"),
                })
        return missed

    @staticmethod
    def _find_false_positives(
        scanner_results: dict,
        gainers: list[dict],
        losers: list[dict],
    ) -> list[dict]:
        """Stocks flagged by 3+ bull scanners but ended negative."""
        loser_tickers = {_normalize_ticker(lo["ticker"]): lo for lo in losers}

        # Count bull-scanner hits per ticker
        ticker_bull_count: dict[str, int] = {}
        for key, cfg in SCANNERS.items():
            if cfg.get("type") != "BULL":
                continue
            result = scanner_results.get(key)
            for t in ScannerReviewEngine._extract_tickers_from_result(result):
                ticker_bull_count[t] = ticker_bull_count.get(t, 0) + 1

        false_pos = []
        for ticker, count in ticker_bull_count.items():
            if count >= 3 and ticker in loser_tickers:
                lo = loser_tickers[ticker]
                false_pos.append({
                    "ticker": lo["ticker"],
                    "bull_scanner_count": count,
                    "pct_change": lo.get("pct_change", 0),
                    "exchange": lo.get("exchange", "NSE"),
                })

        return sorted(false_pos, key=lambda x: x["bull_scanner_count"], reverse=True)

    @staticmethod
    def _calculate_segment_performance(scanner_hit_rates: dict) -> dict:
        """Aggregate hit rates per segment (NSE/MCX/CDS)."""
        segments: dict[str, list[float]] = {}
        for key, data in scanner_hit_rates.items():
            seg = data.get("segment", "NSE")
            hr = data.get("hit_rate")
            if hr is not None:
                segments.setdefault(seg, []).append(hr)

        result = {}
        for seg, rates in segments.items():
            result[seg] = {
                "avg_hit_rate": round(sum(rates) / len(rates), 1) if rates else 0,
                "scanner_count": len(rates),
                "best": round(max(rates), 1) if rates else 0,
                "worst": round(min(rates), 1) if rates else 0,
            }
        return result

    @staticmethod
    def _calculate_chain_accuracy(
        scanner_results: dict,
        gainers: list[dict],
        losers: list[dict],
    ) -> dict:
        """Signal chain intersection vs actual movers."""
        gainer_tickers = {_normalize_ticker(g["ticker"]) for g in gainers}
        loser_tickers = {_normalize_ticker(lo["ticker"]) for lo in losers}

        chain_results: dict[str, dict] = {}

        for chain_name, chain_cfg in SIGNAL_CHAINS.items():
            chain_scanners = chain_cfg.get("scanners", [])

            # For each chain, find stocks that appear in ALL chain scanners
            sets: list[set[str]] = []
            for skey in chain_scanners:
                result = scanner_results.get(skey)
                tickers = ScannerReviewEngine._extract_tickers_from_result(result)
                sets.append(tickers)

            if not sets:
                chain_results[chain_name] = {"fired": False, "intersection": []}
                continue

            intersection = sets[0]
            for s in sets[1:]:
                intersection = intersection & s

            if not intersection:
                chain_results[chain_name] = {"fired": False, "intersection": []}
                continue

            # Determine chain direction from chain name heuristic
            is_bull = any(
                w in chain_name.lower()
                for w in ("long", "bull", "breakout", "momentum", "spring", "positional")
            )
            is_bear = any(
                w in chain_name.lower()
                for w in ("short", "bear", "distribution")
            )

            if is_bull:
                caught = intersection & gainer_tickers
            elif is_bear:
                caught = intersection & loser_tickers
            else:
                caught = (intersection & gainer_tickers) | (intersection & loser_tickers)

            chain_results[chain_name] = {
                "fired": True,
                "intersection": list(intersection),
                "caught": list(caught),
                "hit_rate": round(len(caught) / len(intersection) * 100, 1) if intersection else 0,
            }

        return chain_results

    @staticmethod
    def _calculate_promoted_performance(
        promoted_stocks: list,
        gainers: list[dict],
        losers: list[dict],
    ) -> dict:
        """How many promoted stocks were actual gainers."""
        if not promoted_stocks:
            return {"total": 0, "hit": 0, "hit_pct": 0, "gainers": [], "losers": []}

        gainer_tickers = {_normalize_ticker(g["ticker"]) for g in gainers}
        loser_tickers = {_normalize_ticker(lo["ticker"]) for lo in losers}

        promoted_norm = [_normalize_ticker(p) if isinstance(p, str) else _normalize_ticker(p.get("ticker", "")) for p in promoted_stocks]

        hit = [t for t in promoted_norm if t in gainer_tickers]
        miss = [t for t in promoted_norm if t in loser_tickers]

        total = len(promoted_norm)
        hit_count = len(hit)

        return {
            "total": total,
            "hit": hit_count,
            "hit_pct": round(hit_count / total * 100, 1) if total > 0 else 0,
            "gainers": hit,
            "losers": miss,
        }

    # ── Build review ─────────────────────────────────────────

    def _build_review(
        self,
        review_date: date,
        predictions: dict,
        actuals: dict,
        signals: list[dict],
        outcomes: list[dict],
    ) -> dict:
        """Orchestrate all analysis into a single review dict."""
        scanner_results = predictions.get("scanner_results", {})
        promoted_stocks = predictions.get("promoted_stocks", [])

        gainers = actuals.get("gainers", [])
        losers = actuals.get("losers", [])

        # Core analysis
        scanner_hit_rates = self._calculate_scanner_hit_rates(scanner_results, gainers, losers)
        missed = self._find_missed_opportunities(scanner_results, gainers)
        false_pos = self._find_false_positives(scanner_results, gainers, losers)
        segment_perf = self._calculate_segment_performance(scanner_hit_rates)
        chain_acc = self._calculate_chain_accuracy(scanner_results, gainers, losers)
        promoted_perf = self._calculate_promoted_performance(promoted_stocks, gainers, losers)

        # Compute overall hit rate (average of all scanners with data)
        valid_rates = [
            v["hit_rate"] for v in scanner_hit_rates.values()
            if v.get("hit_rate") is not None and v.get("total_flagged", 0) > 0
        ]
        overall_hit_rate = round(sum(valid_rates) / len(valid_rates), 1) if valid_rates else 0

        # Best / worst scanners (only those with >= 1 flagged stock)
        ranked = sorted(
            [
                {"scanner": k, **v}
                for k, v in scanner_hit_rates.items()
                if v.get("hit_rate") is not None and v.get("total_flagged", 0) > 0
            ],
            key=lambda x: x["hit_rate"],
            reverse=True,
        )
        best = ranked[:5]
        worst = ranked[-5:] if len(ranked) >= 5 else ranked[::-1][:5]

        return {
            "review_date": str(review_date),
            "market_direction": predictions.get("direction", "NEUTRAL"),
            "bull_pct": predictions.get("bull_pct", 0),
            "bear_pct": predictions.get("bear_pct", 0),
            "overall_hit_rate": overall_hit_rate,
            "scanner_hit_rates": scanner_hit_rates,
            "missed_opportunities": missed,
            "top10_total": min(10, len(gainers)),
            "false_positives": false_pos,
            "segment_performance": segment_perf,
            "chain_accuracy": chain_acc,
            "promoted_performance": promoted_perf,
            "best_scanners": best,
            "worst_scanners": worst,
            "signals_today": len(signals),
            "outcomes_today": len(outcomes),
            "total_gainers": len(gainers),
            "total_losers": len(losers),
        }

    # ── Phase C — Persistence & Notification ─────────────────

    @staticmethod
    def _persist_to_db(db: Session, review_data: dict) -> bool:
        """INSERT or UPDATE ScannerReview row (upsert by date)."""
        from mcp_server.models import ScannerReview

        try:
            rd = review_data["review_date"]
            existing = db.query(ScannerReview).filter(
                ScannerReview.review_date == rd,
            ).first()

            if existing:
                existing.market_direction = review_data.get("market_direction")
                existing.overall_hit_rate = review_data.get("overall_hit_rate")
                existing.scanner_hit_rates = review_data.get("scanner_hit_rates")
                existing.missed_opportunities = review_data.get("missed_opportunities")
                existing.false_positives = review_data.get("false_positives")
                existing.segment_performance = review_data.get("segment_performance")
                existing.chain_accuracy = review_data.get("chain_accuracy")
                existing.promoted_performance = review_data.get("promoted_performance")
                existing.best_scanners = review_data.get("best_scanners")
                existing.worst_scanners = review_data.get("worst_scanners")
                existing.review_payload = review_data
            else:
                row = ScannerReview(
                    review_date=rd,
                    market_direction=review_data.get("market_direction"),
                    overall_hit_rate=review_data.get("overall_hit_rate"),
                    scanner_hit_rates=review_data.get("scanner_hit_rates"),
                    missed_opportunities=review_data.get("missed_opportunities"),
                    false_positives=review_data.get("false_positives"),
                    segment_performance=review_data.get("segment_performance"),
                    chain_accuracy=review_data.get("chain_accuracy"),
                    promoted_performance=review_data.get("promoted_performance"),
                    best_scanners=review_data.get("best_scanners"),
                    worst_scanners=review_data.get("worst_scanners"),
                    review_payload=review_data,
                )
                db.add(row)

            db.commit()
            logger.info("Scanner review persisted to DB for %s", rd)
            return True
        except Exception as exc:
            db.rollback()
            logger.error("DB persist failed for scanner review: %s", exc)
            return False

    @staticmethod
    def _persist_to_json(review_data: dict) -> bool:
        """Append to data/scanner_review.json, auto-prune >90 days."""
        try:
            _REVIEW_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)

            history: list[dict] = []
            if _REVIEW_JSON_PATH.exists():
                try:
                    history = json.loads(_REVIEW_JSON_PATH.read_text())
                    if not isinstance(history, list):
                        history = []
                except (json.JSONDecodeError, OSError):
                    history = []

            # Deduplicate by date
            rd = review_data["review_date"]
            history = [h for h in history if h.get("review_date") != rd]
            history.append(review_data)

            # Prune entries older than 90 days
            cutoff = str(date.today() - timedelta(days=_MAX_JSON_DAYS))
            history = [h for h in history if h.get("review_date", "") >= cutoff]

            _REVIEW_JSON_PATH.write_text(json.dumps(history, indent=2, default=str))
            logger.info("Scanner review saved to JSON (%d entries)", len(history))
            return True
        except Exception as exc:
            logger.error("JSON persist failed for scanner review: %s", exc)
            return False

    @staticmethod
    def _persist_to_sheets(review_data: dict) -> bool:
        """Log review to Google Sheets."""
        try:
            from mcp_server.sheets_sync import log_scanner_review
            return log_scanner_review(review_data)
        except Exception as exc:
            logger.warning("Sheets persist skipped: %s", exc)
            return False

    @staticmethod
    async def _send_telegram_summary(review_data: dict) -> bool:
        """Format and send Telegram EOD summary."""
        try:
            from mcp_server.telegram_bot import send_telegram_message

            msg = format_telegram_review(review_data)
            await send_telegram_message(msg, force=True)
            logger.info("Telegram review summary sent")
            return True
        except Exception as exc:
            logger.warning("Telegram summary skipped: %s", exc)
            return False

    # ── Main Entry ───────────────────────────────────────────

    async def run_review(self, for_date: date | None = None) -> dict:
        """Full review pipeline with guards (weekend/holiday/no-data)."""
        review_date = for_date or now_ist().date()

        # Guard: weekend
        if is_weekend(review_date):
            return {"status": "skipped", "reason": "weekend_or_holiday", "review_date": str(review_date)}

        # Guard: market holiday
        if is_market_holiday("NSE", review_date):
            return {"status": "skipped", "reason": "weekend_or_holiday", "review_date": str(review_date)}

        db = SessionLocal()
        try:
            # Phase A: collect data
            predictions = self._get_scanner_predictions(db, review_date)
            if not predictions:
                return {"status": "no_data", "reason": "no_mwa_scan_today", "review_date": str(review_date)}

            actuals = self._get_market_actuals()
            if not actuals or not actuals.get("gainers"):
                return {"status": "no_data", "reason": "no_market_data", "review_date": str(review_date)}

            signals = self._get_todays_signals(db, review_date)
            outcomes = self._get_todays_outcomes(db, review_date)

            # Phase B: analysis
            review_data = self._build_review(review_date, predictions, actuals, signals, outcomes)
            review_data["status"] = "completed"

            # Phase C: persist (non-blocking — continue on failure)
            self._persist_to_db(db, review_data)
            self._persist_to_json(review_data)
            self._persist_to_sheets(review_data)
            await self._send_telegram_summary(review_data)

            return review_data
        finally:
            db.close()


# ══════════════════════════════════════════════════════════════
# Rolling Analytics (reads from JSON history)
# ══════════════════════════════════════════════════════════════

def _load_json_history() -> list[dict]:
    """Load review history from JSON file."""
    if not _REVIEW_JSON_PATH.exists():
        return []
    try:
        data = json.loads(_REVIEW_JSON_PATH.read_text())
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def get_rolling_stats(days: int = 30) -> dict:
    """30-day avg hit_rate/precision per scanner from JSON history."""
    history = _load_json_history()
    cutoff = str(date.today() - timedelta(days=days))
    recent = [h for h in history if h.get("review_date", "") >= cutoff]

    if not recent:
        return {"days": days, "entries": 0, "scanners": {}}

    # Aggregate per-scanner stats
    scanner_stats: dict[str, list[float]] = {}
    for entry in recent:
        for key, data in entry.get("scanner_hit_rates", {}).items():
            hr = data.get("hit_rate")
            if hr is not None:
                scanner_stats.setdefault(key, []).append(hr)

    result: dict[str, dict] = {}
    for key, rates in scanner_stats.items():
        result[key] = {
            "avg_hit_rate": round(sum(rates) / len(rates), 1),
            "max_hit_rate": round(max(rates), 1),
            "min_hit_rate": round(min(rates), 1),
            "data_points": len(rates),
        }

    return {"days": days, "entries": len(recent), "scanners": result}


def get_leaderboard(days: int = 30) -> list[dict]:
    """Scanners ranked by rolling performance."""
    stats = get_rolling_stats(days)
    scanners = stats.get("scanners", {})

    ranked = sorted(
        [
            {"scanner": k, **v, "type": _classify_scanner(k), "segment": _get_scanner_segment(k)}
            for k, v in scanners.items()
        ],
        key=lambda x: x["avg_hit_rate"],
        reverse=True,
    )
    return ranked


# ══════════════════════════════════════════════════════════════
# Telegram Formatter
# ══════════════════════════════════════════════════════════════

def format_telegram_review(review: dict) -> str:
    """Format EOD review into a Telegram-friendly message."""
    direction = review.get("market_direction", "NEUTRAL")
    rd = review.get("review_date", "")
    hit_rate = review.get("overall_hit_rate", 0)
    bull_pct = review.get("bull_pct", 0)
    bear_pct = review.get("bear_pct", 0)

    best = review.get("best_scanners", [])
    worst = review.get("worst_scanners", [])
    missed = review.get("missed_opportunities", [])
    fp = review.get("false_positives", [])
    promoted = review.get("promoted_performance", {})

    lines = [
        f"📊 EOD Scanner Review — {rd}",
        f"Direction: {direction} | Bull {bull_pct}% | Bear {bear_pct}%",
        f"Overall Hit Rate: {hit_rate}%",
        "",
    ]

    # Best scanners
    if best:
        lines.append("✅ Best Scanners:")
        for b in best[:3]:
            lines.append(f"  • {b['scanner']}: {b['hit_rate']}% ({b.get('total_flagged', 0)} flagged)")

    # Worst scanners
    if worst:
        lines.append("❌ Worst Scanners:")
        for w in worst[:3]:
            lines.append(f"  • {w['scanner']}: {w['hit_rate']}% ({w.get('total_flagged', 0)} flagged)")

    # Promoted performance
    if promoted.get("total", 0) > 0:
        lines.append(f"\n🏆 Promoted: {promoted['hit']}/{promoted['total']} hit ({promoted['hit_pct']}%)")

    # Missed opportunities
    if missed:
        tickers = ", ".join(m["ticker"] for m in missed[:5])
        lines.append(f"\n⚠️ Missed (top gainers): {tickers}")

    # False positives
    if fp:
        tickers = ", ".join(f["ticker"] for f in fp[:5])
        lines.append(f"🚫 False Positives (3+ bull, ended -ve): {tickers}")

    # Segment performance
    seg_perf = review.get("segment_performance", {})
    if seg_perf:
        lines.append("\n📈 Segment Performance:")
        for seg, data in seg_perf.items():
            lines.append(f"  {seg}: avg {data['avg_hit_rate']}% ({data['scanner_count']} scanners)")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# Background Loop (module-level)
# ══════════════════════════════════════════════════════════════

async def scanner_review_loop():
    """Run every 60s, trigger review at 15:45 IST. Follows _auto_scan_loop() pattern."""
    review_hour = getattr(settings, "SCANNER_REVIEW_HOUR", 15)
    review_minute = 45

    while True:
        try:
            now = now_ist()
            today_str = str(now.date())

            # Only trigger at the configured time, and only once per day
            if (
                now.hour == review_hour
                and now.minute == review_minute
                and today_str not in _review_cache
            ):
                logger.info("Scanner review triggered at %s", now.isoformat())
                _review_cache[today_str] = True

                engine = ScannerReviewEngine()
                result = await engine.run_review()
                logger.info("Scanner review result: %s", result.get("status", "unknown"))

        except Exception as exc:
            logger.error("Scanner review loop error: %s", exc)

        await asyncio.sleep(60)
