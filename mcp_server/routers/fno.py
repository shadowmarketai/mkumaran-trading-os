"""F&O derivatives analytics — OI buildup, IV rank, PCR, volatility, expiry.

Extracted from mcp_server.mcp_server in Phase 2b of the router split.
Per operator decision §9.3 of docs/MCP_SERVER_ROUTER_SPLIT_PLAN.md, fno/
is split from options/ into its own router. This router owns the
derivatives-analytics endpoints; options math lives in options.py.

9 routes migrated. All F&O analytics endpoints need the shared Kite
client, accessed via mcp_server._get_kite_for_fo() (still in
mcp_server.py per "helpers stay" rule).
"""
import asyncio
import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["fno"])


@router.post("/tools/get_fo_signal")
async def tool_get_fo_signal():
    """Combined F&O signal: OI + PCR + EMA."""
    from mcp_server.fo_module import get_fo_signal

    result = get_fo_signal()
    return {"status": "ok", "tool": "get_fo_signal", **result}


@router.post("/tools/scan_oi_buildup")
async def tool_scan_oi_buildup(symbols: str | None = None):
    """
    OI buildup scan across F&O indices + stocks.

    symbols: optional comma-separated list (default: all indices + F&O stocks).
    Returns LONG_BUILDUP / SHORT_BUILDUP / SHORT_COVERING / LONG_UNWINDING per symbol.
    """
    from mcp_server import mcp_server as _ms
    from mcp_server.fo_module import scan_oi_buildup

    sym_list = [s.strip().upper() for s in symbols.split(",")] if symbols else None
    kite = _ms._get_kite_for_fo()
    result = await asyncio.to_thread(scan_oi_buildup, kite, sym_list)
    return {"status": "ok", "tool": "scan_oi_buildup", **result}


@router.get("/api/fno/oi_buildup")
async def api_oi_buildup(symbols: str | None = None):
    """GET variant of OI buildup scan for dashboard consumption."""
    from mcp_server import mcp_server as _ms
    from mcp_server.fo_module import scan_oi_buildup

    sym_list = [s.strip().upper() for s in symbols.split(",")] if symbols else None
    kite = _ms._get_kite_for_fo()
    return await asyncio.to_thread(scan_oi_buildup, kite, sym_list)


@router.get("/api/fno/snapshot/{symbol}")
async def api_fno_snapshot(symbol: str):
    """Full F&O snapshot for any symbol: futures OI + chain + IV + buildup + expiry."""
    from mcp_server import mcp_server as _ms
    from mcp_server.fo_module import get_stock_fo_snapshot

    kite = _ms._get_kite_for_fo()
    return await asyncio.to_thread(get_stock_fo_snapshot, kite, symbol.upper())


@router.get("/api/fno/iv_rank/{symbol}")
async def api_iv_rank(symbol: str):
    """IV rank + percentile for a symbol (NIFTY, BANKNIFTY, RELIANCE, ...)."""
    from mcp_server import mcp_server as _ms
    from mcp_server.fo_module import get_iv_rank

    kite = _ms._get_kite_for_fo()
    return await asyncio.to_thread(get_iv_rank, kite, symbol.upper())


@router.get("/api/fno/volatility_setup/{symbol}")
async def api_volatility_setup(symbol: str):
    """Detect long/short straddle setup based on IV rank."""
    from mcp_server import mcp_server as _ms
    from mcp_server.fo_module import detect_volatility_setup

    kite = _ms._get_kite_for_fo()
    return await asyncio.to_thread(detect_volatility_setup, kite, symbol.upper())


@router.get("/api/fno/expiry/{symbol}")
async def api_fno_expiry(symbol: str):
    """Check if today is expiry day for a given symbol."""
    from mcp_server import mcp_server as _ms
    from mcp_server.fo_module import is_expiry_day

    kite = _ms._get_kite_for_fo()
    return await asyncio.to_thread(is_expiry_day, kite, symbol.upper())


@router.post("/tools/run_fno_analytics")
async def tool_run_fno_analytics():
    """
    Manually trigger one F&O analytics cycle.

    Returns alerts + per-symbol snapshots and updates the persisted state.
    Useful for n8n hooks or for testing alert wiring outside market hours.
    """
    from mcp_server.fno_analytics_monitor import check_fno_analytics_once, _send_alerts

    result = await asyncio.to_thread(check_fno_analytics_once)
    alerts = result.get("alerts", [])
    if alerts:
        try:
            await _send_alerts(alerts)
        except Exception as e:
            logger.warning("F&O alerts dispatch failed: %s", e)
    return {"status": "ok", "tool": "run_fno_analytics", **result}


@router.get("/api/fno/analytics/state")
async def api_fno_analytics_state():
    """Return the most recent F&O analytics monitor snapshot/state file."""
    from mcp_server.fno_analytics_monitor import _load_state, STATE_FILE

    state = _load_state()
    return {
        "exists": STATE_FILE.exists(),
        "path": str(STATE_FILE),
        "state": state,
    }
