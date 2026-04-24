"""Trades — order execution, position management, broker connectivity.

Extracted from mcp_server.mcp_server in Phase 2e of the router split.
17 routes moved verbatim.

Clusters:
  - Dashboard read (/api/trades/active)
  - Order lifecycle (place, cancel, close, close-all)
  - Position maintenance (update_pnl, update_trailing_sl,
    refresh_trade_prices, check_exit_strategies)
  - Portfolio view (portfolio_exposure, order_status, pretrade_check)
  - Broker connectivity (connect_kite, connect_gwc, connect_angel,
    angel_status)

Deferred imports: `_get_order_manager`, `_get_live_ltp`, `_realtime_engine`
stay in mcp_server.py — they're used by lifespan tasks + other handlers
still there.
"""
import asyncio
import logging
from dataclasses import asdict as _asdict

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from mcp_server.db import get_db
from mcp_server.models import ActiveTrade
from mcp_server.routers.deps import limiter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["trades"])


# ── Request models ─────────────────────────────────────────────────


class PlaceOrderRequest(BaseModel):
    ticker: str
    direction: str  # BUY or SELL
    qty: int
    price: float = 0
    order_type: str = "LIMIT"
    product: str = "CNC"
    stop_loss: float = 0
    target: float = 0
    tag: str = ""


class CancelOrderRequest(BaseModel):
    order_id: str


class ClosePositionRequest(BaseModel):
    ticker: str


# ── Dashboard read ─────────────────────────────────────────────────


@router.get("/api/trades/active")
async def api_active_trades(
    response: Response,
    exchange: str = "",
    asset_class: str = "",
    timeframe: str = "",
    db: Session = Depends(get_db),
):
    """Active trades for dashboard. Optional filter by exchange/asset_class/timeframe."""
    response.headers["Cache-Control"] = "no-store"
    query = db.query(ActiveTrade).options(joinedload(ActiveTrade.signal))
    if exchange:
        query = query.filter(ActiveTrade.exchange == exchange.upper())
    if asset_class:
        query = query.filter(ActiveTrade.asset_class == asset_class.upper())
    if timeframe:
        query = query.filter(ActiveTrade.timeframe == timeframe)
    trades = query.order_by(ActiveTrade.id.desc()).limit(100).all()
    result = []
    for t in trades:
        direction = t.signal.direction if t.signal else "LONG"
        is_short = direction in ("SELL", "SHORT")
        if t.current_price and t.entry_price:
            entry = float(t.entry_price)
            current = float(t.current_price)
            pnl = round(((entry - current) if is_short else (current - entry)) / entry * 100, 2)
        else:
            pnl = 0
        result.append({
            "id": t.id,
            "signal_id": t.signal_id,
            "ticker": t.ticker,
            "exchange": t.exchange or "NSE",
            "asset_class": t.asset_class or "EQUITY",
            "timeframe": t.timeframe or "1D",
            "entry_price": float(t.entry_price),
            "target": float(t.target),
            "stop_loss": float(t.stop_loss),
            "prrr": float(t.prrr) if t.prrr else 0,
            "current_price": float(t.current_price) if t.current_price else 0,
            "crrr": float(t.crrr) if t.crrr else 0,
            "pnl_pct": pnl,
            "alert_sent": t.alert_sent or False,
            "direction": direction,
            "last_updated": str(t.last_updated) if t.last_updated else None,
        })
    return result


# ── Order lifecycle ────────────────────────────────────────────────


@router.post("/tools/place_order")
@limiter.limit("5/minute")
async def tool_place_order(request: Request, req: PlaceOrderRequest):
    """Place a live order with safety controls."""
    from mcp_server import mcp_server as _ms
    manager = _ms._get_order_manager()
    result = manager.place_order(
        ticker=req.ticker,
        direction=req.direction,
        qty=req.qty,
        price=req.price,
        order_type=req.order_type,
        product=req.product,
        stop_loss=req.stop_loss,
        target=req.target,
        tag=req.tag,
    )
    return _asdict(result)


@router.post("/tools/cancel_order")
async def tool_cancel_order(req: CancelOrderRequest):
    """Cancel a pending order."""
    from mcp_server import mcp_server as _ms
    manager = _ms._get_order_manager()
    result = manager.cancel_order(req.order_id)
    return _asdict(result)


@router.post("/tools/close_position")
async def tool_close_position(req: ClosePositionRequest):
    """Close an open position at market."""
    from mcp_server import mcp_server as _ms
    manager = _ms._get_order_manager()
    result = manager.close_position(req.ticker)
    return _asdict(result)


@router.post("/tools/close_all")
@limiter.limit("5/minute")
async def tool_close_all(request: Request):
    """EMERGENCY: Close all open positions at market."""
    from mcp_server import mcp_server as _ms
    manager = _ms._get_order_manager()
    results = manager.close_all_positions()
    return [_asdict(r) for r in results]


@router.get("/tools/order_status")
async def tool_order_status():
    """Get order manager status including kill switch state."""
    from mcp_server import mcp_server as _ms
    manager = _ms._get_order_manager()
    return manager.get_status()


# ── Position maintenance ───────────────────────────────────────────


@router.post("/tools/update_pnl")
async def tool_update_pnl(realized_pnl: float = Query(...)):
    """Update daily realized P&L for kill switch tracking."""
    from mcp_server import mcp_server as _ms
    manager = _ms._get_order_manager()
    manager.update_pnl(realized_pnl)
    return manager.get_status()


@router.post("/tools/update_trailing_sl")
async def tool_update_trailing_sl(ticker: str = Query(...), current_price: float = Query(...)):
    """Update trailing SL for a position given current market price."""
    from mcp_server import mcp_server as _ms
    manager = _ms._get_order_manager()
    return manager.update_trailing_sl(ticker, current_price)


@router.post("/tools/update_all_trailing_sl")
async def tool_update_all_trailing_sl():
    """Update trailing SL for ALL open positions using live prices."""
    from mcp_server import mcp_server as _ms
    manager = _ms._get_order_manager()

    results = []
    for pos in manager.open_positions:
        ticker = pos.get("ticker", "")
        try:
            ltp = _ms._get_live_ltp(ticker)
            if ltp:
                result = manager.update_trailing_sl(ticker, ltp)
                result["ticker"] = ticker
                result["ltp"] = ltp
                results.append(result)
        except Exception as e:
            results.append({"ticker": ticker, "updated": False, "message": str(e)})

    return {"positions_checked": len(results), "results": results}


@router.post("/tools/refresh_trade_prices")
async def tool_refresh_trade_prices(db: Session = Depends(get_db)):
    """Fetch live prices for all active trades and update DB."""
    from datetime import datetime as _dt
    from mcp_server import mcp_server as _ms

    trades = db.query(ActiveTrade).options(joinedload(ActiveTrade.signal)).all()
    updated = []
    for t in trades:
        try:
            ltp = _ms._get_live_ltp(t.ticker)
            if ltp and ltp > 0:
                t.current_price = ltp
                t.last_updated = _dt.now()
                direction = t.signal.direction if t.signal else "LONG"
                is_short = direction in ("SELL", "SHORT")
                risk = (float(t.stop_loss) - ltp) if is_short else (ltp - float(t.stop_loss))
                reward = (ltp - float(t.target)) if is_short else (float(t.target) - ltp)
                t.crrr = round(reward / risk, 2) if risk > 0 else 0
                updated.append({
                    "ticker": t.ticker,
                    "price": ltp,
                    "crrr": float(t.crrr),
                })
        except Exception as e:
            logger.error("Price refresh error for %s: %s", t.ticker, e)
    if updated:
        db.commit()
    return {"updated": len(updated), "total": len(trades), "prices": updated}


@router.get("/tools/portfolio_exposure")
async def tool_portfolio_exposure():
    """Get current portfolio sector/asset-class exposure breakdown."""
    from mcp_server import mcp_server as _ms
    from mcp_server.portfolio_risk import get_portfolio_exposure
    manager = _ms._get_order_manager()
    return get_portfolio_exposure(manager.open_positions, manager.capital)


@router.post("/tools/check_exit_strategies")
async def tool_check_exit_strategies():
    """Evaluate exit strategy for ALL open positions using live prices."""
    from mcp_server import mcp_server as _ms
    manager = _ms._get_order_manager()

    results = []
    for pos in manager.open_positions:
        ticker = pos.get("ticker", "")
        try:
            ltp = _ms._get_live_ltp(ticker)
            if ltp:
                result = manager.evaluate_exit_strategy(ticker, ltp)
                result["ticker"] = ticker
                result["ltp"] = ltp
                results.append(result)
        except Exception as e:
            results.append({"ticker": ticker, "action": "ERROR", "message": str(e)})

    return {"checked": len(results), "results": results}


@router.post("/tools/pretrade_check")
async def tool_pretrade_check(signal_id: int = Query(...), db: Session = Depends(get_db)):
    """Run 10 automated pre-trade checks for a signal."""
    from mcp_server.pretrade_check import run_pretrade_checks
    return run_pretrade_checks(signal_id, db)


# ── Broker connectivity ────────────────────────────────────────────


@router.post("/tools/connect_kite")
async def tool_connect_kite():
    """Connect Kite to the order manager using kite_auth."""
    from mcp_server import mcp_server as _ms
    manager = _ms._get_order_manager()
    if manager.kite is not None:
        return {"kite_connected": True, "message": "Already connected"}

    def _do_connect():
        from mcp_server.kite_auth import get_authenticated_kite
        kite = get_authenticated_kite()  # blocking TOTP login flow
        capital = None
        try:
            margins = kite.margins("equity")
            if margins and "available" in margins:
                capital = float(margins["available"].get("live_balance", 100000))
        except Exception:
            pass
        return kite, capital

    try:
        kite, capital = await asyncio.to_thread(_do_connect)
        manager.kite = kite
        if capital is not None:
            manager.capital = capital
        return {
            "kite_connected": True,
            "message": "Kite connected successfully",
            "capital": manager.capital,
        }
    except Exception as e:
        logger.error("Kite connection failed: %s", e)
        return {
            "kite_connected": False,
            "message": f"Kite connection failed: {e}",
        }


@router.post("/tools/connect_gwc")
async def tool_connect_gwc():
    """Activate Goodwill (GWC) as a live data source via auto-login.

    Mirrors /tools/connect_kite — runs the full GWC login flow in a worker
    thread and wires the resulting access_token into the MarketDataProvider.
    """
    try:
        from mcp_server.gwc_auth import refresh_gwc_token
        from mcp_server.data_provider import get_provider
        access_token = await asyncio.to_thread(refresh_gwc_token)
        provider = get_provider()
        provider.gwc.set_access_token(access_token)
        provider._sources["gwc"] = True
        return {
            "gwc_connected": True,
            "token_prefix": access_token[:8] + "..." if access_token else None,
            "message": "Goodwill connected via auto-login",
        }
    except Exception as e:
        logger.error("GWC connect failed: %s", e)
        return {
            "gwc_connected": False,
            "message": f"GWC connect failed: {e}",
        }


@router.post("/tools/connect_angel")
async def tool_connect_angel():
    """Connect Angel One to the order manager using angel_auth."""
    from mcp_server import mcp_server as _ms
    manager = _ms._get_order_manager()
    if manager.broker is not None:
        return {"angel_connected": True, "message": "Already connected"}

    def _do_connect():
        from mcp_server.angel_auth import get_authenticated_angel
        client = get_authenticated_angel()

        from mcp_server.data_provider import AngelSource
        angel = AngelSource()
        angel.client = client
        angel.logged_in = True

        capital = None
        try:
            rms = client.rms()
            if rms and rms.get("data"):
                net = rms["data"].get("net", rms["data"].get("availablecash", 0))
                if net:
                    capital = float(net)
        except Exception:
            pass
        return angel, capital

    try:
        angel, capital = await asyncio.to_thread(_do_connect)
        manager.broker = angel
        if capital is not None:
            manager.capital = capital

        # Manual reconnect should clear the session-level circuit breaker on
        # the data provider's Angel (only the user can confirm IP whitelist
        # has been updated upstream).
        try:
            from mcp_server.data_provider import get_provider
            provider = get_provider()
            if hasattr(provider, "angel") and provider.angel:
                provider.angel.client = angel.client
                provider.angel.logged_in = True
                provider.angel._session_disabled = False
                provider.angel._consecutive_failures = 0
                if hasattr(provider.angel, "_token_cache"):
                    provider.angel._token_cache.clear()
                provider._sources["angel"] = True
                logger.info("Angel circuit breaker reset by manual connect")
        except Exception as reset_err:
            logger.warning("Could not reset provider Angel: %s", reset_err)

        return {
            "angel_connected": True,
            "message": "Angel One connected successfully",
            "capital": manager.capital,
        }
    except Exception as e:
        logger.error("Angel connect failed: %s", e)
        return {
            "angel_connected": False,
            "message": f"Angel connect failed: {e}",
        }


@router.get("/tools/angel_status")
async def tool_angel_status():
    """Get Angel One connection status + positions/holdings count."""
    from mcp_server import mcp_server as _ms
    manager = _ms._get_order_manager()
    angel = manager.broker

    if angel is None or not getattr(angel, "logged_in", False):
        return {
            "logged_in": False,
            "message": "Angel not connected — call /tools/connect_angel first",
        }

    def _fetch_status():
        result = {"logged_in": True}
        try:
            positions = angel.get_positions()
            pos_data = positions.get("data", []) if isinstance(positions, dict) else []
            result["positions_count"] = len(pos_data) if pos_data else 0
        except Exception:
            result["positions_count"] = 0
        try:
            holdings = angel.get_holdings()
            hold_data = holdings.get("data", []) if isinstance(holdings, dict) else []
            result["holdings_count"] = len(hold_data) if hold_data else 0
        except Exception:
            result["holdings_count"] = 0
        try:
            balance = angel.get_balance()
            if balance and balance.get("data"):
                result["available_cash"] = balance["data"].get("availablecash", "N/A")
                result["net"] = balance["data"].get("net", "N/A")
        except Exception:
            pass
        return result

    return await asyncio.to_thread(_fetch_status)
