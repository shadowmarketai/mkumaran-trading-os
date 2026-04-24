"""Health + info + exchanges — the smallest, safest router.

Extracted from `mcp_server.mcp_server` in the Phase 1a router-split PR.
Routes moved verbatim; behavior is identical.

`/health` reads the live `_order_manager` module-level singleton via a
lazy-import inside the handler so this module doesn't force
`mcp_server.mcp_server` to be fully initialised at router import time.
"""
from fastapi import APIRouter
from sqlalchemy import text

from mcp_server.asset_registry import get_supported_exchanges
from mcp_server.db import SessionLocal

router = APIRouter(tags=["health"])


@router.get("/api/info")
async def api_info():
    return {
        "service": "MKUMARAN Trading OS",
        "version": "1.9",
        "status": "running",
        "docs": "/docs",
    }


@router.get("/health")
async def health():
    # Deferred import — `_order_manager` is initialised by mcp_server.mcp_server
    # lifespan after this router is already registered.
    from mcp_server import mcp_server as _ms

    checks = {"api": "ok"}

    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    if _ms._order_manager and _ms._order_manager.kite:
        checks["kite"] = "connected"
    else:
        checks["kite"] = "not_connected"

    db_ok = checks["database"] == "ok"
    status = "healthy" if db_ok else "degraded"

    return {
        "status": status,
        "service": "mkumaran-trading-os",
        "checks": checks,
    }


@router.get("/api/exchanges")
async def api_exchanges():
    """List all supported exchanges and asset classes."""
    return get_supported_exchanges()
