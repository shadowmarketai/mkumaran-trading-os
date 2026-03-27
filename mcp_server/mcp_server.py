import logging
from dataclasses import asdict
from datetime import date

from fastapi import FastAPI, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, case

from mcp_server.config import settings
from mcp_server.db import get_db, init_db, SessionLocal
from mcp_server.models import Watchlist, Signal, Outcome, MWAScore, ActiveTrade
from mcp_server.asset_registry import (
    parse_ticker, get_asset_class, get_exchange,
    get_supported_exchanges, Exchange, AssetClass,
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="MKUMARAN Trading OS - MCP Server",
    description="Hybrid Trading Intelligence MCP Server",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    try:
        logger.info("Initializing database...")
        init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.warning("Database init skipped (not available): %s", e)
    logger.info("MCP Server starting on %s:%s", settings.MCP_SERVER_HOST, settings.MCP_SERVER_PORT)


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "mkumaran-trading-os"}


# ============================================================
# MCP Tool Endpoints — wired to real engines
# ============================================================


@app.get("/api/exchanges")
async def api_exchanges():
    """List all supported exchanges and asset classes."""
    return get_supported_exchanges()


@app.post("/tools/get_stock_data")
async def tool_get_stock_data(
    ticker: str,
    timeframe: str = "day",
    days: int = 365,
):
    """Get OHLCV data for any instrument via yfinance. Supports NSE, BSE, MCX, CDS, NFO."""
    from mcp_server.nse_scanner import get_stock_data

    df = get_stock_data(ticker, period="1y", interval="1d")
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


@app.post("/tools/run_rrms")
async def tool_run_rrms(
    ticker: str,
    cmp: float = 0,
    ltrp: float = 0,
    pivot_high: float = 0,
    direction: str = "LONG",
):
    """Run RRMS position sizing calculation."""
    from mcp_server.rrms_engine import RRMSEngine

    engine = RRMSEngine()

    if cmp <= 0:
        # Try to fetch live price via yfinance
        from mcp_server.nse_scanner import get_stock_data

        df = get_stock_data(ticker, days=5)
        if df is not None and not df.empty:
            cmp = float(df["Close"].iloc[-1])
        else:
            return {"status": "error", "message": "CMP required (auto-fetch failed)"}

    result = engine.calculate(ticker, cmp, ltrp, pivot_high, direction)
    return {"status": "ok", "tool": "run_rrms", **asdict(result)}


@app.post("/tools/detect_pattern")
async def tool_detect_pattern(ticker: str, timeframe: str = "day"):
    """Detect all 12 price patterns on a stock."""
    from mcp_server.pattern_engine import PatternEngine
    from mcp_server.nse_scanner import get_stock_data

    df = get_stock_data(ticker, timeframe=timeframe)
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


@app.post("/tools/detect_smc")
async def tool_detect_smc(ticker: str, timeframe: str = "day"):
    """Detect Smart Money Concepts (SMC/ICT) patterns on a stock."""
    from mcp_server.smc_engine import SMCEngine
    from mcp_server.nse_scanner import get_stock_data

    df = get_stock_data(ticker, timeframe=timeframe)
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


@app.post("/tools/detect_wyckoff")
async def tool_detect_wyckoff(ticker: str, timeframe: str = "day"):
    """Detect Wyckoff market cycle patterns on a stock."""
    from mcp_server.wyckoff_engine import WyckoffEngine
    from mcp_server.nse_scanner import get_stock_data

    df = get_stock_data(ticker, timeframe=timeframe)
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


@app.post("/tools/detect_vsa")
async def tool_detect_vsa(ticker: str, timeframe: str = "day"):
    """Detect Volume Spread Analysis patterns on a stock."""
    from mcp_server.vsa_engine import VSAEngine
    from mcp_server.nse_scanner import get_stock_data

    df = get_stock_data(ticker, timeframe=timeframe)
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


@app.post("/tools/detect_harmonic")
async def tool_detect_harmonic(ticker: str, timeframe: str = "day"):
    """Detect Harmonic price patterns on a stock."""
    from mcp_server.harmonic_engine import HarmonicEngine
    from mcp_server.nse_scanner import get_stock_data

    df = get_stock_data(ticker, timeframe=timeframe)
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


@app.post("/tools/detect_rl")
async def tool_detect_rl(ticker: str, timeframe: str = "day"):
    """Detect RL-inspired patterns (regime, VWAP, momentum, optimal entry) on a stock."""
    from mcp_server.rl_engine import RLEngine
    from mcp_server.nse_scanner import get_stock_data

    df = get_stock_data(ticker, timeframe=timeframe)
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


@app.post("/tools/backtest_confluence")
async def tool_backtest_confluence(ticker: str, days: int = 365):
    """Compare all strategies side-by-side on a stock."""
    from mcp_server.backtester import run_backtest_all_strategies

    result = run_backtest_all_strategies(ticker, days=days)
    return {"status": "ok", "tool": "backtest_confluence", **result}


@app.post("/tools/get_mwa_score")
async def tool_get_mwa_score(db: Session = Depends(get_db)):
    """Get current MWA breadth score from DB or calculate fresh."""
    # Try to get today's score from DB
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

    # No score yet today — return latest available
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


@app.post("/tools/run_mwa_scan")
async def tool_run_mwa_scan(db: Session = Depends(get_db)):
    """Run the full 40-scanner MWA scan and persist score to DB."""
    from mcp_server.mwa_scanner import MWAScanner, SCANNERS
    from mcp_server.mwa_scoring import calculate_mwa_score, get_promoted_stocks, format_morning_brief

    scanner = MWAScanner()
    raw_results = scanner.run_all(save=True)

    score = calculate_mwa_score(raw_results)
    promoted = get_promoted_stocks(raw_results)
    brief = format_morning_brief(score)

    # Persist to DB
    today = date.today()
    existing = db.query(MWAScore).filter(MWAScore.score_date == today).first()
    if existing:
        existing.direction = score["direction"]
        existing.bull_score = score["bull_score"]
        existing.bear_score = score["bear_score"]
        existing.bull_pct = score["bull_pct"]
        existing.bear_pct = score["bear_pct"]
        existing.scanner_results = {k: len(v) if isinstance(v, list) else v for k, v in raw_results.items()}
        existing.promoted_stocks = promoted
    else:
        mwa = MWAScore(
            score_date=today,
            direction=score["direction"],
            bull_score=score["bull_score"],
            bear_score=score["bear_score"],
            bull_pct=score["bull_pct"],
            bear_pct=score["bear_pct"],
            scanner_results={k: len(v) if isinstance(v, list) else v for k, v in raw_results.items()},
            promoted_stocks=promoted,
        )
        db.add(mwa)
    db.commit()

    # Auto-sync to Google Sheets
    import asyncio
    asyncio.ensure_future(_auto_sync_sheets(mwa_data={
        "score_date": str(today),
        "direction": score["direction"],
        "bull_score": score["bull_score"],
        "bear_score": score["bear_score"],
        "bull_pct": score["bull_pct"],
        "bear_pct": score["bear_pct"],
    }))

    return {
        "status": "ok",
        "tool": "run_mwa_scan",
        "direction": score["direction"],
        "bull_pct": score["bull_pct"],
        "bear_pct": score["bear_pct"],
        "fired_bull": score["fired_bull"],
        "fired_bear": score["fired_bear"],
        "active_chains": score["active_chains"],
        "chain_boost": score["chain_boost"],
        "promoted_stocks": promoted,
        "scanner_count": len(raw_results),
        "morning_brief": brief,
    }


async def _auto_sync_sheets(signal_data: dict = None, mwa_data: dict = None):
    """Background auto-sync to Google Sheets. Non-blocking, fails silently."""
    try:
        from mcp_server.sheets_sync import log_signal, log_mwa
        if signal_data:
            log_signal(signal_data)
        if mwa_data:
            log_mwa(mwa_data)
    except Exception as e:
        logger.debug("Sheets auto-sync skipped: %s", e)


@app.post("/tools/backtest_strategy")
async def tool_backtest_strategy(
    ticker: str,
    strategy: str = "rrms",
    days: int = 365,
):
    """Backtest a strategy on historical data."""
    from mcp_server.backtester import run_backtest

    result = run_backtest(ticker, strategy=strategy, days=days)
    return {"status": "ok", "tool": "backtest_strategy", **result}


@app.post("/tools/manage_watchlist")
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


@app.post("/tools/get_active_trades")
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


@app.post("/tools/validate_signal")
async def tool_validate_signal(
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


@app.post("/tools/get_fo_signal")
async def tool_get_fo_signal():
    """Combined F&O signal: OI + PCR + EMA."""
    from mcp_server.fo_module import get_fo_signal

    result = get_fo_signal()
    return {"status": "ok", "tool": "get_fo_signal", **result}


# ============================================================
# Wall Street AI Prompt Tool Endpoints
# ============================================================


@app.post("/tools/wallstreet/fundamental_screen")
async def tool_ws_fundamental_screen(ticker: str, company_name: str = ""):
    """Goldman Sachs-style fundamental screening."""
    from mcp_server.wallstreet_tools import fundamental_screen

    result = fundamental_screen(ticker, company_name or ticker)
    return {"status": "ok", "tool": "fundamental_screen", **result}


@app.post("/tools/wallstreet/dcf_valuation")
async def tool_ws_dcf_valuation(ticker: str, company_name: str = ""):
    """Morgan Stanley-style DCF valuation."""
    from mcp_server.wallstreet_tools import dcf_valuation

    result = dcf_valuation(ticker, company_name or ticker)
    return {"status": "ok", "tool": "dcf_valuation", **result}


@app.post("/tools/wallstreet/risk_report")
async def tool_ws_risk_report(portfolio_tickers: str = ""):
    """Bridgewater All Weather risk analysis."""
    from mcp_server.wallstreet_tools import portfolio_risk_report

    tickers = [t.strip() for t in portfolio_tickers.split(",") if t.strip()]
    result = portfolio_risk_report(tickers)
    return {"status": "ok", "tool": "risk_report", **result}


@app.post("/tools/wallstreet/earnings_brief")
async def tool_ws_earnings_brief(ticker: str, company_name: str = ""):
    """JPMorgan pre-earnings brief."""
    from mcp_server.wallstreet_tools import pre_earnings_brief

    result = pre_earnings_brief(ticker, company_name or ticker)
    return {"status": "ok", "tool": "earnings_brief", **result}


@app.post("/tools/wallstreet/technical_summary")
async def tool_ws_technical_summary(ticker: str, ohlcv_summary: str = ""):
    """Citadel 3-sentence technical summary."""
    from mcp_server.wallstreet_tools import citadel_technical_summary

    result = citadel_technical_summary(ticker, ohlcv_summary)
    return {"status": "ok", "tool": "technical_summary", "text": result}


@app.post("/tools/wallstreet/sector_analysis")
async def tool_ws_sector_analysis(ticker: str, company_name: str = ""):
    """Bain competitive sector analysis."""
    from mcp_server.sector_picker import SectorPicker

    # SectorPicker needs kite; use without kite for fundamental-only analysis
    from mcp_server.sector_picker import fetch_stock_fundamentals, get_sector_peers

    peers = get_sector_peers(ticker)
    if not peers:
        return {"status": "ok", "tool": "sector_analysis", "message": f"No sector map for {ticker}"}

    fundamentals = fetch_stock_fundamentals(ticker)
    return {
        "status": "ok",
        "tool": "sector_analysis",
        "ticker": ticker,
        "sector": peers["sector"],
        "peers": peers["peers"],
        "fundamentals": fundamentals,
    }


@app.post("/tools/wallstreet/macro_assessment")
async def tool_ws_macro_assessment():
    """McKinsey macro sector rotation assessment."""
    from mcp_server.wallstreet_tools import macro_assessment

    result = macro_assessment()
    return {"status": "ok", "tool": "macro_assessment", **result}


# ============================================================
# Dashboard API endpoints (for React frontend)
# ============================================================


@app.get("/api/overview")
async def api_overview(db: Session = Depends(get_db)):
    """Dashboard overview data."""
    watchlist_count = db.query(Watchlist).filter(Watchlist.active.is_(True)).count()
    active_trades = db.query(ActiveTrade).count()
    total_signals = db.query(Signal).count()
    today_signals = db.query(Signal).filter(Signal.signal_date == date.today()).count()

    # Latest MWA
    latest_mwa = db.query(MWAScore).order_by(desc(MWAScore.score_date)).first()

    # Win rate
    total_outcomes = db.query(Outcome).count()
    wins = db.query(Outcome).filter(Outcome.outcome == "WIN").count()
    win_rate = round((wins / total_outcomes * 100), 1) if total_outcomes > 0 else 0

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
    }


@app.get("/api/signals")
async def api_signals(limit: int = 50, db: Session = Depends(get_db)):
    """Recent signals for dashboard."""
    signals = (
        db.query(Signal)
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


@app.get("/api/trades/active")
async def api_active_trades(
    exchange: str = "",
    db: Session = Depends(get_db),
):
    """Active trades for dashboard. Optional filter by exchange."""
    query = db.query(ActiveTrade)
    if exchange:
        query = query.filter(ActiveTrade.exchange == exchange.upper())
    trades = query.all()
    return [
        {
            "id": t.id,
            "signal_id": t.signal_id,
            "ticker": t.ticker,
            "exchange": t.exchange or "NSE",
            "asset_class": t.asset_class or "EQUITY",
            "entry_price": float(t.entry_price),
            "target": float(t.target),
            "stop_loss": float(t.stop_loss),
            "prrr": float(t.prrr) if t.prrr else 0,
            "current_price": float(t.current_price) if t.current_price else 0,
            "crrr": float(t.crrr) if t.crrr else 0,
            "pnl_pct": round(
                (float(t.current_price) - float(t.entry_price)) / float(t.entry_price) * 100, 2
            )
            if t.current_price and t.entry_price
            else 0,
            "alert_sent": t.alert_sent or False,
            "direction": t.signal.direction if t.signal else "LONG",
            "last_updated": str(t.last_updated) if t.last_updated else None,
        }
        for t in trades
    ]


@app.get("/api/mwa/latest")
async def api_mwa_latest(db: Session = Depends(get_db)):
    """Latest MWA score for dashboard."""
    score = db.query(MWAScore).order_by(desc(MWAScore.score_date)).first()
    if not score:
        return {"status": "no_data"}

    return {
        "id": score.id,
        "score_date": str(score.score_date),
        "direction": score.direction,
        "bull_score": float(score.bull_score or 0),
        "bear_score": float(score.bear_score or 0),
        "bull_pct": float(score.bull_pct or 0),
        "bear_pct": float(score.bear_pct or 0),
        "scanner_results": score.scanner_results or {},
        "promoted_stocks": score.promoted_stocks or [],
        "fii_net": float(score.fii_net or 0),
        "dii_net": float(score.dii_net or 0),
        "sector_strength": score.sector_strength or {},
    }


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


@app.get("/api/watchlist")
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


@app.post("/api/watchlist")
async def api_watchlist_add(
    ticker: str = Query(...),
    tier: int = Query(default=3),
    ltrp: float = Query(default=0),
    pivot_high: float = Query(default=0),
    timeframe: str = Query(default="1D"),
    db: Session = Depends(get_db),
):
    """Add instrument to watchlist. Supports EXCHANGE:SYMBOL format."""
    # Auto-detect exchange from ticker prefix
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


@app.delete("/api/watchlist/{item_id}")
async def api_watchlist_remove(item_id: int, db: Session = Depends(get_db)):
    """Remove stock from watchlist."""
    item = db.query(Watchlist).filter(Watchlist.id == item_id).first()
    if not item:
        return {"status": "error", "message": "Item not found"}
    db.delete(item)
    db.commit()
    return {"status": "ok", "id": item_id}


@app.patch("/api/watchlist/{item_id}/toggle")
async def api_watchlist_toggle(item_id: int, db: Session = Depends(get_db)):
    """Toggle watchlist item active status."""
    item = db.query(Watchlist).filter(Watchlist.id == item_id).first()
    if not item:
        return {"status": "error", "message": "Item not found"}
    item.active = not item.active
    db.commit()
    db.refresh(item)
    return _serialize_watchlist(item)


@app.get("/api/accuracy")
async def api_accuracy(db: Session = Depends(get_db)):
    """Accuracy metrics for dashboard with breakdowns."""
    total = db.query(Outcome).count()
    wins = db.query(Outcome).filter(Outcome.outcome == "WIN").count()
    losses = db.query(Outcome).filter(Outcome.outcome == "LOSS").count()
    open_count = db.query(Signal).filter(Signal.status == "OPEN").count()

    total_pnl = db.query(func.sum(Outcome.pnl_amount)).scalar() or 0
    avg_rrr_val = db.query(func.avg(Signal.rrr)).scalar() or 0

    # By pattern breakdown
    pattern_rows = (
        db.query(
            Signal.pattern,
            func.count(Outcome.id).label("total"),
            func.sum(case((Outcome.outcome == "WIN", 1), else_=0)).label("wins"),
        )
        .join(Signal, Outcome.signal_id == Signal.id)
        .group_by(Signal.pattern)
        .all()
    )
    by_pattern = [
        {
            "pattern": row.pattern or "Unknown",
            "total": row.total,
            "wins": int(row.wins),
            "win_rate": round(int(row.wins) / row.total * 100, 1) if row.total > 0 else 0,
        }
        for row in pattern_rows
    ]

    # By direction breakdown
    direction_rows = (
        db.query(
            Signal.direction,
            func.count(Outcome.id).label("total"),
            func.sum(case((Outcome.outcome == "WIN", 1), else_=0)).label("wins"),
        )
        .join(Signal, Outcome.signal_id == Signal.id)
        .group_by(Signal.direction)
        .all()
    )
    by_direction = [
        {
            "direction": row.direction,
            "total": row.total,
            "wins": int(row.wins),
            "win_rate": round(int(row.wins) / row.total * 100, 1) if row.total > 0 else 0,
        }
        for row in direction_rows
    ]

    # Monthly PnL (compute in Python for cross-DB compatibility)
    all_outcomes = (
        db.query(Outcome)
        .filter(Outcome.exit_date.isnot(None))
        .order_by(Outcome.exit_date)
        .all()
    )
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


class BacktestRequest(BaseModel):
    ticker: str
    strategy: str = "rrms"
    days: int = 180


@app.post("/api/backtest")
async def api_backtest(req: BacktestRequest):
    """Run backtest from dashboard."""
    from mcp_server.backtester import run_backtest

    result = run_backtest(req.ticker, strategy=req.strategy, days=req.days)
    return result


# ============================================================
# Order Execution Endpoints (Live Trading with Safety Controls)
# ============================================================


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


# Singleton order manager — initialized without Kite (connect later)
_order_manager = None


def _get_order_manager():
    """Get or create the singleton OrderManager."""
    global _order_manager
    if _order_manager is None:
        from mcp_server.order_manager import OrderManager
        _order_manager = OrderManager(kite=None, capital=100000)
    return _order_manager


@app.post("/tools/place_order")
async def tool_place_order(req: PlaceOrderRequest):
    """Place a live order with safety controls."""
    from dataclasses import asdict as _asdict
    manager = _get_order_manager()
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


@app.post("/tools/cancel_order")
async def tool_cancel_order(req: CancelOrderRequest):
    """Cancel a pending order."""
    from dataclasses import asdict as _asdict
    manager = _get_order_manager()
    result = manager.cancel_order(req.order_id)
    return _asdict(result)


@app.post("/tools/close_position")
async def tool_close_position(req: ClosePositionRequest):
    """Close an open position at market."""
    from dataclasses import asdict as _asdict
    manager = _get_order_manager()
    result = manager.close_position(req.ticker)
    return _asdict(result)


@app.post("/tools/close_all")
async def tool_close_all():
    """EMERGENCY: Close all open positions at market."""
    from dataclasses import asdict as _asdict
    manager = _get_order_manager()
    results = manager.close_all_positions()
    return [_asdict(r) for r in results]


@app.get("/tools/order_status")
async def tool_order_status():
    """Get order manager status including kill switch state."""
    manager = _get_order_manager()
    return manager.get_status()


@app.post("/tools/update_pnl")
async def tool_update_pnl(realized_pnl: float = Query(...)):
    """Update daily realized P&L for kill switch tracking."""
    manager = _get_order_manager()
    manager.update_pnl(realized_pnl)
    return manager.get_status()


@app.post("/tools/connect_kite")
async def tool_connect_kite():
    """Connect Kite to the order manager using kite_auth."""
    manager = _get_order_manager()
    if manager.kite is not None:
        return {"kite_connected": True, "message": "Already connected"}

    try:
        from mcp_server.kite_auth import get_authenticated_kite
        kite = get_authenticated_kite()
        manager.kite = kite
        # Update capital from Kite margins
        try:
            margins = kite.margins("equity")
            if margins and "available" in margins:
                manager.capital = float(margins["available"].get("live_balance", 100000))
        except Exception:
            pass  # Keep default capital
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


# ============================================================
# Signal Tracking Endpoints (Telegram + Google Sheets)
# ============================================================


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


@app.post("/tools/record_signal")
async def tool_record_signal(req: RecordSignalRequest):
    """Record a trading signal to Google Sheets for accuracy tracking."""
    from mcp_server.telegram_receiver import record_signal_to_sheets
    result = record_signal_to_sheets(req.model_dump())

    # Also log to sheets_sync tab format
    import asyncio
    asyncio.ensure_future(_auto_sync_sheets(signal_data={
        "signal_date": str(date.today()),
        "ticker": req.ticker,
        "direction": req.direction,
        "entry_price": req.entry_price,
        "stop_loss": req.stop_loss,
        "target": req.target,
        "rrr": req.rrr,
        "ai_confidence": req.confidence,
        "status": "OPEN",
    }))

    return result


@app.post("/tools/update_signal")
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


@app.get("/tools/signal_accuracy")
async def tool_signal_accuracy():
    """Get signal accuracy statistics from Google Sheets."""
    from mcp_server.telegram_receiver import get_sheets_tracker
    tracker = get_sheets_tracker()
    return tracker.get_accuracy_stats()


@app.post("/api/telegram_webhook")
async def api_telegram_webhook(payload: dict):
    """
    Webhook for Telegram messages (alternative to polling).

    n8n can forward Telegram messages here for processing.
    """
    from mcp_server.telegram_receiver import parse_signal_message, record_signal_to_sheets

    text = payload.get("message", {}).get("text", "")
    if not text:
        text = payload.get("text", "")

    signal = parse_signal_message(text)
    if signal is None:
        return {"parsed": False, "message": "Not a valid signal"}

    from dataclasses import asdict
    result = record_signal_to_sheets(asdict(signal))
    return {"parsed": True, **result}


class ReflectTradesRequest(BaseModel):
    limit: int = 10


class ReflectSingleRequest(BaseModel):
    signal_id: str


@app.post("/tools/reflect_trades")
async def tool_reflect_trades(req: ReflectTradesRequest):
    """Batch reflection on unreflected closed trades (called by n8n EOD)."""
    from mcp_server.trade_memory import TradeMemory
    from mcp_server.trade_reflector import TradeReflector
    memory = TradeMemory(filepath=settings.TRADE_MEMORY_FILE)
    reflector = TradeReflector(memory)
    return reflector.reflect_batch(limit=req.limit)


@app.post("/tools/reflect_single")
async def tool_reflect_single(req: ReflectSingleRequest):
    """Reflect on a specific closed trade."""
    from mcp_server.trade_memory import TradeMemory
    from mcp_server.trade_reflector import TradeReflector
    memory = TradeMemory(filepath=settings.TRADE_MEMORY_FILE)
    reflector = TradeReflector(memory)
    return reflector.reflect_on_trade(req.signal_id)


@app.get("/tools/trade_memory_stats")
async def tool_trade_memory_stats():
    """Get trade memory + reflection statistics."""
    from mcp_server.trade_memory import TradeMemory
    from mcp_server.trade_reflector import TradeReflector
    memory = TradeMemory(filepath=settings.TRADE_MEMORY_FILE)
    reflector = TradeReflector(memory)
    return {
        "memory": memory.get_stats(),
        "reflection": reflector.get_reflection_stats(),
    }


class TVWebhookPayload(BaseModel):
    ticker: str
    direction: str = "LONG"
    entry: float = 0
    sl: float = 0
    target: float = 0
    rrr: float = 0
    qty: int = 0
    source: str = "tradingview"


@app.post("/api/tv_webhook")
async def api_tv_webhook(payload: TVWebhookPayload):
    """
    TradingView webhook receiver.

    Pine Script sends alerts here when RRMS conditions trigger.
    Flow: TV Alert -> Validate -> Record -> Telegram notification
    """
    # Normalize ticker format
    ticker = payload.ticker
    if ":" not in ticker:
        ticker = f"NSE:{ticker}"

    direction = "LONG" if payload.direction.upper() in ("LONG", "BUY") else "SHORT"

    # Auto-calculate RRR if not provided but entry/sl/target are
    rrr = payload.rrr
    if rrr == 0 and payload.entry > 0 and payload.sl > 0 and payload.target > 0:
        risk = abs(payload.entry - payload.sl)
        reward = abs(payload.target - payload.entry)
        rrr = round(reward / risk, 2) if risk > 0 else 0

    # Step 0: Gather live market context for validation
    mwa_direction = "UNKNOWN"
    scanner_count = 0
    fii_net = 0.0
    sector_strength = "NEUTRAL"
    delivery_pct = 0.0
    confidence_boosts = ["TV Signal (+5%)"]
    pre_confidence = 55

    try:
        # Pull latest MWA from DB
        db_session = SessionLocal()
        latest_mwa = db_session.query(MWAScore).order_by(desc(MWAScore.score_date)).first()
        if latest_mwa:
            mwa_direction = latest_mwa.direction or "UNKNOWN"
            fii_net = float(latest_mwa.fii_net or 0)
            scanner_results = latest_mwa.scanner_results or {}
            # Count how many scanners this ticker appeared in
            plain_ticker = ticker.split(":")[-1] if ":" in ticker else ticker
            scanner_count = sum(
                1 for v in scanner_results.values()
                if isinstance(v, list) and plain_ticker in v
            )
            if mwa_direction in ("BULL", "MILD_BULL") and direction == "LONG":
                confidence_boosts.append(f"MWA {mwa_direction} (+10%)")
                pre_confidence += 10
            elif mwa_direction in ("BEAR", "MILD_BEAR") and direction == "SHORT":
                confidence_boosts.append(f"MWA {mwa_direction} (+10%)")
                pre_confidence += 10
            if scanner_count >= 3:
                confidence_boosts.append(f"Scanner hits: {scanner_count} (+5%)")
                pre_confidence += 5
        db_session.close()
    except Exception as e:
        logger.debug("TV webhook context fetch skipped: %s", e)

    # Step 0.5: BM25 memory lookup (0 API calls)
    similar_trades = []
    try:
        from mcp_server.trade_memory import TradeMemory
        _tv_memory = TradeMemory(filepath=settings.TRADE_MEMORY_FILE)
        similar_trades = _tv_memory.find_similar_for_signal(
            ticker=ticker, direction=direction, pattern="RRMS",
            rrr=rrr, confidence=pre_confidence,
            exchange=ticker.split(":")[0] if ":" in ticker else "NSE",
            top_k=settings.MEMORY_TOP_K,
        )
    except Exception as e:
        logger.debug("Trade memory lookup skipped: %s", e)

    # Step 1: Validate signal via debate validator (auto-triages debate vs single-pass)
    validation = {}
    try:
        from mcp_server.debate_validator import run_debate
        debate_result = run_debate(
            ticker=ticker,
            direction=direction,
            pattern="RRMS",
            rrr=rrr,
            entry_price=payload.entry,
            stop_loss=payload.sl,
            target=payload.target,
            mwa_direction=mwa_direction,
            scanner_count=scanner_count,
            tv_confirmed=True,
            sector_strength=sector_strength,
            fii_net=fii_net,
            delivery_pct=delivery_pct,
            confidence_boosts=confidence_boosts,
            pre_confidence=pre_confidence,
            similar_trades=similar_trades,
        )
        validation = {
            "confidence": debate_result.final_confidence,
            "recommendation": debate_result.recommendation,
            "reasoning": debate_result.reasoning,
            "validation_status": debate_result.validation_status,
            "method": debate_result.method,
            "api_calls_used": debate_result.api_calls_used,
            "risk_assessment": debate_result.risk_assessment,
            "boosts": debate_result.boosts,
        }
    except Exception as e:
        logger.error("TV webhook validation failed: %s", e)
        validation = {"recommendation": "SKIP", "confidence": 0, "reasoning": str(e)}

    confidence = validation.get("confidence", 0)
    recommendation = validation.get("recommendation", "SKIP")

    # Step 2: Record signal
    signal_data = {
        "ticker": ticker,
        "direction": "BUY" if direction == "LONG" else "SELL",
        "entry_price": payload.entry,
        "stop_loss": payload.sl,
        "target": payload.target,
        "rrr": rrr,
        "pattern": "RRMS (TradingView)",
        "confidence": confidence,
        "exchange": ticker.split(":")[0] if ":" in ticker else "NSE",
        "notes": f"TV Alert | {recommendation} | Qty: {payload.qty}",
    }

    from mcp_server.telegram_receiver import record_signal_to_sheets
    record_result = record_signal_to_sheets(signal_data)

    # Step 2.5: Store in trade memory for future BM25 lookups
    try:
        from mcp_server.trade_memory import TradeMemory, TradeRecord
        _tv_memory_store = TradeMemory(filepath=settings.TRADE_MEMORY_FILE)
        _tv_memory_store.add_record(TradeRecord(
            signal_id=record_result.get("signal_id", f"tv_{ticker}_{date.today().isoformat()}"),
            ticker=ticker,
            direction="BUY" if direction == "LONG" else "SELL",
            pattern="RRMS (TradingView)",
            entry_price=payload.entry,
            stop_loss=payload.sl,
            target=payload.target,
            rrr=rrr,
            confidence=confidence,
            recommendation=recommendation,
            exchange=ticker.split(":")[0] if ":" in ticker else "NSE",
        ))
    except Exception as e:
        logger.debug("Trade memory store skipped: %s", e)

    # Step 3: Send Telegram notification
    try:
        from mcp_server.telegram_bot import send_telegram_message
        emoji = "\U0001f7e2" if recommendation == "ALERT" else "\U0001f7e1" if recommendation == "WATCHLIST" else "\U0001f534"
        msg = (
            f"{emoji} TradingView Signal\n"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            f"Ticker: {ticker}\n"
            f"Direction: {direction}\n"
            f"Entry: {payload.entry} | SL: {payload.sl} | TGT: {payload.target}\n"
            f"RRR: {rrr} | Qty: {payload.qty}\n"
            f"AI Confidence: {confidence}% ({recommendation})\n"
            f"Signal ID: {record_result.get('signal_id', 'N/A')}"
        )
        await send_telegram_message(msg)
    except Exception as e:
        logger.debug("Telegram notification skipped: %s", e)

    return {
        "status": "ok",
        "source": "tradingview",
        "ticker": ticker,
        "direction": direction,
        "ai_confidence": confidence,
        "recommendation": recommendation,
        "signal_id": record_result.get("signal_id", ""),
        "recorded": record_result.get("recorded", False),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.MCP_SERVER_HOST, port=settings.MCP_SERVER_PORT)
