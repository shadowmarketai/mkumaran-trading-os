"""Scanners — pattern detection, MWA breadth, tier monitors, scanner review.

Extracted from mcp_server.mcp_server in Phase 3a of the router split.
17 routes moved verbatim.

Clusters:
  - Market data primitives (/tools/get_stock_data, /api/chart/*)
  - Pattern detection engines (SMC, Wyckoff, VSA, Harmonic, RL, Pattern)
  - MWA breadth scan (current, historical, job-based async runner)
  - Tier monitors (T2 watchlist / T3 active trades)
  - Scanner review engine (today / history / leaderboard / run)

Deferred imports: `_mwa_jobs`, `_run_mwa_scan_background`, `_now_ist`
still live in mcp_server.py — they're shared module-level state /
utilities used by both routes and the lifespan scheduled task.
"""
import asyncio
import logging
from dataclasses import asdict
from datetime import date

import pandas as pd
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import desc
from sqlalchemy.orm import Session

from mcp_server.asset_registry import get_asset_class, parse_ticker
from mcp_server.db import get_db
from mcp_server.models import MWAScore, ScannerReview
from mcp_server.routers.deps import limiter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["scanners"])


# ── Market data primitives ─────────────────────────────────────────


@router.post("/tools/get_stock_data")
async def tool_get_stock_data(
    ticker: str,
    timeframe: str = "day",
    days: int = 365,
):
    """Get OHLCV data for any instrument via yfinance. Supports NSE, BSE, MCX, CDS, NFO."""
    from mcp_server.nse_scanner import get_stock_data

    df = await asyncio.to_thread(get_stock_data, ticker, "1y", "1d")
    if df is None or df.empty:
        return {"status": "error", "message": f"No data for {ticker}"}

    exchange_str, symbol = parse_ticker(ticker)

    return {
        "status": "ok",
        "tool": "get_stock_data",
        "ticker": ticker,
        "exchange": exchange_str,
        "asset_class": get_asset_class(ticker).value,
        "timeframe": timeframe,
        "bars": len(df),
        "latest": {
            "date": str(df.index[-1]),
            "open": round(float(df["open"].iloc[-1]), 2),
            "high": round(float(df["high"].iloc[-1]), 2),
            "low": round(float(df["low"].iloc[-1]), 2),
            "close": round(float(df["close"].iloc[-1]), 2),
            "volume": int(df["volume"].iloc[-1]),
        },
    }


@router.get("/api/chart/{ticker:path}")
async def api_chart_ohlcv(
    ticker: str,
    interval: str = Query("1D", pattern="^(1m|5m|15m|1h|1H|1D|1d)$"),
    days: int = Query(30, ge=1, le=365),
):
    """Return chart-ready OHLCV bars for lightweight-charts frontend."""
    from mcp_server.data_provider import get_stock_data

    _interval_map = {
        "1m": "1m", "5m": "5m", "15m": "15m",
        "1h": "1h", "1H": "1h", "1D": "1d", "1d": "1d",
    }
    data_interval = _interval_map.get(interval, "1d")

    if days <= 5:
        period = "5d"
    elif days <= 30:
        period = "1mo"
    elif days <= 90:
        period = "3mo"
    elif days <= 180:
        period = "6mo"
    else:
        period = "1y"

    df = await asyncio.to_thread(get_stock_data, ticker, period, data_interval)
    if df is None or df.empty:
        return {"status": "error", "bars": [], "message": f"No data for {ticker}"}

    bars = []
    for idx, row in df.iterrows():
        ts = idx
        if hasattr(ts, "timestamp"):
            time_val = int(ts.timestamp())
        else:
            time_val = int(pd.Timestamp(ts).timestamp()) if ts else 0
        bars.append({
            "time": time_val,
            "open": round(float(row["open"]), 2),
            "high": round(float(row["high"]), 2),
            "low": round(float(row["low"]), 2),
            "close": round(float(row["close"]), 2),
            "volume": int(row["volume"]) if "volume" in row and row["volume"] == row["volume"] else 0,
        })

    return {"status": "ok", "ticker": ticker, "interval": interval, "bars": bars}


# ── Pattern detection engines ──────────────────────────────────────


@router.post("/tools/detect_pattern")
async def tool_detect_pattern(ticker: str, timeframe: str = "day"):
    """Detect all 12 price patterns on a stock."""
    from mcp_server.pattern_engine import PatternEngine
    from mcp_server.nse_scanner import get_stock_data

    df = await asyncio.to_thread(get_stock_data, ticker)
    if df is None or df.empty:
        return {"status": "error", "message": f"No data for {ticker}"}

    engine = PatternEngine()
    patterns = engine.detect_all(df)

    return {
        "status": "ok",
        "tool": "detect_pattern",
        "ticker": ticker,
        "timeframe": timeframe,
        "patterns_found": len(patterns),
        "patterns": [asdict(p) for p in patterns],
    }


@router.post("/tools/detect_smc")
async def tool_detect_smc(ticker: str, timeframe: str = "day"):
    """Detect Smart Money Concepts (SMC/ICT) patterns on a stock."""
    from mcp_server.smc_engine import SMCEngine
    from mcp_server.nse_scanner import get_stock_data

    df = await asyncio.to_thread(get_stock_data, ticker)
    if df is None or df.empty:
        return {"status": "error", "message": f"No data for {ticker}"}

    engine = SMCEngine()
    patterns = engine.detect_all(df)

    return {
        "status": "ok",
        "tool": "detect_smc",
        "ticker": ticker,
        "timeframe": timeframe,
        "patterns_found": len(patterns),
        "patterns": [asdict(p) for p in patterns],
    }


@router.post("/tools/detect_wyckoff")
async def tool_detect_wyckoff(ticker: str, timeframe: str = "day"):
    """Detect Wyckoff market cycle patterns on a stock."""
    from mcp_server.wyckoff_engine import WyckoffEngine
    from mcp_server.nse_scanner import get_stock_data

    df = await asyncio.to_thread(get_stock_data, ticker)
    if df is None or df.empty:
        return {"status": "error", "message": f"No data for {ticker}"}

    engine = WyckoffEngine()
    patterns = engine.detect_all(df)

    return {
        "status": "ok",
        "tool": "detect_wyckoff",
        "ticker": ticker,
        "timeframe": timeframe,
        "patterns_found": len(patterns),
        "patterns": [asdict(p) for p in patterns],
    }


@router.post("/tools/detect_vsa")
async def tool_detect_vsa(ticker: str, timeframe: str = "day"):
    """Detect Volume Spread Analysis patterns on a stock."""
    from mcp_server.vsa_engine import VSAEngine
    from mcp_server.nse_scanner import get_stock_data

    df = await asyncio.to_thread(get_stock_data, ticker)
    if df is None or df.empty:
        return {"status": "error", "message": f"No data for {ticker}"}

    engine = VSAEngine()
    patterns = engine.detect_all(df)

    return {
        "status": "ok",
        "tool": "detect_vsa",
        "ticker": ticker,
        "timeframe": timeframe,
        "patterns_found": len(patterns),
        "patterns": [asdict(p) for p in patterns],
    }


@router.post("/tools/detect_harmonic")
async def tool_detect_harmonic(ticker: str, timeframe: str = "day"):
    """Detect Harmonic price patterns on a stock."""
    from mcp_server.harmonic_engine import HarmonicEngine
    from mcp_server.nse_scanner import get_stock_data

    df = await asyncio.to_thread(get_stock_data, ticker)
    if df is None or df.empty:
        return {"status": "error", "message": f"No data for {ticker}"}

    engine = HarmonicEngine()
    patterns = engine.detect_all(df)

    return {
        "status": "ok",
        "tool": "detect_harmonic",
        "ticker": ticker,
        "timeframe": timeframe,
        "patterns_found": len(patterns),
        "patterns": [asdict(p) for p in patterns],
    }


@router.post("/tools/detect_rl")
async def tool_detect_rl(ticker: str, timeframe: str = "day"):
    """Detect RL-inspired patterns (regime, VWAP, momentum, optimal entry) on a stock."""
    from mcp_server.rl_engine import RLEngine
    from mcp_server.nse_scanner import get_stock_data

    df = await asyncio.to_thread(get_stock_data, ticker)
    if df is None or df.empty:
        return {"status": "error", "message": f"No data for {ticker}"}

    engine = RLEngine()
    patterns = engine.detect_all(df)

    return {
        "status": "ok",
        "tool": "detect_rl",
        "ticker": ticker,
        "timeframe": timeframe,
        "patterns_found": len(patterns),
        "patterns": [asdict(p) for p in patterns],
    }


# ── MWA breadth scan ───────────────────────────────────────────────


@router.post("/tools/get_mwa_score")
async def tool_get_mwa_score(db: Session = Depends(get_db)):
    """Get current MWA breadth score from DB or calculate fresh."""
    today = date.today()
    score = db.query(MWAScore).filter(MWAScore.score_date == today).first()

    if score:
        return {
            "status": "ok",
            "tool": "get_mwa_score",
            "date": str(score.score_date),
            "direction": score.direction,
            "bull_score": float(score.bull_score or 0),
            "bear_score": float(score.bear_score or 0),
            "bull_pct": float(score.bull_pct or 0),
            "bear_pct": float(score.bear_pct or 0),
            "promoted_stocks": score.promoted_stocks or [],
            "fii_net": float(score.fii_net or 0),
            "dii_net": float(score.dii_net or 0),
        }

    latest = db.query(MWAScore).order_by(desc(MWAScore.score_date)).first()
    if latest:
        return {
            "status": "ok",
            "tool": "get_mwa_score",
            "date": str(latest.score_date),
            "direction": latest.direction,
            "bull_score": float(latest.bull_score or 0),
            "bear_score": float(latest.bear_score or 0),
            "bull_pct": float(latest.bull_pct or 0),
            "bear_pct": float(latest.bear_pct or 0),
            "promoted_stocks": latest.promoted_stocks or [],
            "note": "Using latest available (not today)",
        }

    return {"status": "ok", "tool": "get_mwa_score", "message": "No MWA scores available yet"}


@router.get("/tools/mwa_scan_status/{job_id}")
async def tool_mwa_scan_status(job_id: str):
    """Poll for MWA scan job status."""
    from mcp_server import mcp_server as _ms

    job = _ms._mwa_jobs.get(job_id)
    if not job:
        return {"error": "Job not found", "job_id": job_id}
    resp = {"job_id": job_id, "status": job["status"], "started": job["started"]}
    if job["status"] in ("completed", "failed"):
        resp["finished"] = job.get("finished")
        resp["result"] = job.get("result")
    return resp


@router.post("/tools/run_mwa_scan")
@limiter.limit("30/minute")
async def tool_run_mwa_scan(request: Request, db: Session = Depends(get_db)):
    """Run the full 98-scanner MWA scan and persist score to DB."""
    import threading
    from mcp_server import mcp_server as _ms
    from mcp_server.market_calendar import is_market_holiday, is_market_open, is_weekend

    today = date.today()
    if is_weekend(today):
        return {"status": "skipped", "tool": "run_mwa_scan",
                "reason": f"Weekend ({today.strftime('%A')}). Scan not needed."}
    if is_market_holiday("NSE", today):
        return {"status": "skipped", "tool": "run_mwa_scan",
                "reason": f"Market holiday ({today}). Scan not needed."}
    any_open = is_market_open("NSE") or is_market_open("MCX") or is_market_open("CDS")
    if not any_open:
        return {"status": "skipped", "tool": "run_mwa_scan",
                "reason": "All markets closed. Scan skipped to prevent after-hours signals."}

    mode = request.query_params.get("mode", "async")
    if mode == "async":
        import uuid
        job_id = uuid.uuid4().hex[:12]
        _ms._mwa_jobs[job_id] = {
            "status": "queued", "result": None,
            "started": _ms._now_ist().isoformat(), "finished": None,
        }
        t = threading.Thread(target=_ms._run_mwa_scan_background, args=(job_id,), daemon=True)
        t.start()
        return {
            "status": "queued",
            "job_id": job_id,
            "poll_url": f"/tools/mwa_scan_status/{job_id}",
        }

    # Sync mode — blocks until complete
    result = _ms._execute_mwa_scan(db)
    return result


@router.get("/api/mwa/latest")
async def api_mwa_latest(db: Session = Depends(get_db)):
    """Latest MWA score for dashboard."""
    score = db.query(MWAScore).order_by(desc(MWAScore.score_date)).first()
    if not score:
        return {"status": "no_data"}

    raw_sr = score.scanner_results or {}
    scanner_results: dict = {}
    from mcp_server.mwa_scanner import SCANNERS
    for k, cfg in SCANNERS.items():
        if cfg.get("type") in ("UNKNOWN",):
            continue
        scanner_results[k] = {
            "name": k,
            "group": cfg.get("layer", "Other"),
            "weight": cfg.get("weight", 0),
            "count": 0,
            "direction": cfg.get("type", "NEUTRAL"),
            "stocks": [],
        }
    for k, v in raw_sr.items():
        if isinstance(v, dict) and "name" in v:
            scanner_results[k] = v
        else:
            cfg = SCANNERS.get(k, {})
            count = v if isinstance(v, (int, float)) else 0
            scanner_results[k] = {
                "name": k,
                "group": cfg.get("layer", "Other"),
                "weight": cfg.get("weight", 0),
                "count": int(count),
                "direction": cfg.get("type", "NEUTRAL"),
                "stocks": [],
            }

    return {
        "id": score.id,
        "score_date": str(score.score_date),
        "direction": score.direction,
        "bull_score": float(score.bull_score or 0),
        "bear_score": float(score.bear_score or 0),
        "bull_pct": float(score.bull_pct or 0),
        "bear_pct": float(score.bear_pct or 0),
        "scanner_results": scanner_results,
        "promoted_stocks": score.promoted_stocks or [],
        "fii_net": float(score.fii_net or 0),
        "dii_net": float(score.dii_net or 0),
        "sector_strength": score.sector_strength or {},
    }


# ── Tier monitors ──────────────────────────────────────────────────


@router.post("/tools/tier3_monitor")
async def tool_tier3_monitor(db: Session = Depends(get_db)):
    """Run Tier 3 active trade monitoring — updates prices, checks SL/target hits."""
    from mcp_server.tier_monitor import tier3_monitor
    alerts = tier3_monitor(db)
    return {"alerts": len(alerts), "details": alerts}


@router.post("/tools/tier2_monitor")
async def tool_tier2_monitor(db: Session = Depends(get_db)):
    """Run Tier 2 watchlist monitoring — checks entry zones, S&R breaches."""
    from mcp_server.tier_monitor import tier2_monitor
    alerts = tier2_monitor(db)
    return {"alerts": len(alerts), "details": alerts}


# ── Scanner review engine ─────────────────────────────────────────


@router.get("/api/scanner-review/today")
async def api_scanner_review_today(db: Session = Depends(get_db)):
    """Today's review (or most recent)."""
    row = (
        db.query(ScannerReview)
        .order_by(ScannerReview.review_date.desc())
        .first()
    )
    if not row:
        return {"status": "no_data", "reason": "no_reviews_yet"}
    return row.review_payload or {
        "review_date": str(row.review_date),
        "market_direction": row.market_direction,
        "overall_hit_rate": float(row.overall_hit_rate or 0),
        "scanner_hit_rates": row.scanner_hit_rates,
        "missed_opportunities": row.missed_opportunities,
        "false_positives": row.false_positives,
        "segment_performance": row.segment_performance,
        "chain_accuracy": row.chain_accuracy,
        "promoted_performance": row.promoted_performance,
        "best_scanners": row.best_scanners,
        "worst_scanners": row.worst_scanners,
    }


@router.get("/api/scanner-review/history")
async def api_scanner_review_history(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """Rolling review history."""
    from datetime import timedelta as _td

    cutoff = date.today() - _td(days=days)
    rows = (
        db.query(ScannerReview)
        .filter(ScannerReview.review_date >= cutoff)
        .order_by(ScannerReview.review_date.desc())
        .all()
    )
    return {
        "days": days,
        "count": len(rows),
        "reviews": [
            {
                "review_date": str(r.review_date),
                "market_direction": r.market_direction,
                "overall_hit_rate": float(r.overall_hit_rate or 0),
                "best_scanners": r.best_scanners,
                "worst_scanners": r.worst_scanners,
                "promoted_performance": r.promoted_performance,
            }
            for r in rows
        ],
    }


@router.post("/tools/run_scanner_review")
async def tool_run_scanner_review():
    """Manual trigger for scanner review (n8n compatible)."""
    from mcp_server.scanner_review import ScannerReviewEngine

    engine = ScannerReviewEngine()
    result = await engine.run_review()
    return result


@router.get("/api/scanner-review/leaderboard")
async def api_scanner_review_leaderboard(
    days: int = Query(default=30, ge=1, le=365),
):
    """Scanner ranking by rolling performance."""
    from mcp_server.scanner_review import get_leaderboard, get_rolling_stats

    board = get_leaderboard(days)
    stats = get_rolling_stats(days)
    return {
        "days": days,
        "entries": stats.get("entries", 0),
        "leaderboard": board,
    }
