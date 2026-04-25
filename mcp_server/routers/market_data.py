"""Market data — dashboard overview + accuracy + news + movers + cache.

Extracted from mcp_server.mcp_server in Phase 3c of the router split.
16 routes moved verbatim.

Clusters:
  - Dashboard aggregates (overview, accuracy)
  - News feed (news, market_news, check_news_alerts, ai_report, news_sentiment)
  - Momentum ranking (api/momentum, momentum_rankings, momentum_rebalance)
  - Market movers (top gainers / losers / 52W high-low / most active)
  - OHLCV cache management (stats, refresh, purge)
  - Realtime WebSocket status (live-prices, realtime/status)

Deferred imports (stay in mcp_server.py — module-level singletons / caches):
  - _index_cache, _market_movers_cache, _market_movers_ts
  - _fetch_market_movers (heavy helper)
  - _realtime_engine, _now_ist
"""
import logging
from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import case, desc, func
from sqlalchemy.orm import Session

from mcp_server.db import SessionLocal, get_db
from mcp_server.models import ActiveTrade, MWAScore, Outcome, Signal, Watchlist
from mcp_server.routers.deps import limiter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["market-data"])


# ── Request models ─────────────────────────────────────────────────


class CacheRefreshRequest(BaseModel):
    ticker: str
    interval: str = "1d"
    period: str = "1y"


class CachePurgeRequest(BaseModel):
    days_to_keep: int = 1825


# ── Dashboard aggregates ──────────────────────────────────────────


@router.get("/api/overview")
async def api_overview(
    exchange: str = "",
    asset_class: str = "",
    db: Session = Depends(get_db),
):
    """Dashboard overview data. Optional filter by exchange/asset_class."""
    from mcp_server import mcp_server as _ms
    from mcp_server.market_calendar import get_market_status

    wl_query = db.query(Watchlist).filter(Watchlist.active.is_(True))
    at_query = db.query(ActiveTrade)
    sig_query = db.query(Signal)
    today_query = db.query(Signal).filter(Signal.signal_date == date.today())

    if exchange:
        wl_query = wl_query.filter(Watchlist.exchange == exchange.upper())
        at_query = at_query.filter(ActiveTrade.exchange == exchange.upper())
        sig_query = sig_query.filter(Signal.exchange == exchange.upper())
        today_query = today_query.filter(Signal.exchange == exchange.upper())
    if asset_class:
        wl_query = wl_query.filter(Watchlist.asset_class == asset_class.upper())
        at_query = at_query.filter(ActiveTrade.asset_class == asset_class.upper())
        sig_query = sig_query.filter(Signal.asset_class == asset_class.upper())
        today_query = today_query.filter(Signal.asset_class == asset_class.upper())

    watchlist_count = wl_query.count()
    active_trades = at_query.count()
    total_signals = sig_query.count()
    today_signals = today_query.count()

    latest_mwa = db.query(MWAScore).order_by(desc(MWAScore.score_date)).first()

    outcome_query = db.query(Outcome)
    if exchange or asset_class:
        outcome_query = outcome_query.join(Signal, Outcome.signal_id == Signal.id)
        if exchange:
            outcome_query = outcome_query.filter(Signal.exchange == exchange.upper())
        if asset_class:
            outcome_query = outcome_query.filter(Signal.asset_class == asset_class.upper())
    total_outcomes = outcome_query.count()
    wins = outcome_query.filter(Outcome.outcome == "WIN").count()
    win_rate = round((wins / total_outcomes * 100), 1) if total_outcomes > 0 else 0

    ms = get_market_status("NSE")
    reason = ms.get("reason", "CLOSED")
    status_map = {"OPEN": "LIVE", "PRE_MARKET": "PRE", "POST_MARKET": "POST"}
    market_status = status_map.get(reason, "CLOSED")

    # Index prices — use global cache only, never block this endpoint
    ic = getattr(_ms, "_index_cache", None) or {}
    nifty_price = ic.get("nifty_price", 0)
    nifty_change = ic.get("nifty_change", 0)
    nifty_change_pct = ic.get("nifty_change_pct", 0)
    banknifty_price = ic.get("banknifty_price", 0)
    banknifty_change = ic.get("banknifty_change", 0)
    banknifty_change_pct = ic.get("banknifty_change_pct", 0)

    return {
        "watchlist_count": watchlist_count,
        "active_trades": active_trades,
        "total_signals": total_signals,
        "today_signals": today_signals,
        "mwa_direction": latest_mwa.direction if latest_mwa else "N/A",
        "mwa_bull_pct": float(latest_mwa.bull_pct) if latest_mwa and latest_mwa.bull_pct else 0,
        "mwa_bear_pct": float(latest_mwa.bear_pct) if latest_mwa and latest_mwa.bear_pct else 0,
        "win_rate": win_rate,
        "total_outcomes": total_outcomes,
        "market_status": market_status,
        "nifty_price": nifty_price,
        "nifty_change": nifty_change,
        "nifty_change_pct": nifty_change_pct,
        "banknifty_price": banknifty_price,
        "banknifty_change": banknifty_change,
        "banknifty_change_pct": banknifty_change_pct,
    }


@router.get("/api/accuracy")
async def api_accuracy(
    exchange: str = "",
    asset_class: str = "",
    db: Session = Depends(get_db),
):
    """Accuracy metrics for dashboard with breakdowns. Optional filter by exchange/asset_class."""
    outcome_base = db.query(Outcome)
    signal_base = db.query(Signal)
    if exchange or asset_class:
        outcome_base = outcome_base.join(Signal, Outcome.signal_id == Signal.id)
        if exchange:
            outcome_base = outcome_base.filter(Signal.exchange == exchange.upper())
            signal_base = signal_base.filter(Signal.exchange == exchange.upper())
        if asset_class:
            outcome_base = outcome_base.filter(Signal.asset_class == asset_class.upper())
            signal_base = signal_base.filter(Signal.asset_class == asset_class.upper())

    total = outcome_base.count()
    wins = outcome_base.filter(Outcome.outcome == "WIN").count()
    losses = outcome_base.filter(Outcome.outcome == "LOSS").count()
    open_count = signal_base.filter(Signal.status == "OPEN").count()

    pnl_query = db.query(func.sum(Outcome.pnl_amount))
    rrr_query = db.query(func.avg(Signal.rrr))
    if exchange or asset_class:
        pnl_query = pnl_query.join(Signal, Outcome.signal_id == Signal.id)
        if exchange:
            pnl_query = pnl_query.filter(Signal.exchange == exchange.upper())
            rrr_query = rrr_query.filter(Signal.exchange == exchange.upper())
        if asset_class:
            pnl_query = pnl_query.filter(Signal.asset_class == asset_class.upper())
            rrr_query = rrr_query.filter(Signal.asset_class == asset_class.upper())
    total_pnl = pnl_query.scalar() or 0
    avg_rrr_val = rrr_query.scalar() or 0

    # By pattern
    pattern_query = (
        db.query(
            Signal.pattern,
            func.count(Outcome.id).label("total"),
            func.sum(case((Outcome.outcome == "WIN", 1), else_=0)).label("wins"),
        )
        .join(Signal, Outcome.signal_id == Signal.id)
    )
    if exchange:
        pattern_query = pattern_query.filter(Signal.exchange == exchange.upper())
    if asset_class:
        pattern_query = pattern_query.filter(Signal.asset_class == asset_class.upper())
    pattern_rows = pattern_query.group_by(Signal.pattern).all()
    by_pattern = [
        {
            "pattern": row.pattern or "Unknown",
            "total": row.total,
            "wins": int(row.wins),
            "win_rate": round(int(row.wins) / row.total * 100, 1) if row.total > 0 else 0,
        }
        for row in pattern_rows
    ]

    # By direction
    dir_query = (
        db.query(
            Signal.direction,
            func.count(Outcome.id).label("total"),
            func.sum(case((Outcome.outcome == "WIN", 1), else_=0)).label("wins"),
        )
        .join(Signal, Outcome.signal_id == Signal.id)
    )
    if exchange:
        dir_query = dir_query.filter(Signal.exchange == exchange.upper())
    if asset_class:
        dir_query = dir_query.filter(Signal.asset_class == asset_class.upper())
    direction_rows = dir_query.group_by(Signal.direction).all()
    by_direction = [
        {
            "direction": row.direction,
            "total": row.total,
            "wins": int(row.wins),
            "win_rate": round(int(row.wins) / row.total * 100, 1) if row.total > 0 else 0,
        }
        for row in direction_rows
    ]

    # Monthly PnL
    monthly_query = db.query(Outcome).filter(Outcome.exit_date.isnot(None))
    if exchange or asset_class:
        monthly_query = monthly_query.join(Signal, Outcome.signal_id == Signal.id)
        if exchange:
            monthly_query = monthly_query.filter(Signal.exchange == exchange.upper())
        if asset_class:
            monthly_query = monthly_query.filter(Signal.asset_class == asset_class.upper())
    all_outcomes = monthly_query.order_by(Outcome.exit_date).all()
    monthly: dict = {}
    for o in all_outcomes:
        month_key = o.exit_date.strftime("%b %Y") if o.exit_date else "Unknown"
        if month_key not in monthly:
            monthly[month_key] = {"pnl": 0, "trades": 0, "wins": 0}
        monthly[month_key]["pnl"] += float(o.pnl_amount or 0)
        monthly[month_key]["trades"] += 1
        if o.outcome == "WIN":
            monthly[month_key]["wins"] += 1
    monthly_pnl = [
        {
            "month": k,
            "pnl": round(v["pnl"], 2),
            "trades": v["trades"],
            "win_rate": round(v["wins"] / v["trades"] * 100, 1) if v["trades"] > 0 else 0,
        }
        for k, v in monthly.items()
    ]

    return {
        "total_signals": total + open_count,
        "wins": wins,
        "losses": losses,
        "open": open_count,
        "win_rate": round((wins / total * 100), 1) if total > 0 else 0,
        "target_rate": round((wins / (total + open_count) * 100), 1) if (total + open_count) > 0 else 0,
        "total_pnl": round(float(total_pnl), 2),
        "avg_rrr": round(float(avg_rrr_val), 2),
        "by_pattern": by_pattern,
        "by_direction": by_direction,
        "monthly_pnl": monthly_pnl,
    }


# ── News ───────────────────────────────────────────────────────────


@router.get("/api/news")
async def api_news(
    hours: int = Query(default=24, ge=1, le=168),
    min_impact: str = Query(default="LOW"),
):
    """Get latest news items classified by impact. For dashboard consumption."""
    from mcp_server.news_monitor import get_latest_news
    from dataclasses import asdict as _asdict

    items = get_latest_news(hours=hours, min_impact=min_impact.upper())
    return [_asdict(item) for item in items[:100]]


@router.get("/tools/market_news")
async def tool_market_news(
    hours: int = Query(default=12, ge=1, le=168),
    min_impact: str = Query(default="MEDIUM"),
):
    """MCP tool: Get market news for Claude analysis."""
    from mcp_server.news_monitor import get_latest_news
    from dataclasses import asdict as _asdict

    items = get_latest_news(hours=hours, min_impact=min_impact.upper())
    return {
        "status": "ok",
        "tool": "market_news",
        "count": len(items),
        "items": [_asdict(item) for item in items[:50]],
    }


@router.post("/tools/check_news_alerts")
async def tool_check_news_alerts():
    """Trigger news check and send HIGH-impact alerts to Telegram."""
    from mcp_server.news_monitor import check_and_alert

    result = await check_and_alert()
    return {"status": "ok", "tool": "check_news_alerts", **result}


@router.post("/tools/ai_report")
async def tool_ai_report(request: Request):
    """Generate an AI narrative report (morning brief or EOD).

    Body: {"report_type": "morning"|"eod", "data": {...}}
    """
    body = await request.json()
    report_type = body.get("report_type", "eod")
    data = body.get("data", {})
    from mcp_server.wallstreet_tools import generate_ai_report

    report = await generate_ai_report(report_type, data)
    return {"status": "ok", "tool": "ai_report", "report_type": report_type, "report": report}


@router.post("/tools/news_sentiment")
async def tool_news_sentiment(request: Request):
    """Get AI-scored news sentiment for a symbol.

    Body: {"symbol": "RELIANCE"}
    """
    body = await request.json()
    symbol = body.get("symbol", "")
    if not symbol:
        return {"status": "error", "message": "symbol is required"}
    from mcp_server.news_monitor import calculate_news_sentiment

    result = calculate_news_sentiment(symbol)
    return {"status": "ok", "tool": "news_sentiment", "symbol": symbol, **result}


# ── Momentum ranking ──────────────────────────────────────────────


@router.get("/api/momentum")
async def api_momentum():
    """Get cached momentum rankings + portfolio + rebalance signals for dashboard."""
    from mcp_server.momentum_ranker import get_momentum_portfolio

    portfolio = get_momentum_portfolio()
    if not portfolio:
        return {
            "ranked_at": None,
            "top_n": 0,
            "holdings": [],
            "rankings": [],
            "signals": [],
            "message": "No momentum scan yet. Trigger a rebalance to generate rankings.",
        }
    return portfolio


@router.get("/tools/momentum_rankings")
async def tool_momentum_rankings(top_n: int = Query(default=10, ge=1, le=50)):
    """MCP tool: Get current momentum rankings for Claude analysis."""
    from mcp_server.momentum_ranker import get_momentum_portfolio

    portfolio = get_momentum_portfolio()
    if not portfolio:
        return {
            "status": "ok",
            "tool": "momentum_rankings",
            "count": 0,
            "rankings": [],
            "message": "No rankings available. Run momentum_rebalance first.",
        }
    rankings = portfolio.get("rankings", [])[:top_n]
    return {
        "status": "ok",
        "tool": "momentum_rankings",
        "ranked_at": portfolio.get("ranked_at"),
        "count": len(rankings),
        "rankings": rankings,
    }


@router.post("/tools/momentum_rebalance")
@limiter.limit("30/minute")
async def tool_momentum_rebalance(request: Request, top_n: int = Query(default=10, ge=1, le=50)):
    """Trigger full universe momentum scan and generate rebalance signals.

    Takes ~40-75s due to rate-limited yfinance calls.
    """
    from mcp_server.momentum_ranker import (
        rank_universe,
        generate_rebalance_signals,
        get_momentum_portfolio,
        save_momentum_portfolio,
    )
    from dataclasses import asdict as _asdict

    prev = get_momentum_portfolio()
    current_holdings = prev.get("holdings", []) if prev else []

    rankings = rank_universe(top_n=top_n)
    signals = generate_rebalance_signals(current_holdings, rankings, top_n=top_n)

    payload = save_momentum_portfolio(rankings, signals, top_n=top_n)

    return {
        "status": "ok",
        "tool": "momentum_rebalance",
        "top_n": top_n,
        "stocks_scored": len(rankings),
        "buy_signals": len([s for s in signals if s.action == "BUY"]),
        "sell_signals": len([s for s in signals if s.action == "SELL"]),
        "rankings": [_asdict(s) for s in rankings],
        "signals": [_asdict(s) for s in signals],
        "ranked_at": payload.get("ranked_at"),
    }


# ── Market movers ─────────────────────────────────────────────────


@router.get("/api/market-movers")
async def api_market_movers(
    category: str = Query(default="gainers", pattern="^(gainers|losers|week52_high|week52_low|most_active)$"),
    exchange: str = Query(default="ALL"),
):
    """Market movers: top gainers, losers, 52W high/low, most active.

    Cached for 5 minutes during market hours.
    """
    from mcp_server import mcp_server as _ms

    now = _ms._now_ist()
    stale = (
        _ms._market_movers_ts is None
        or (now - _ms._market_movers_ts).total_seconds() > 300
    )

    if stale or not _ms._market_movers_cache:
        try:
            _ms._market_movers_cache = _ms._fetch_market_movers()
            _ms._market_movers_ts = now
        except Exception as e:
            logger.error("Market movers fetch failed: %s", e)
            if not _ms._market_movers_cache:
                return {"category": category, "stocks": [], "error": str(e)}

    stocks = _ms._market_movers_cache.get(category, [])

    if exchange != "ALL":
        stocks = [s for s in stocks if s["exchange"] == exchange.upper()]

    return {
        "category": category,
        "exchange": exchange,
        "stocks": stocks,
        "total": len(stocks),
        "fetched_at": _ms._market_movers_cache.get("fetched_at"),
        "total_universe": _ms._market_movers_cache.get("total_stocks", 0),
    }


# ── OHLCV cache management ────────────────────────────────────────


@router.get("/api/cache/stats")
async def api_cache_stats():
    """Cache size, hit rate, unique tickers, interval breakdown."""
    from mcp_server.ohlcv_cache import get_cache_stats

    db_session = SessionLocal()
    try:
        stats = get_cache_stats(db_session)
        return {"status": "ok", **stats}
    finally:
        db_session.close()


@router.post("/tools/cache_refresh")
async def tool_cache_refresh(req: CacheRefreshRequest):
    """Force-refresh cached data for a ticker (invalidate + re-fetch)."""
    from mcp_server.ohlcv_cache import invalidate_ticker
    from mcp_server.data_provider import get_stock_data

    db_session = SessionLocal()
    try:
        deleted = invalidate_ticker(db_session, req.ticker, req.interval)
    finally:
        db_session.close()

    df = get_stock_data(req.ticker, period=req.period, interval=req.interval, force_refresh=True)

    return {
        "status": "ok",
        "tool": "cache_refresh",
        "ticker": req.ticker,
        "interval": req.interval,
        "deleted_rows": deleted,
        "new_bars": len(df) if df is not None and not df.empty else 0,
    }


@router.post("/tools/cache_purge")
async def tool_cache_purge(req: CachePurgeRequest):
    """Delete cached data older than N days (default 5 years)."""
    from mcp_server.ohlcv_cache import purge_old_data

    db_session = SessionLocal()
    try:
        deleted = purge_old_data(db_session, days_to_keep=req.days_to_keep)
    finally:
        db_session.close()

    return {
        "status": "ok",
        "tool": "cache_purge",
        "days_to_keep": req.days_to_keep,
        "deleted_rows": deleted,
    }


# ── Realtime WebSocket status ──────────────────────────────────────


@router.get("/api/live-prices")
async def api_live_prices(symbols: str = Query(..., description="Comma-separated symbols")):
    """Batch LTP from WebSocket tick cache."""
    from mcp_server import mcp_server as _ms

    syms = [s.strip() for s in symbols.split(",") if s.strip()]
    engine = getattr(_ms, "_realtime_engine", None)
    if engine:
        return engine.cache.get_multiple_ltps(syms)
    return {s: None for s in syms}


@router.get("/api/realtime/status")
async def api_realtime_status():
    """RealtimeEngine health / status."""
    from mcp_server import mcp_server as _ms

    engine = getattr(_ms, "_realtime_engine", None)
    if not engine:
        return {"active": False, "reason": "engine_not_started"}
    return {
        "active": engine._active,
        "websocket_connected": (
            engine.gwc_ws.connected if engine.gwc_ws else False
        ),
        "subscribed_symbols": len(engine._subscribed_symbols),
        "monitored_positions": len(engine.monitor.positions),
        "redis_available": engine.cache._available,
    }


# ── Regime detector ────────────────────────────────────────────────


@router.get("/api/events/status")
async def api_events_status():
    """Return the event calendar status — blackout state, upcoming 24h events,
    today's options expiry instruments, and total events loaded.
    """
    from mcp_server.event_calendar import get_calendar
    return get_calendar().status()


@router.get("/api/events/upcoming")
async def api_events_upcoming(hours: float = 48):
    """Return all events within the next `hours` hours."""
    from mcp_server.event_calendar import get_calendar
    cal = get_calendar()
    events = cal.upcoming(hours=hours)
    return {
        "hours": hours,
        "count": len(events),
        "events": [
            {"type": e.type, "dt": e.dt.isoformat(),
             "hours_until": round(e.hours_until(), 1),
             "buffer_hours": e.buffer_hours, "notes": e.notes}
            for e in events
        ],
    }


@router.get("/api/regime/{ticker}")
async def api_regime(
    ticker: str,
    days: int = 90,
    adx_trending: float = 25.0,
    atr_volatile_pct: float = 3.0,
):
    """Classify the current market regime for a ticker.

    Returns the ADX-based regime label (TRENDING_UP / TRENDING_DOWN /
    RANGING / VOLATILE) plus the raw ADX, ±DI, and ATR% values.

    Query params let callers override the classification thresholds
    without a code change — useful for tuning during backtesting.
    """
    import asyncio
    from mcp_server.nse_scanner import get_stock_data
    from mcp_server.regime_detector import classify_from_df

    df = await asyncio.to_thread(get_stock_data, ticker, f"{days}d", "1d")
    if df is None or df.empty:
        return {"error": f"No data for {ticker}", "ticker": ticker}

    regime = classify_from_df(
        df,
        adx_trending=adx_trending,
        atr_volatile_pct=atr_volatile_pct,
    )
    return {"ticker": ticker, "days": days, **regime.as_dict()}
