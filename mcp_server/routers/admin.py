"""Admin — sheets maintenance + Stitch ETL pipeline.

Extracted from mcp_server.mcp_server in Phase 3d of the router split.
8 routes moved verbatim.

Clusters:
  - Google Sheets maintenance (reset, clear, backfill outcomes)
  - Stitch Import API ETL (status, push, push_signals, push_trades, validate)

All handlers wrap external-service calls — no shared mcp_server state.
Clean, isolated extraction.
"""
import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from mcp_server.db import get_db
from mcp_server.models import Outcome, Signal

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin"])


# ── Request models ─────────────────────────────────────────────────


class StitchPushRequest(BaseModel):
    table_name: str
    key_names: list[str]
    records: list[dict]


# ── Google Sheets maintenance ─────────────────────────────────────


@router.post("/tools/reset_sheets")
async def tool_reset_sheets():
    """Clear all existing signal data from Google Sheets and start fresh.

    Deletes all rows from the SIGNALS tab (preserves headers) so new
    entries are captured cleanly without stale data corrupting accuracy.
    """
    try:
        from mcp_server.telegram_receiver import get_sheets_tracker
        tracker = get_sheets_tracker()
        ws = tracker._worksheet
        if ws is None:
            return {"status": "error", "message": "Sheets not connected"}

        all_rows = ws.get_all_values()
        if len(all_rows) > 1:
            ws.delete_rows(2, len(all_rows))
            cleared = len(all_rows) - 1
        else:
            cleared = 0

        seg_cleared = 0
        for seg_name in ["NSE Equity", "F&O", "Commodity", "Forex", "Intraday"]:
            try:
                seg_ws = tracker._sheet.worksheet(seg_name)
                seg_rows = seg_ws.get_all_values()
                if len(seg_rows) > 1:
                    seg_ws.delete_rows(2, len(seg_rows))
                    seg_cleared += len(seg_rows) - 1
            except Exception:
                pass

        logger.info(
            "Sheets reset: cleared %d master rows + %d segment rows",
            cleared, seg_cleared,
        )
        return {
            "status": "ok",
            "master_rows_cleared": cleared,
            "segment_rows_cleared": seg_cleared,
        }
    except Exception as e:
        logger.error("Sheets reset failed: %s", e)
        return {"status": "error", "message": str(e)}


@router.post("/tools/backfill_sheets_outcomes")
async def tool_backfill_sheets_outcomes(
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """Reconcile Google Sheets for already-closed trades.

    Walks Outcome records from the last `days` days, joins Signal, and:
      1. Calls update_signal_status_by_match() to patch the SIGNALS + segment tabs
         (fixes rows left in OPEN state by the old broken wildcard lookup).
      2. Calls update_accuracy() with the full outcome list to populate the
         ACCURACY tab (dedupe-safe so repeat runs are harmless).

    Safe to call repeatedly — idempotent via match-based update + signal_id dedupe.
    """
    from mcp_server.telegram_receiver import get_sheets_tracker
    from mcp_server.sheets_sync import update_accuracy

    cutoff = date.today() - timedelta(days=days)

    rows = (
        db.query(Outcome, Signal)
        .join(Signal, Outcome.signal_id == Signal.id)
        .filter(Outcome.exit_date >= cutoff)
        .order_by(Outcome.exit_date.asc(), Outcome.id.asc())
        .all()
    )

    tracker = get_sheets_tracker()

    patched_master = 0
    patched_none = 0
    errors: list[dict] = []
    accuracy_rows: list[dict] = []

    for outcome, sig in rows:
        direction = sig.direction or "BUY"
        entry_price = float(sig.entry_price or 0)
        exit_price = float(outcome.exit_price or 0)

        if entry_price > 0 and exit_price > 0:
            if direction in ("BUY", "LONG"):
                pnl_pct = (exit_price - entry_price) / entry_price * 100
                pnl_rs = exit_price - entry_price
            else:
                pnl_pct = (entry_price - exit_price) / entry_price * 100
                pnl_rs = entry_price - exit_price
        else:
            pnl_pct = 0.0
            pnl_rs = 0.0

        outcome_str = (outcome.outcome or "").upper()
        if outcome_str == "WIN":
            sheet_status = "TARGET_HIT"
        elif outcome_str == "LOSS":
            sheet_status = "SL_HIT"
        else:
            sheet_status = "CLOSED"

        signal_date_str = (
            sig.signal_date.isoformat()
            if sig.signal_date
            else date.today().isoformat()
        )

        try:
            ok = tracker.update_signal_status_by_match(
                ticker=sig.ticker,
                signal_date=signal_date_str,
                direction=direction,
                exchange=sig.exchange or "NSE",
                status=sheet_status,
                exit_price=exit_price,
                notes=f"Backfilled | P&L: {round(pnl_pct, 2)}%",
            )
            if ok:
                patched_master += 1
            else:
                patched_none += 1
        except Exception as e:
            errors.append({
                "signal_id": sig.id,
                "ticker": sig.ticker,
                "error": str(e),
            })

        accuracy_rows.append({
            "signal_id": sig.id,
            "ticker": sig.ticker,
            "exchange": sig.exchange or "NSE",
            "asset_class": sig.asset_class or "EQUITY",
            "direction": direction,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "outcome": outcome_str or "WIN",
            "pnl_amount": round(pnl_rs * (sig.qty or 1), 2),
            "days_held": outcome.days_held or 0,
            "exit_reason": outcome.exit_reason or "",
            "exit_date": (
                outcome.exit_date.isoformat()
                if outcome.exit_date
                else str(date.today())
            ),
        })

    accuracy_ok = False
    if accuracy_rows:
        try:
            accuracy_ok = update_accuracy(accuracy_rows)
        except Exception as e:
            errors.append({"accuracy_update_error": str(e)})

    return {
        "status": "ok",
        "days_scanned": days,
        "cutoff_date": cutoff.isoformat(),
        "outcomes_found": len(rows),
        "patched_in_sheet": patched_master,
        "not_found_in_sheet": patched_none,
        "accuracy_tab_updated": accuracy_ok,
        "accuracy_rows_sent": len(accuracy_rows),
        "errors": errors,
    }


@router.post("/tools/clear_sheets")
async def tool_clear_sheets():
    """Clear all Google Sheets data rows (keep headers) for a fresh start."""
    from mcp_server.sheets_sync import _get_sheets_client

    _, sheet = _get_sheets_client()
    if not sheet:
        return {"error": "Google Sheets not configured"}

    cleared = []
    errors = []

    tabs_headers = {
        "Signals": [
            "Signal ID", "Date", "Ticker", "Exchange", "Asset Class",
            "Direction", "Entry Price", "Stop Loss", "Target", "RRR",
            "Pattern", "Confidence", "Status", "Exit Price", "Exit Date",
            "P&L %", "P&L Rs", "Result", "Notes",
        ],
        "SIGNALS": [
            "Date", "Time", "Ticker", "Exchange", "Asset Class",
            "Direction", "Pattern", "Entry", "SL", "Target",
            "RRR", "Qty", "Risk Amt", "AI Confidence",
            "TV Confirmed", "MWA Score", "Scanner Count", "Status",
        ],
        "SIGNALS_EQUITY": None,
        "SIGNALS_COMMODITY": None,
        "SIGNALS_FNO": None,
        "SIGNALS_FOREX": None,
        "WATCHLIST": [
            "Ticker", "Name", "Exchange", "Asset Class", "Timeframe",
            "Tier", "LTRP", "Pivot High", "Active", "Source",
            "Added By", "Notes",
        ],
        "ACCURACY": [
            "Signal ID", "Ticker", "Exchange", "Asset Class",
            "Direction", "Entry", "Exit", "Outcome", "P&L",
            "Days Held", "Exit Reason",
        ],
        "MWA LOG": [
            "Date", "Direction", "Bull Score", "Bear Score", "Bull %", "Bear %",
        ],
        "ACTIVE TRADES": [
            "Ticker", "Exchange", "Asset Class", "Direction",
            "Entry", "Target", "SL", "PRRR", "Current",
            "CRRR", "P&L %", "Last Updated",
        ],
    }

    segment_headers = [
        "Signal ID", "Date", "Ticker", "Exchange", "Asset Class",
        "Direction", "Entry Price", "Stop Loss", "Target", "RRR",
        "Pattern", "Confidence", "Status", "Exit Price", "Exit Date",
        "P&L %", "P&L Rs", "Result", "Notes",
    ]

    for tab_name, headers in tabs_headers.items():
        try:
            ws = sheet.worksheet(tab_name)
            ws.clear()
            h = headers if headers else segment_headers
            ws.append_row(h)
            cleared.append(tab_name)
        except Exception as e:
            errors.append(f"{tab_name}: {e}")

    return {
        "status": "ok",
        "cleared_tabs": cleared,
        "errors": errors,
        "message": f"Cleared {len(cleared)} tabs, {len(errors)} errors",
    }


# ── Stitch Data ETL ────────────────────────────────────────────────


@router.get("/tools/stitch_status")
async def tool_stitch_status():
    """Check if Stitch Import API pipeline is healthy."""
    from mcp_server.stitch_sync import stitch_status
    try:
        result = await stitch_status()
        return {"status": "ok", "tool": "stitch_status", "stitch": result}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.post("/tools/stitch_push")
async def tool_stitch_push(req: StitchPushRequest):
    """Push arbitrary records to Stitch data warehouse."""
    from mcp_server.stitch_sync import stitch_push
    try:
        result = await stitch_push(req.table_name, req.key_names, req.records)
        return {"status": "ok", "tool": "stitch_push", "stitch": result}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@router.post("/tools/stitch_push_signals")
async def tool_stitch_push_signals(db: Session = Depends(get_db)):
    """Push all recent trading signals to Stitch warehouse."""
    from mcp_server.stitch_sync import push_signals

    signals = db.query(Signal).order_by(desc(Signal.created_at)).limit(500).all()
    records = [
        {
            "signal_id": str(s.id),
            "symbol": s.ticker,
            "exchange": s.exchange or "NSE",
            "direction": s.direction,
            "entry": s.entry_price,
            "stoploss": s.stop_loss,
            "target": s.target,
            "confidence": s.confidence or 0,
            "scanner": s.pattern or "",
            "timestamp": s.created_at.isoformat() if s.created_at else "",
        }
        for s in signals
    ]
    result = await push_signals(records)
    return {"status": "ok", "tool": "stitch_push_signals", "count": len(records), "stitch": result}


@router.post("/tools/stitch_push_trades")
async def tool_stitch_push_trades(db: Session = Depends(get_db)):
    """Push closed trade history to Stitch warehouse."""
    from mcp_server.stitch_sync import push_trades

    outcomes = db.query(Outcome).order_by(desc(Outcome.closed_at)).limit(500).all()
    records = [
        {
            "trade_id": str(o.id),
            "symbol": o.ticker,
            "direction": o.direction,
            "entry_price": o.entry_price,
            "exit_price": o.exit_price or 0,
            "pnl": o.pnl or 0,
            "pnl_pct": o.pnl_pct or 0,
            "status": o.status or "CLOSED",
            "opened_at": o.opened_at.isoformat() if o.opened_at else "",
            "closed_at": o.closed_at.isoformat() if o.closed_at else "",
        }
        for o in outcomes
    ]
    result = await push_trades(records)
    return {"status": "ok", "tool": "stitch_push_trades", "count": len(records), "stitch": result}


@router.post("/tools/stitch_validate")
async def tool_stitch_validate(req: StitchPushRequest):
    """Validate records against Stitch without persisting (dry run)."""
    from mcp_server.stitch_sync import stitch_validate
    try:
        result = await stitch_validate(req.table_name, req.key_names, req.records)
        return {"status": "ok", "tool": "stitch_validate", "stitch": result}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Broker reconciliation ─────────────────────────────────────


_last_reconcile_result: dict = {}


@router.post("/api/reconcile/run")
async def api_reconcile_run(alert: bool = True):
    """Trigger an immediate broker-vs-DB reconciliation.

    Compares the live position book from all connected brokers against
    active_trades in Postgres. Returns a summary with any GHOST /
    PHANTOM / QTY_DRIFT entries found.

    Optional query param: alert=false to suppress Telegram notification
    even when drift is found (useful for manual inspection).
    """
    global _last_reconcile_result
    from mcp_server.broker_reconciler import run_reconciliation
    result = run_reconciliation(alert_on_drift=alert)
    _last_reconcile_result = {
        "checked_at": result.checked_at.isoformat(),
        "clean": result.clean,
        "broker_count": len(result.broker_positions),
        "db_count": len(result.db_positions),
        "ghosts": [
            {"id": g.id, "ticker": g.ticker, "qty": g.qty, "direction": g.direction}
            for g in result.ghosts
        ],
        "phantoms": [
            {"ticker": p.ticker, "qty": p.qty, "direction": p.direction, "source": p.source}
            for p in result.phantoms
        ],
        "qty_drifts": result.qty_drifts,
        "summary": result.summary(),
    }
    return _last_reconcile_result


@router.get("/api/reconcile/status")
async def api_reconcile_status():
    """Return the result of the most recent reconciliation run (cached in-memory).

    Returns an empty object if no reconciliation has been run since
    the last server restart.
    """
    if not _last_reconcile_result:
        return {"status": "no_run", "message": "POST /api/reconcile/run to trigger"}
    return _last_reconcile_result


# ── Tax export ────────────────────────────────────────────────


@router.get("/api/tax/statement")
async def api_tax_statement(
    fy: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
):
    """Export a tax statement for all closed trades in the given period.

    Params (mutually exclusive):
      fy        Financial year e.g. "2025-26" (default: current FY)
      from_date ISO date string e.g. "2025-04-01"
      to_date   ISO date string e.g. "2026-03-31"

    Returns a full trade-by-trade P&L with Indian tax category
    (INTRADAY_EQUITY / STCG_EQUITY / LTCG_EQUITY / FNO), exact
    transaction costs (STT / brokerage / GST / exchange / SEBI /
    stamp duty), and an indicative (approximate) tax figure per trade.

    Disclaimer: indicative_tax values are APPROXIMATE. Consult your CA.
    """
    import asyncio
    from mcp_server.tax_exporter import export_tax_statement

    if fy is None and from_date is None:
        from datetime import date as _date
        today = _date.today()
        fy = f"{today.year if today.month >= 4 else today.year - 1}-{str(today.year + (1 if today.month >= 4 else 0))[2:]}"

    summary = await asyncio.to_thread(
        export_tax_statement, fy, from_date, to_date,
    )
    return summary.as_dict()


@router.get("/api/tax/statement.csv")
async def api_tax_statement_csv(
    fy: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
):
    """Download the tax statement as a CSV file.

    Same parameters as GET /api/tax/statement.
    Returns Content-Disposition: attachment so browsers save the file.
    """
    import asyncio
    from fastapi.responses import Response
    from mcp_server.tax_exporter import export_tax_statement

    if fy is None and from_date is None:
        from datetime import date as _date
        today = _date.today()
        fy = f"{today.year if today.month >= 4 else today.year - 1}-{str(today.year + (1 if today.month >= 4 else 0))[2:]}"

    summary = await asyncio.to_thread(
        export_tax_statement, fy, from_date, to_date,
    )
    csv_bytes = summary.as_csv()
    filename  = f"tax_statement_{summary.fy.replace('-', '_')}.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Dhan intraday backfill ─────────────────────────────────────


_backfill_status: dict = {"running": False, "progress": "", "pid": None}


@router.post("/tools/run_backfill")
async def tool_run_backfill(
    years: int = 5,
    ticker: str | None = None,
    resume: bool = True,
):
    """Launch the Dhan intraday OHLCV backfill as a background asyncio task.

    Runs inside the FastAPI process — survives Coolify terminal disconnects.

    Params:
      years:   years of 15-min history to pull (default 5)
      ticker:  single ticker (default: all 100 Nifty stocks)
      resume:  skip chunks already in backfill_progress table (default true)

    Check progress: GET /tools/backfill_status
    """
    global _backfill_status

    if _backfill_status.get("running"):
        return {
            "status": "already_running",
            "progress": _backfill_status.get("progress"),
        }

    import asyncio

    async def _run():
        global _backfill_status
        _backfill_status = {"running": True, "progress": "starting...", "pid": None}
        try:
            import sys
            sys.path.insert(0, "/app")
            # Import and run the backfill inline
            from scripts.backfill_dhan_intraday import (
                NIFTY_100, backfill_ticker, _ensure_progress_table,
                _build_ca_skip_dates,
            )
            from mcp_server.db import SessionLocal
            from mcp_server.data_provider import get_provider

            universe = [ticker.upper()] if ticker else NIFTY_100
            total_days = years * 365
            session = SessionLocal()
            _ensure_progress_table(session)
            provider = get_provider()
            dhan_source = provider.dhan
            if not dhan_source.logged_in:
                ok = dhan_source.login()
                if not ok:
                    _backfill_status = {"running": False, "progress": "FAILED: Dhan login failed"}
                    return

            ca_skip = _build_ca_skip_dates()
            grand_total = 0

            for i, sym in enumerate(universe, 1):
                _backfill_status["progress"] = f"[{i}/{len(universe)}] {sym} — {grand_total} bars so far"
                bars = await asyncio.to_thread(
                    backfill_ticker, dhan_source, sym, total_days, session, resume, ca_skip
                )
                grand_total += bars

            session.close()
            _backfill_status = {
                "running": False,
                "progress": f"DONE — {grand_total} bars across {len(universe)} tickers",
            }
        except Exception as e:
            _backfill_status = {"running": False, "progress": f"FAILED: {e}"}
            logger.error("Backfill task failed: %s", e)

    asyncio.create_task(_run())
    return {
        "status": "started",
        "message": f"Backfill running in background ({years}Y, {'all Nifty 100' if not ticker else ticker}). Poll GET /tools/backfill_status for progress.",
    }


@router.get("/tools/backfill_status")
async def tool_backfill_status():
    """Return current backfill progress."""
    return _backfill_status
