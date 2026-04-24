"""Signals — dashboard CRUD + lifecycle tools.

Extracted from mcp_server.mcp_server in Phase 2d of the router split.
10 routes moved verbatim.

Clusters:
  - Dashboard signal list + delete + duplicate cleanup (/api/signals/*)
  - Signal authoring + outcome reporting (record_signal, update_signal)
  - Accuracy reporting (signal_accuracy, eod_summary)
  - Validation + monitoring (validate_signal, check_signals)
  - Active trade snapshot (get_active_trades)

Deferred imports: `_auto_sync_sheets()` stays in mcp_server.py.
"""
import asyncio
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from mcp_server.asset_registry import get_asset_class
from mcp_server.config import settings
from mcp_server.db import SessionLocal, get_db
from mcp_server.models import ActiveTrade, Outcome, Signal
from mcp_server.routers.deps import limiter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["signals"])


# ── Request models ─────────────────────────────────────────────────


class RecordSignalRequest(BaseModel):
    ticker: str
    direction: str
    entry_price: float
    stop_loss: float = 0
    target: float = 0
    pattern: str = ""
    confidence: int = 0
    exchange: str = "NSE"
    notes: str = ""
    rrr: float = 0


class UpdateSignalRequest(BaseModel):
    signal_id: str
    status: str  # TARGET_HIT, SL_HIT, PARTIAL, EXPIRED, CANCELLED
    exit_price: float = 0
    notes: str = ""


# ── Dashboard CRUD ─────────────────────────────────────────────────


@router.get("/api/signals")
async def api_signals(
    limit: int = 50,
    status: str = "",
    exchange: str = "",
    asset_class: str = "",
    timeframe: str = "",
    db: Session = Depends(get_db),
):
    """Recent signals for dashboard. Optional filter by status/exchange/asset_class/timeframe."""
    query = db.query(Signal)
    if status:
        query = query.filter(Signal.status == status.upper())
    if exchange:
        query = query.filter(Signal.exchange == exchange.upper())
    if asset_class:
        query = query.filter(Signal.asset_class == asset_class.upper())
    if timeframe:
        query = query.filter(Signal.timeframe == timeframe)
    signals = (
        query
        .order_by(desc(Signal.signal_date), desc(Signal.id))
        .limit(limit)
        .all()
    )
    return [
        {
            "id": s.id,
            "signal_date": str(s.signal_date),
            "signal_time": str(s.signal_time) if s.signal_time else None,
            "ticker": s.ticker,
            "exchange": s.exchange or "NSE",
            "asset_class": s.asset_class or "EQUITY",
            "timeframe": s.timeframe or "1D",
            "direction": s.direction,
            "pattern": s.pattern,
            "entry_price": float(s.entry_price) if s.entry_price else 0,
            "stop_loss": float(s.stop_loss) if s.stop_loss else 0,
            "target": float(s.target) if s.target else 0,
            "rrr": float(s.rrr) if s.rrr else 0,
            "qty": s.qty or 0,
            "risk_amt": float(s.risk_amt) if s.risk_amt else 0,
            "ai_confidence": s.ai_confidence or 0,
            "tv_confirmed": s.tv_confirmed or False,
            "mwa_score": s.mwa_score or "",
            "scanner_count": s.scanner_count or 0,
            "tier": s.tier or 1,
            "source": s.source or "",
            "status": s.status or "OPEN",
        }
        for s in signals
    ]


@router.post("/api/signals/cleanup-duplicates")
async def api_cleanup_duplicate_signals(db: Session = Depends(get_db)):
    """Remove duplicate OPEN signals keeping the oldest per ticker+direction."""
    from sqlalchemy import func

    dupes = (
        db.query(Signal.ticker, Signal.direction, func.min(Signal.id).label("keep_id"))
        .filter(Signal.status == "OPEN")
        .group_by(Signal.ticker, Signal.direction)
        .having(func.count(Signal.id) > 1)
        .all()
    )

    removed = []
    for ticker, direction, keep_id in dupes:
        extras = (
            db.query(Signal)
            .filter(
                Signal.ticker == ticker,
                Signal.direction == direction,
                Signal.status == "OPEN",
                Signal.id != keep_id,
            )
            .all()
        )
        for sig in extras:
            db.query(ActiveTrade).filter(ActiveTrade.signal_id == sig.id).delete()
            removed.append({"id": sig.id, "ticker": sig.ticker, "direction": sig.direction})
            db.delete(sig)

    db.commit()
    return {"removed_count": len(removed), "removed": removed}


@router.delete("/api/signals/{signal_id}")
async def api_delete_signal(signal_id: int, db: Session = Depends(get_db)):
    """Delete a signal and its linked ActiveTrade."""
    sig = db.query(Signal).filter(Signal.id == signal_id).first()
    if not sig:
        raise HTTPException(status_code=404, detail="Signal not found")
    db.query(ActiveTrade).filter(ActiveTrade.signal_id == signal_id).delete()
    db.delete(sig)
    db.commit()
    return {"deleted": signal_id, "ticker": sig.ticker}


# ── Validation ─────────────────────────────────────────────────────


@router.post("/tools/validate_signal")
@limiter.limit("30/minute")
async def tool_validate_signal(
    request: Request,
    ticker: str,
    direction: str,
    pattern: str,
    rrr: float = 3.0,
    entry_price: float = 0,
    stop_loss: float = 0,
    target: float = 0,
):
    """Validate a trading signal using Claude AI."""
    from mcp_server.validator import validate_signal

    result = validate_signal(
        ticker=ticker,
        direction=direction,
        pattern=pattern,
        rrr=rrr,
        entry_price=entry_price,
        stop_loss=stop_loss,
        target=target,
        mwa_direction="UNKNOWN",
        scanner_count=0,
        tv_confirmed=False,
        sector_strength="NEUTRAL",
        fii_net=0,
        delivery_pct=0,
        confidence_boosts=[],
        pre_confidence=50,
    )
    return {"status": "ok", "tool": "validate_signal", **result}


# ── Active trades summary ─────────────────────────────────────────


@router.post("/tools/get_active_trades")
async def tool_get_active_trades(db: Session = Depends(get_db)):
    """Get all active trades with PRRR vs CRRR."""
    trades = db.query(ActiveTrade).all()
    return {
        "status": "ok",
        "tool": "get_active_trades",
        "count": len(trades),
        "trades": [
            {
                "ticker": t.ticker,
                "entry_price": float(t.entry_price),
                "target": float(t.target),
                "stop_loss": float(t.stop_loss),
                "prrr": float(t.prrr) if t.prrr else None,
                "current_price": float(t.current_price) if t.current_price else None,
                "crrr": float(t.crrr) if t.crrr else None,
                "alert_sent": t.alert_sent,
            }
            for t in trades
        ],
    }


# ── Signal lifecycle (record / update outcome) ─────────────────────


@router.post("/tools/record_signal")
async def tool_record_signal(req: RecordSignalRequest):
    """Record a trading signal to Google Sheets for accuracy tracking."""
    from mcp_server import mcp_server as _ms
    from mcp_server.telegram_receiver import record_signal_to_sheets

    result = record_signal_to_sheets(req.model_dump())

    # Also log to sheets_sync tab format (with segment routing)
    asyncio.ensure_future(_ms._auto_sync_sheets(signal_data={
        "signal_date": str(date.today()),
        "ticker": req.ticker,
        "exchange": req.exchange,
        "asset_class": get_asset_class(f"{req.exchange}:{req.ticker.split(':')[-1]}").value if req.exchange else "EQUITY",
        "direction": req.direction,
        "entry_price": req.entry_price,
        "stop_loss": req.stop_loss,
        "target": req.target,
        "rrr": req.rrr,
        "ai_confidence": req.confidence,
        "status": "OPEN",
    }))

    return result


@router.post("/tools/update_signal")
async def tool_update_signal(req: UpdateSignalRequest):
    """Update signal status when target/SL is hit."""
    from mcp_server.telegram_receiver import get_sheets_tracker
    tracker = get_sheets_tracker()
    success = tracker.update_signal_status(
        req.signal_id, req.status, req.exit_price, req.notes,
    )

    # Also update trade memory with outcome
    try:
        from mcp_server.trade_memory import TradeMemory
        _mem = TradeMemory(filepath=settings.TRADE_MEMORY_FILE)
        outcome_map = {"TARGET_HIT": "WIN", "SL_HIT": "LOSS", "BREAKEVEN": "BREAKEVEN"}
        outcome = outcome_map.get(req.status, req.status)
        _mem.update_outcome(
            signal_id=req.signal_id,
            outcome=outcome,
            exit_price=req.exit_price or 0.0,
        )
    except Exception as e:
        logger.debug("Trade memory outcome update skipped: %s", e)

    return {"success": success, "signal_id": req.signal_id, "status": req.status}


# ── Accuracy + EOD reporting ───────────────────────────────────────


@router.get("/tools/signal_accuracy")
async def tool_signal_accuracy():
    """Get signal accuracy statistics from Google Sheets."""
    from mcp_server.telegram_receiver import get_sheets_tracker
    tracker = get_sheets_tracker()
    return tracker.get_accuracy_stats()


@router.get("/tools/eod_summary")
async def tool_eod_summary():
    """Pre-formatted EOD summary — self-contained, no Claude needed.

    Returns both a JSON dict and a formatted Telegram-ready text string.
    Covers: today's signals, accuracy, P&L, top/worst scanners, corrections.
    """
    today = date.today()
    db = SessionLocal()
    try:
        today_sigs = db.query(Signal).filter(Signal.signal_date == today).all()
        today_open = sum(1 for s in today_sigs if s.status == "OPEN")

        today_outcomes = db.query(Outcome).filter(Outcome.exit_date == today).all()
        wins = sum(1 for o in today_outcomes if o.outcome == "WIN")
        losses = sum(1 for o in today_outcomes if o.outcome == "LOSS")
        pnl = sum(float(o.pnl_amount or 0) for o in today_outcomes)
        wr = round(wins / max(wins + losses, 1) * 100, 1)

        total_closed = db.query(Outcome).count()
        total_wins = db.query(Outcome).filter(Outcome.outcome == "WIN").count()
        total_losses = db.query(Outcome).filter(Outcome.outcome == "LOSS").count()
        all_time_wr = round(total_wins / max(total_closed, 1) * 100, 1)

        active_count = db.query(ActiveTrade).count()

        sep = "━" * 24
        text = (
            f"📊 EOD Report — {today.strftime('%d/%m/%Y')}\n"
            f"{sep}\n"
            f"Today's Signals: {len(today_sigs)} (Open: {today_open})\n"
            f"Closed Today: {wins + losses} | W: {wins} L: {losses}\n"
            f"Win Rate: {wr}%\n"
            f"Today P&L: ₹{pnl:,.0f}\n"
            f"{sep}\n"
            f"All-Time: {total_closed} closed | WR: {all_time_wr}%\n"
            f"Active Trades: {active_count}\n"
            f"{sep}\n"
        )

        return {
            "report": text,
            "today": {
                "signals": len(today_sigs),
                "open": today_open,
                "wins": wins,
                "losses": losses,
                "win_rate": wr,
                "pnl": round(pnl, 2),
            },
            "all_time": {
                "closed": total_closed,
                "wins": total_wins,
                "losses": total_losses,
                "win_rate": all_time_wr,
            },
            "active_trades": active_count,
        }
    finally:
        db.close()


# ── Monitor trigger ────────────────────────────────────────────────


@router.post("/tools/check_signals")
async def tool_check_signals():
    """Manually trigger signal monitor — check all OPEN signals for SL/TGT hit."""
    from mcp_server.signal_monitor import monitor_open_signals, _send_close_alert
    closed = monitor_open_signals()
    for c in closed:
        try:
            await _send_close_alert(c)
        except Exception:
            pass
    return {
        "checked": True,
        "closed_count": len(closed),
        "closed_signals": closed,
    }
