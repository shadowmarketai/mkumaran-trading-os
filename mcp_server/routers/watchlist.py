"""Watchlist CRUD — dashboard + /tools endpoints.

Extracted from mcp_server.mcp_server in Phase 1d of the router split.
All 5 handlers moved verbatim. The `_serialize_watchlist` helper moved
with them because it has no other callers.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from mcp_server.asset_registry import get_asset_class, get_exchange, parse_ticker
from mcp_server.db import get_db
from mcp_server.models import Watchlist

router = APIRouter(tags=["watchlist"])


def _serialize_watchlist(w: Watchlist) -> dict:
    return {
        "id": w.id,
        "ticker": w.ticker,
        "name": w.name or w.ticker,
        "exchange": w.exchange or "NSE",
        "asset_class": w.asset_class or "EQUITY",
        "timeframe": w.timeframe or "1D",
        "tier": w.tier,
        "ltrp": float(w.ltrp) if w.ltrp else None,
        "pivot_high": float(w.pivot_high) if w.pivot_high else None,
        "active": w.active if w.active is not None else True,
        "source": w.source or "Manual",
        "added_at": str(w.added_at) if w.added_at else None,
        "added_by": w.added_by or "user",
        "notes": w.notes,
    }


@router.post("/tools/manage_watchlist")
async def tool_manage_watchlist(
    action: str,
    ticker: str = "",
    tier: int = 2,
    ltrp: float = 0,
    pivot_high: float = 0,
    exchange: str = "",
    db: Session = Depends(get_db),
):
    """Add, remove, pause, or list watchlist instruments (stocks, commodities, forex, F&O)."""
    # Auto-detect exchange from ticker prefix or use provided exchange
    if ticker and ":" in ticker:
        ex_str, symbol = parse_ticker(ticker)
        formatted_ticker = f"{ex_str}:{symbol}"
    elif ticker and exchange:
        formatted_ticker = f"{exchange.upper()}:{ticker.upper()}"
    elif ticker:
        formatted_ticker = f"NSE:{ticker.upper()}"
    else:
        formatted_ticker = ""

    if action == "list":
        query = db.query(Watchlist)
        if tier > 0:
            query = query.filter(Watchlist.tier == tier)
        if exchange:
            query = query.filter(Watchlist.exchange == exchange.upper())
        items = query.filter(Watchlist.active.is_(True)).all()
        return {
            "status": "ok",
            "action": "list",
            "count": len(items),
            "stocks": [
                {
                    "ticker": w.ticker,
                    "exchange": w.exchange or "NSE",
                    "asset_class": w.asset_class or "EQUITY",
                    "tier": w.tier,
                    "ltrp": float(w.ltrp) if w.ltrp else None,
                    "pivot_high": float(w.pivot_high) if w.pivot_high else None,
                    "added_at": str(w.added_at),
                }
                for w in items
            ],
        }

    if not ticker:
        return {"status": "error", "message": "ticker required for add/remove/pause"}

    detected_exchange = get_exchange(formatted_ticker).value
    detected_asset = get_asset_class(formatted_ticker).value

    if action == "add":
        existing = db.query(Watchlist).filter(Watchlist.ticker == formatted_ticker).first()
        if existing:
            existing.active = True
            existing.tier = tier
            existing.exchange = detected_exchange
            existing.asset_class = detected_asset
            if ltrp > 0:
                existing.ltrp = ltrp
            if pivot_high > 0:
                existing.pivot_high = pivot_high
            db.commit()
            return {"status": "ok", "action": "reactivated", "ticker": formatted_ticker, "exchange": detected_exchange}

        new_item = Watchlist(
            ticker=formatted_ticker,
            exchange=detected_exchange,
            asset_class=detected_asset,
            tier=tier,
            ltrp=ltrp if ltrp > 0 else None,
            pivot_high=pivot_high if pivot_high > 0 else None,
        )
        db.add(new_item)
        db.commit()
        return {"status": "ok", "action": "added", "ticker": formatted_ticker, "exchange": detected_exchange, "tier": tier}

    if action == "remove":
        item = db.query(Watchlist).filter(Watchlist.ticker == formatted_ticker).first()
        if item:
            db.delete(item)
            db.commit()
            return {"status": "ok", "action": "removed", "ticker": formatted_ticker}
        return {"status": "error", "message": f"{formatted_ticker} not in watchlist"}

    if action == "pause":
        item = db.query(Watchlist).filter(Watchlist.ticker == formatted_ticker).first()
        if item:
            item.active = False
            db.commit()
            return {"status": "ok", "action": "paused", "ticker": formatted_ticker}
        return {"status": "error", "message": f"{formatted_ticker} not in watchlist"}

    return {"status": "error", "message": f"Unknown action: {action}"}


@router.get("/api/watchlist")
async def api_watchlist(
    tier: int = 0,
    exchange: str = "",
    asset_class: str = "",
    db: Session = Depends(get_db),
):
    """Watchlist for dashboard (all items, not just active). Filter by exchange/asset_class."""
    query = db.query(Watchlist)
    if tier > 0:
        query = query.filter(Watchlist.tier == tier)
    if exchange:
        query = query.filter(Watchlist.exchange == exchange.upper())
    if asset_class:
        query = query.filter(Watchlist.asset_class == asset_class.upper())

    items = query.order_by(Watchlist.tier, Watchlist.ticker).all()
    return [_serialize_watchlist(w) for w in items]


@router.post("/api/watchlist")
async def api_watchlist_add(
    ticker: str = Query(...),
    tier: int = Query(default=3),
    ltrp: float = Query(default=0),
    pivot_high: float = Query(default=0),
    timeframe: str = Query(default="1D"),
    db: Session = Depends(get_db),
):
    """Add instrument to watchlist. Supports EXCHANGE:SYMBOL format."""
    if ":" in ticker:
        ex_str, symbol = parse_ticker(ticker)
        formatted = f"{ex_str}:{symbol}"
    else:
        formatted = f"NSE:{ticker.upper()}"

    detected_exchange = get_exchange(formatted).value
    detected_asset = get_asset_class(formatted).value

    existing = db.query(Watchlist).filter(Watchlist.ticker == formatted).first()
    if existing:
        existing.active = True
        existing.tier = tier
        existing.exchange = detected_exchange
        existing.asset_class = detected_asset
        if ltrp > 0:
            existing.ltrp = ltrp
        if pivot_high > 0:
            existing.pivot_high = pivot_high
        db.commit()
        db.refresh(existing)
        return _serialize_watchlist(existing)

    item = Watchlist(
        ticker=formatted,
        name=formatted,
        exchange=detected_exchange,
        asset_class=detected_asset,
        tier=tier,
        timeframe=timeframe,
        ltrp=ltrp if ltrp > 0 else None,
        pivot_high=pivot_high if pivot_high > 0 else None,
        source="Manual",
        added_by="user",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _serialize_watchlist(item)


@router.delete("/api/watchlist/{item_id}")
async def api_watchlist_remove(item_id: int, db: Session = Depends(get_db)):
    """Remove stock from watchlist."""
    item = db.query(Watchlist).filter(Watchlist.id == item_id).first()
    if not item:
        return {"status": "error", "message": "Item not found"}
    db.delete(item)
    db.commit()
    return {"status": "ok", "id": item_id}


@router.patch("/api/watchlist/{item_id}/toggle")
async def api_watchlist_toggle(item_id: int, db: Session = Depends(get_db)):
    """Toggle watchlist item active status."""
    item = db.query(Watchlist).filter(Watchlist.id == item_id).first()
    if not item:
        return {"status": "error", "message": "Item not found"}
    item.active = not item.active
    db.commit()
    db.refresh(item)
    return _serialize_watchlist(item)
