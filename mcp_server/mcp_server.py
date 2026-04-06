import asyncio
import logging
import pandas as pd
import requests
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, desc, case, text

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from mcp_server.config import settings
from mcp_server.db import get_db, init_db, SessionLocal
from mcp_server.models import Watchlist, Signal, Outcome, MWAScore, ActiveTrade
from mcp_server.asset_registry import (
    parse_ticker, get_asset_class, get_exchange,
    get_supported_exchanges,
)

logger = logging.getLogger(__name__)

# ── Health tracking globals ──────────────────────────────────
_server_start_time: datetime | None = None
_last_mwa_scan_time: datetime | None = None
_bot_app = None  # Telegram bot Application instance
_realtime_engine = None  # RealtimeEngine instance (WebSocket live feed)


def _now_ist() -> datetime:
    """Current datetime in IST regardless of server timezone."""
    from mcp_server.market_calendar import now_ist
    return now_ist()


async def _auto_scan_loop():
    """Background task: run MWA scan every 15 minutes during market hours."""
    from mcp_server.market_calendar import is_market_open

    while True:
        try:
            open_segments: list[str] = []
            if is_market_open("NSE"):
                open_segments.extend(["NSE", "NFO"])
            if is_market_open("MCX"):
                open_segments.append("MCX")
            if is_market_open("CDS"):
                open_segments.append("CDS")

            if open_segments:
                logger.info("Auto-scan: open segments=%s", open_segments)
                db = SessionLocal()
                try:
                    _execute_mwa_scan(db, segments=open_segments)
                    logger.info("Auto-scan: MWA scan completed")
                finally:
                    db.close()
            await asyncio.sleep(900)  # 15 minutes
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Auto-scan loop error: %s", e)
            await asyncio.sleep(900)


async def _price_refresh_loop():
    """Background task: refresh active trade prices every 60s during market hours."""
    from mcp_server.market_calendar import is_market_open
    from mcp_server.db import SessionLocal
    while True:
        try:
            if is_market_open("NSE"):
                db = SessionLocal()
                try:
                    trades = db.query(ActiveTrade).options(
                        joinedload(ActiveTrade.signal),
                    ).all()
                    count = 0
                    for t in trades:
                        try:
                            # Try WebSocket cache first (sub-ms)
                            ltp = None
                            if _realtime_engine:
                                ticker_clean = t.ticker.replace("NSE:", "") if t.ticker else ""
                                if ticker_clean:
                                    ltp = _realtime_engine.get_ltp(ticker_clean)
                            # Fallback to REST API
                            if not ltp or ltp <= 0:
                                ltp = _get_live_ltp(t.ticker)
                            if ltp and ltp > 0:
                                t.current_price = ltp
                                t.last_updated = _now_ist()
                                direction = (
                                    t.signal.direction if t.signal else "LONG"
                                )
                                is_short = direction in ("SELL", "SHORT")
                                sl = float(t.stop_loss)
                                tgt = float(t.target)
                                risk = (sl - ltp) if is_short else (ltp - sl)
                                reward = (ltp - tgt) if is_short else (tgt - ltp)
                                t.crrr = round(reward / risk, 2) if risk > 0 else 0
                                count += 1
                        except Exception as e:
                            logger.debug("Price tick error %s: %s", t.ticker, e)
                    if count:
                        db.commit()
                        logger.info("Price refresh: %d/%d updated", count, len(trades))
                finally:
                    db.close()
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Price refresh loop error: %s", e)
            await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _server_start_time, _bot_app

    # Startup — configure structured logging
    from mcp_server.logging_config import setup_logging
    setup_logging()

    _server_start_time = _now_ist()

    # Capture the main event loop for background thread access
    global _main_event_loop
    _main_event_loop = asyncio.get_running_loop()

    try:
        logger.info("Initializing database...")
        init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.warning("Database init skipped (not available): %s", e)

    # Start signal auto-monitor background task
    monitor_task = None
    try:
        from mcp_server.signal_monitor import signal_monitor_loop
        monitor_task = asyncio.create_task(signal_monitor_loop())
        logger.info("Signal auto-monitor background task started")
    except Exception as e:
        logger.warning("Signal monitor startup skipped: %s", e)

    # Start live price refresh background task (every 60s during market hours)
    price_task = asyncio.create_task(_price_refresh_loop())
    logger.info("Live price refresh background task started")

    # Start auto-scan background task (every 15 min during market hours)
    auto_scan_task = asyncio.create_task(_auto_scan_loop())
    logger.info("Auto-scan background task started (every 15 min during market hours)")

    # Start Telegram bot polling (so /health, /kitelogin commands work)
    try:
        from mcp_server.telegram_bot import create_bot_application
        _bot_app = create_bot_application()
        if _bot_app:
            await _bot_app.initialize()
            await _bot_app.start()
            await _bot_app.updater.start_polling(drop_pending_updates=True)
            logger.info("Telegram bot polling started")
    except Exception as e:
        logger.warning("Telegram bot polling startup skipped: %s", e)

    # Start RealtimeEngine (WebSocket live market data)
    global _realtime_engine
    try:
        from mcp_server.realtime_engine import RealtimeEngine
        _realtime_engine = RealtimeEngine()
        _realtime_engine.start_async()
        logger.info("RealtimeEngine started (WebSocket live feed)")
    except Exception as e:
        logger.warning("RealtimeEngine startup skipped: %s", e)
        _realtime_engine = None

    logger.info("MCP Server starting on %s:%s", settings.MCP_SERVER_HOST, settings.MCP_SERVER_PORT)
    yield
    # Shutdown — stop RealtimeEngine
    if _realtime_engine:
        try:
            _realtime_engine.stop()
        except Exception as e:
            logger.warning("RealtimeEngine shutdown error: %s", e)

    # Shutdown — stop Telegram bot
    if _bot_app:
        try:
            await _bot_app.updater.stop()
            await _bot_app.stop()
            await _bot_app.shutdown()
            logger.info("Telegram bot stopped")
        except Exception as e:
            logger.warning("Telegram bot shutdown error: %s", e)

    # Shutdown — cancel monitor task
    if monitor_task and not monitor_task.done():
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass

    # Shutdown — cancel price refresh task
    if price_task and not price_task.done():
        price_task.cancel()
        try:
            await price_task
        except asyncio.CancelledError:
            pass

    # Shutdown — cancel auto-scan task
    if auto_scan_task and not auto_scan_task.done():
        auto_scan_task.cancel()
        try:
            await auto_scan_task
        except asyncio.CancelledError:
            pass
    logger.info("MCP Server shutting down")


app = FastAPI(
    title="MKUMARAN Trading OS - MCP Server",
    description="Hybrid Trading Intelligence MCP Server",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Auth Middleware (opt-in via AUTH_ENABLED=true) ──────────

# Paths that never require auth
AUTH_PUBLIC_PATHS = {
    "/auth/login", "/api/auth/login", "/api/info", "/health", "/docs",
    "/openapi.json", "/redoc",
    "/api/tv_webhook", "/api/telegram_webhook",
    "/api/kite_callback", "/api/kite_login_url",
    "/api/gwc_callback", "/api/gwc_login_url",
    "/tools/connect_angel", "/tools/refresh_angel_token",
    # n8n workflow endpoints (read-only scan/data tools)
    "/tools/run_mwa_scan", "/tools/get_stock_data",
    "/tools/order_status", "/tools/get_fo_signal",
    "/tools/update_all_trailing_sl", "/tools/check_exit_strategies",
    # AI report + news sentiment (n8n calls without auth)
    "/tools/ai_report", "/tools/news_sentiment",
}
AUTH_PUBLIC_PREFIXES = (
    "/assets/", "/docs/", "/redoc/",
    "/tools/mwa_scan_status/", "/api/chart/",
)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if not settings.AUTH_ENABLED:
            return await call_next(request)

        path = request.url.path

        # Only enforce auth on API and tool endpoints
        # SPA routes (/, /overview, /news, etc.) are served as index.html
        # and the frontend ProtectedRoute handles UI-side auth
        is_protected = (
            path.startswith("/api/")
            or path.startswith("/tools/")
            or path.startswith("/auth/")
        )

        if not is_protected:
            return await call_next(request)

        # Allow public API paths (webhooks, health, docs, login)
        if path in AUTH_PUBLIC_PATHS or path.startswith(AUTH_PUBLIC_PREFIXES):
            return await call_next(request)

        # Check Authorization header
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Not authenticated"},
            )

        token = auth_header[7:]
        from mcp_server.auth import decode_access_token
        payload = decode_access_token(token)
        if payload is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token"},
            )

        # Attach user info to request state
        request.state.user = payload
        return await call_next(request)


app.add_middleware(AuthMiddleware)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled error on %s: %s", request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": "An unexpected error occurred",
            "path": request.url.path,
        },
    )





@app.get("/api/info")
async def api_info():
    return {
        "service": "MKUMARAN Trading OS",
        "version": "1.9",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    checks = {"api": "ok"}

    # Check database
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    # Check Kite connection
    if _order_manager and _order_manager.kite:
        checks["kite"] = "connected"
    else:
        checks["kite"] = "not_connected"

    # Overall status
    db_ok = checks["database"] == "ok"
    status = "healthy" if db_ok else "degraded"

    return {
        "status": status,
        "service": "mkumaran-trading-os",
        "checks": checks,
    }


# ============================================================
# Authentication Endpoints
# ============================================================


class LoginRequest(BaseModel):
    email: str
    password: str


@app.post("/auth/login")
@app.post("/api/auth/login", include_in_schema=False)
@limiter.limit("5/minute")
async def auth_login(request: Request, req: LoginRequest):
    """Authenticate admin user and return JWT token."""
    from mcp_server.auth import authenticate_admin, create_access_token

    user = authenticate_admin(req.email, req.password)
    if user is None:
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid email or password"},
        )

    token = create_access_token({"sub": user["email"], "role": user["role"]})
    return {
        "access_token": token,
        "token_type": "bearer",
        "email": user["email"],
    }


@app.get("/auth/me")
@app.get("/api/auth/me", include_in_schema=False)
async def auth_me(request: Request):
    """Get current authenticated user info."""
    if not settings.AUTH_ENABLED:
        return {"email": "dev@local", "role": "admin", "auth_enabled": False}

    user = getattr(request.state, "user", None)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})

    return {"email": user.get("sub", ""), "role": user.get("role", ""), "auth_enabled": True}


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


@app.get("/api/chart/{ticker:path}")
async def api_chart_ohlcv(
    ticker: str,
    interval: str = Query("1D", regex="^(1m|5m|15m|1h|1H|1D|1d)$"),
    days: int = Query(30, ge=1, le=365),
):
    """Return chart-ready OHLCV bars for lightweight-charts frontend."""
    from mcp_server.data_provider import get_stock_data

    # Map frontend intervals to data_provider intervals
    _interval_map = {
        "1m": "1m", "5m": "5m", "15m": "15m",
        "1h": "1h", "1H": "1h", "1D": "1d", "1d": "1d",
    }
    data_interval = _interval_map.get(interval, "1d")

    # Map days to period string
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

    df = get_stock_data(ticker, period=period, interval=data_interval)
    if df is None or df.empty:
        return {"status": "error", "bars": [], "message": f"No data for {ticker}"}

    bars = []
    for idx, row in df.iterrows():
        # idx may be a DatetimeIndex or a column
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


# ── Background MWA scan jobs ─────────────────────────────────
_mwa_jobs: dict[str, dict] = {}  # job_id -> {status, result, started, finished}


_main_event_loop: asyncio.AbstractEventLoop | None = None


def _fire_and_forget(coro) -> None:
    """Schedule an async coroutine from any thread (main or background).

    Uses asyncio.ensure_future when called from the main async thread,
    falls back to run_coroutine_threadsafe for background threads.
    """
    try:
        loop = asyncio.get_running_loop()
        asyncio.ensure_future(coro, loop=loop)
    except RuntimeError:
        # No running loop in this thread — use the cached main loop
        if _main_event_loop is not None and _main_event_loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, _main_event_loop)
        else:
            logger.warning("No event loop available — skipping async task")


def _run_mwa_scan_background(job_id: str) -> None:
    """Run the full MWA scan in a background thread, store result in _mwa_jobs."""
    import traceback
    from mcp_server.db import SessionLocal
    try:
        _mwa_jobs[job_id]["status"] = "running"
        result = _execute_mwa_scan(SessionLocal())
        _mwa_jobs[job_id]["result"] = result
        _mwa_jobs[job_id]["status"] = "completed"
    except Exception as e:
        _mwa_jobs[job_id]["status"] = "failed"
        _mwa_jobs[job_id]["result"] = {"error": str(e), "traceback": traceback.format_exc()}
    _mwa_jobs[job_id]["finished"] = _now_ist().isoformat()


@app.get("/tools/mwa_scan_status/{job_id}")
async def tool_mwa_scan_status(job_id: str):
    """Poll for MWA scan job status."""
    job = _mwa_jobs.get(job_id)
    if not job:
        return {"error": "Job not found", "job_id": job_id}
    resp = {"job_id": job_id, "status": job["status"], "started": job["started"]}
    if job["status"] in ("completed", "failed"):
        resp["finished"] = job.get("finished")
        resp["result"] = job.get("result")
    return resp


@app.post("/tools/run_mwa_scan")
@limiter.limit("30/minute")
async def tool_run_mwa_scan(request: Request, db: Session = Depends(get_db)):
    """Run the full 98-scanner MWA scan and persist score to DB."""
    import threading

    # ── Holiday / weekend gate ────────────────────────────────
    from mcp_server.market_calendar import is_market_holiday, is_weekend

    today = date.today()
    if is_weekend(today):
        return {"status": "skipped", "tool": "run_mwa_scan",
                "reason": f"Weekend ({today.strftime('%A')}). Scan not needed."}
    if is_market_holiday("NSE", today):
        return {"status": "skipped", "tool": "run_mwa_scan",
                "reason": f"Market holiday ({today}). Scan not needed."}

    # ── Async mode: return job_id immediately, run in background ──
    mode = request.query_params.get("mode", "async")
    if mode == "async":
        import uuid
        job_id = uuid.uuid4().hex[:12]
        _mwa_jobs[job_id] = {
            "status": "queued", "result": None,
            "started": _now_ist().isoformat(), "finished": None,
        }
        t = threading.Thread(target=_run_mwa_scan_background, args=(job_id,), daemon=True)
        t.start()
        return {
            "status": "accepted", "tool": "run_mwa_scan",
            "job_id": job_id,
            "poll_url": f"/tools/mwa_scan_status/{job_id}",
            "message": "Scan started in background. Poll the status URL for results.",
        }

    # ── Sync mode (mode=sync): run inline and return result ──
    return _execute_mwa_scan(db)


def _execute_mwa_scan(db: Session, segments: list[str] | None = None) -> dict:
    """Core MWA scan logic — used by both sync and async modes.

    Routes data by segment to the best source (Angel for NSE/NFO, Goodwill
    for MCX, yfinance for CDS) and runs scanners per-segment so that
    Chartink (NSE-only) doesn't run against MCX/CDS, while universal
    scanners (SMC/Wyckoff/VSA/Harmonic/RL) now run on all segments.

    Args:
        segments: List of open segments to scan (e.g. ["MCX", "CDS"]).
                  None = scan all segments (backward compat for manual API).
    """
    from mcp_server.mwa_scanner import MWAScanner
    from mcp_server.mwa_scoring import calculate_mwa_score, get_promoted_stocks, format_morning_brief
    from mcp_server.asset_registry import CDS_UNIVERSE, MCX_UNIVERSE, NFO_INDEX_UNIVERSE
    from mcp_server.data_provider import get_provider

    provider = get_provider()

    # ── Fetch OHLCV per segment using routed sources ─────────
    nse_data: dict = {}
    mcx_data: dict = {}
    cds_data: dict = {}
    nfo_data: dict = {}
    data_diag: dict = {"nse": 0, "cds": 0, "mcx": 0, "nfo": 0, "errors": []}

    try:
        from mcp_server.nse_scanner import _get_nse_universe

        # 1) NSE equity — routed via Angel → NSE India → yfinance
        if segments is None or "NSE" in segments:
            nse_stocks = _get_nse_universe()
            for ticker in nse_stocks:
                try:
                    symbol_clean = ticker.replace("NSE:", "")
                    df = provider.get_ohlcv_routed(symbol_clean, interval="day", days=180, exchange="NSE")
                    if df is not None and not df.empty:
                        # Normalize: ensure index-based format for scanners
                        if "date" in df.columns:
                            df = df.set_index("date")
                        nse_data[ticker] = df
                        data_diag["nse"] += 1
                except Exception as e:
                    logger.debug("NSE fetch failed for %s: %s", ticker, e)

        # 2) CDS — routed via yfinance → Angel
        if segments is None or "CDS" in segments:
            for ticker in CDS_UNIVERSE:
                try:
                    df = provider.get_ohlcv_routed(ticker, interval="day", days=180, exchange="CDS")
                    if df is not None and not df.empty:
                        if "date" in df.columns:
                            df = df.set_index("date")
                        cds_data[ticker] = df
                        data_diag["cds"] += 1
                except Exception as e:
                    data_diag["errors"].append(f"CDS:{ticker}: {e}")
                    logger.warning("CDS fetch failed for %s: %s", ticker, e)

        # 3) MCX — routed via Goodwill → Angel → yfinance
        if segments is None or "MCX" in segments:
            for ticker in MCX_UNIVERSE[:6]:
                try:
                    df = provider.get_ohlcv_routed(ticker, interval="day", days=180, exchange="MCX")
                    if df is not None and not df.empty:
                        if "date" in df.columns:
                            df = df.set_index("date")
                        mcx_data[ticker] = df
                        data_diag["mcx"] += 1
                except Exception as e:
                    data_diag["errors"].append(f"MCX:{ticker}: {e}")
                    logger.warning("MCX fetch failed for %s: %s", ticker, e)

        # 4) NFO — routed via Angel → Kite
        if segments is None or "NFO" in segments:
            for ticker in NFO_INDEX_UNIVERSE:
                try:
                    df = provider.get_ohlcv_routed(ticker, interval="day", days=180, exchange="NFO")
                    if df is not None and not df.empty:
                        if "date" in df.columns:
                            df = df.set_index("date")
                        nfo_data[ticker] = df
                        data_diag["nfo"] += 1
                except Exception as e:
                    data_diag["errors"].append(f"NFO:{ticker}: {e}")
                    logger.warning("NFO fetch failed for %s: %s", ticker, e)

        logger.info("Data fetched (routed): NSE=%d, CDS=%d, MCX=%d, NFO=%d (segments=%s)",
                     data_diag["nse"], data_diag["cds"], data_diag["mcx"],
                     data_diag["nfo"], segments or "ALL")
    except Exception as e:
        logger.error("Data fetch failed: %s", e)
        data_diag["errors"].append(str(e))

    # ── Run scanners per segment (skip closed segments) ─────
    scanner = MWAScanner()

    nse_results = scanner.run_all(stock_data=nse_data or None, save=False, segment="NSE") if (segments is None or "NSE" in segments) else {}
    mcx_results = scanner.run_all(stock_data=mcx_data or None, save=False, segment="MCX") if (segments is None or "MCX" in segments) and mcx_data else {}
    cds_results = scanner.run_all(stock_data=cds_data or None, save=False, segment="CDS") if (segments is None or "CDS" in segments) and cds_data else {}
    nfo_results = scanner.run_all(stock_data=nfo_data or None, save=False, segment="NFO") if (segments is None or "NFO" in segments) and nfo_data else {}

    # Merge results — for scanners that ran on multiple segments,
    # combine stock lists (deduplicated)
    raw_results: dict[str, list[str]] = {}
    for seg_results in [nse_results, mcx_results, cds_results, nfo_results]:
        for key, stocks in seg_results.items():
            if key in raw_results:
                existing = set(raw_results[key])
                raw_results[key].extend(s for s in stocks if s not in existing)
            else:
                raw_results[key] = list(stocks)

    # Combined stock_data for downstream signal generation / SMC analysis
    stock_data: dict = {**nse_data, **mcx_data, **cds_data, **nfo_data}

    score = calculate_mwa_score(raw_results, segments_run=segments)
    promoted = get_promoted_stocks(raw_results)
    brief = format_morning_brief(score)

    # Log CDS/MCX scanner results for diagnostics
    for k, v in raw_results.items():
        if k.startswith(("cds_", "mcx_")):
            stocks = v if isinstance(v, list) else []
            if stocks:
                logger.info("Scanner %s fired: %s", k, stocks)

    # Build structured scanner_results for the frontend
    from mcp_server.mwa_scanner import SCANNERS
    structured_results = {}
    for k, v in raw_results.items():
        stocks = v if isinstance(v, list) else []
        cfg = SCANNERS.get(k, {})
        structured_results[k] = {
            "name": k,
            "group": cfg.get("layer", "Other"),
            "weight": cfg.get("weight", 0),
            "count": len(stocks),
            "direction": cfg.get("type", "NEUTRAL"),
            "stocks": stocks[:20],  # cap to avoid bloating DB
        }

    # Persist to DB
    today = date.today()
    existing = db.query(MWAScore).filter(MWAScore.score_date == today).first()
    if existing:
        existing.direction = score["direction"]
        existing.bull_score = score["bull_score"]
        existing.bear_score = score["bear_score"]
        existing.bull_pct = score["bull_pct"]
        existing.bear_pct = score["bear_pct"]
        existing.scanner_results = structured_results
        existing.promoted_stocks = promoted
    else:
        mwa = MWAScore(
            score_date=today,
            direction=score["direction"],
            bull_score=score["bull_score"],
            bear_score=score["bear_score"],
            bull_pct=score["bull_pct"],
            bear_pct=score["bear_pct"],
            scanner_results=structured_results,
            promoted_stocks=promoted,
        )
        db.add(mwa)
    db.commit()

    # Auto-sync to Google Sheets
    _fire_and_forget(_auto_sync_sheets(mwa_data={
        "score_date": str(today),
        "direction": score["direction"],
        "bull_score": score["bull_score"],
        "bear_score": score["bear_score"],
        "bull_pct": score["bull_pct"],
        "bear_pct": score["bear_pct"],
    }))

    # Send MWA scan results to Telegram
    try:
        from mcp_server.telegram_bot import send_telegram_message

        direction_emoji = {"BULL": "\U0001f7e2", "BEAR": "\U0001f534", "SIDEWAYS": "\U0001f7e1"}
        d_emoji = direction_emoji.get(score["direction"], "\u26aa")

        # Build promoted stocks list (top 10)
        promo_lines = ""
        if promoted:
            top_promo = promoted[:10]
            promo_lines = "\n\U0001f31f Promoted Stocks:\n" + "\n".join(
                f"  {s.get('ticker', s) if isinstance(s, dict) else s}" for s in top_promo
            )
            if len(promoted) > 10:
                promo_lines += f"\n  ... +{len(promoted) - 10} more"

        # Build complete chains list
        complete_chains = [c for c in score.get("active_chains", []) if c.get("complete")]
        chain_lines = ""
        if complete_chains:
            chain_lines = "\n\u26d3 Signal Chains:\n" + "\n".join(
                f"  \u2713 {c['name']} (+{c['boost']}%)" for c in complete_chains[:8]
            )

        seg_label = ", ".join(segments) if segments else "ALL"
        if segments and len(segments) == 1:
            seg_label += " only (after-hours)"

        tg_msg = (
            f"{d_emoji} MWA Scan \u2014 {today}\n"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            f"Segments: {seg_label}\n"
            f"Direction: {score['direction']}\n"
            f"Bull: {score['bull_pct']}% | Bear: {score['bear_pct']}%\n"
            f"Fired: {len(score.get('fired_bull', []))} BULL / {len(score.get('fired_bear', []))} BEAR\n"
            f"Scanners: {len(raw_results)} active"
            f"{chain_lines}"
            f"{promo_lines}"
        )
        _fire_and_forget(send_telegram_message(tg_msg, force=True))
    except Exception as e:
        logger.debug("MWA Telegram notification skipped: %s", e)

    # ── MWA Signal Cards: detailed trade levels for top promoted stocks ──
    mwa_signal_cards = []
    try:
        from mcp_server.mwa_signal_generator import generate_mwa_signals

        mwa_signals = generate_mwa_signals(
            promoted=promoted[:10],
            stock_data=stock_data,
            mwa_direction=score["direction"],
            scanner_results=raw_results,
        )

        from mcp_server.market_calendar import is_market_open as _is_mkt_open

        for sig in mwa_signals:
            # Build pre_confidence from scanner count + MWA alignment
            pre_confidence = 50 + min(sig["scanner_count"] * 3, 15)
            if (score["direction"] in ("BULL", "MILD_BULL") and sig["direction"] == "LONG") or \
               (score["direction"] in ("BEAR", "MILD_BEAR") and sig["direction"] == "SHORT"):
                pre_confidence += 10

            confidence_boosts = [f"MWA Promoted ({sig['scanner_count']} scanners)"]

            # SMC analysis — AMD + CRT + C4 confidence boost
            smc_card_text = ""
            try:
                from mcp_server.smart_money_concepts import SMCEngine, smc_confidence_boost
                smc_engine = SMCEngine()
                sig_df = stock_data.get(sig["ticker"])
                if sig_df is not None and len(sig_df) >= 15:
                    smc_result = smc_engine.analyse(sig_df, symbol=sig["ticker"], timeframe="day")
                    rrms_dir = "BULL" if sig["direction"] == "LONG" else "BEAR"
                    smc_boost = smc_confidence_boost(smc_result, rrms_dir)
                    if smc_boost != 0:
                        pre_confidence += smc_boost
                        confidence_boosts.append(f"SMC {smc_result['smc_direction']} ({smc_boost:+d}%)")
                        logger.info("SMC boost for %s: %+d%% (direction=%s)", sig["ticker"], smc_boost, smc_result["smc_direction"])
                    smc_card_text = smc_result.get("telegram_summary", "")
            except Exception as smc_err:
                logger.debug("SMC analysis skipped for %s: %s", sig["ticker"], smc_err)

            # AI validation (same as TV signals)
            try:
                from mcp_server.debate_validator import run_debate
                result = run_debate(
                    ticker=sig["ticker"], direction=sig["direction"],
                    pattern="MWA Scan", rrr=sig["rrr"],
                    entry_price=sig["entry"], stop_loss=sig["sl"], target=sig["target"],
                    mwa_direction=score["direction"], scanner_count=sig["scanner_count"],
                    tv_confirmed=False, sector_strength="NEUTRAL",
                    fii_net=0, delivery_pct=0,
                    confidence_boosts=confidence_boosts, pre_confidence=pre_confidence,
                )
                debate_confidence = result.final_confidence
                recommendation = result.recommendation
                # Use the higher of debate vs pre_confidence as floor
                # MWA-promoted stocks already passed multi-scanner validation
                confidence = max(debate_confidence, pre_confidence)
                if confidence != debate_confidence:
                    logger.info(
                        "MWA signal %s: debate=%d < pre=%d, using pre_confidence",
                        sig["ticker"], debate_confidence, pre_confidence,
                    )
                    recommendation = "WATCHLIST" if confidence > 60 else "SKIP"
            except Exception as debate_err:
                logger.warning("Debate failed for %s, using pre_confidence: %s", sig["ticker"], debate_err)
                confidence = pre_confidence
                recommendation = "WATCHLIST" if confidence > 50 else "SKIP"

            if confidence <= 50:
                logger.info("MWA signal %s skipped: confidence %d <= 50", sig["ticker"], confidence)
                continue

            # Check for duplicate: skip if OPEN signal exists for same ticker+direction
            existing = db.query(Signal).filter(
                Signal.ticker == sig["ticker"],
                Signal.direction == sig["direction"],
                Signal.status == "OPEN",
            ).first()
            if existing:
                logger.info(
                    "MWA signal %s %s skipped: duplicate (existing id=%d)",
                    sig["ticker"], sig["direction"], existing.id,
                )
                continue

            # Record signal to DB + Sheets
            signal_data = {
                "ticker": sig["ticker"],
                "direction": sig["direction"],
                "entry_price": sig["entry"], "stop_loss": sig["sl"], "target": sig["target"],
                "rrr": sig["rrr"], "qty": sig["qty"],
                "pattern": "MWA Scan", "confidence": confidence,
                "exchange": sig["exchange"], "asset_class": sig["asset_class"],
                "timeframe": "day",
                "notes": f"MWA Promoted | {sig['scanner_count']} scanners | {recommendation}",
            }
            try:
                from mcp_server.telegram_receiver import record_signal_to_sheets
                record_result = record_signal_to_sheets(signal_data)
            except Exception as rec_err:
                logger.warning("Signal recording failed for %s: %s", sig["ticker"], rec_err)
                record_result = {"signal_id": "N/A"}

            # Save to DB Signal + ActiveTrade for auto-monitor tracking
            try:
                db_signal = Signal(
                    signal_date=date.today(),
                    signal_time=_now_ist().time(),
                    ticker=sig["ticker"],
                    exchange=sig["exchange"],
                    asset_class=sig["asset_class"],
                    direction=sig["direction"],
                    pattern="MWA Scan",
                    entry_price=sig["entry"],
                    stop_loss=sig["sl"],
                    target=sig["target"],
                    rrr=sig["rrr"],
                    qty=sig["qty"],
                    risk_amt=round((sig["entry"] - sig["sl"]) * sig["qty"], 2) if sig["direction"] == "LONG"
                        else round((sig["sl"] - sig["entry"]) * sig["qty"], 2),
                    ai_confidence=confidence,
                    tv_confirmed=False,
                    mwa_score=score["direction"],
                    scanner_count=sig["scanner_count"],
                    source="mwa_scan",
                    timeframe="1D",
                    status="OPEN",
                )
                db.add(db_signal)
                db.flush()  # Get db_signal.id

                # Fetch live CMP to validate entry (only during market hours)
                sig_exchange = sig.get("exchange", "NSE")
                market_open = _is_mkt_open(sig_exchange)
                live_price = _get_live_ltp(sig["ticker"]) if market_open else None
                if not live_price or live_price <= 0:
                    live_price = sig["entry"]  # fallback

                # Only create ActiveTrade if CMP is within 2% of entry
                entry_price = sig["entry"]
                deviation_pct = abs(live_price - entry_price) / entry_price * 100 if entry_price else 0

                if deviation_pct <= 2.0:
                    db_active = ActiveTrade(
                        signal_id=db_signal.id,
                        ticker=sig["ticker"],
                        exchange=sig["exchange"],
                        asset_class=sig["asset_class"],
                        entry_price=sig["entry"],
                        target=sig["target"],
                        stop_loss=sig["sl"],
                        prrr=sig["rrr"],
                        current_price=live_price,
                        crrr=sig["rrr"],
                        last_updated=_now_ist(),
                        timeframe="1D",
                    )
                    db.add(db_active)
                    logger.info(
                        "ActiveTrade created: %s CMP=%.2f Entry=%.2f (%.1f%% off)",
                        sig["ticker"], live_price, entry_price, deviation_pct,
                    )
                else:
                    logger.info(
                        "ActiveTrade skipped for %s: CMP=%.2f is %.1f%% away from Entry=%.2f",
                        sig["ticker"], live_price, deviation_pct, entry_price,
                    )

                db.commit()
                logger.info("Saved MWA signal to DB: %s (id=%d)", sig["ticker"], db_signal.id)
            except Exception as db_err:
                logger.warning("DB save failed for %s: %s", sig["ticker"], db_err)
                try:
                    db.rollback()
                except Exception:
                    pass

            # Send detailed Telegram card
            emoji_map = {"ALERT": "\U0001f7e2", "WATCHLIST": "\U0001f7e1"}
            emoji = emoji_map.get(recommendation, "\U0001f7e1")
            segment_map = {"NSE": "NSE Equity", "MCX": "Commodity", "CDS": "Forex"}
            segment = segment_map.get(sig["exchange"], sig["exchange"])

            msg = (
                f"{emoji} MWA Signal\n"
                f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
                f"Ticker: {sig['ticker']}\n"
                f"Segment: {segment} | {sig['asset_class']}\n"
                f"Timeframe: Daily (Swing)\n"
                f"Direction: {sig['direction']}\n"
                f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
                f"Entry: \u20b9{sig['entry']:.1f} | SL: \u20b9{sig['sl']:.1f} | TGT: \u20b9{sig['target']:.1f}\n"
                f"RRR: {sig['rrr']:.1f} | Qty: {sig['qty']}\n"
                f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
                f"Scanners: {sig['scanner_count']} fired\n"
                f"AI Confidence: {confidence}% ({recommendation})\n"
                f"Signal ID: {record_result.get('signal_id', 'N/A')}"
            )
            if smc_card_text:
                msg += "\n" + smc_card_text
            _fire_and_forget(send_telegram_message(msg, exchange=sig["exchange"], force=True))
            mwa_signal_cards.append({
                "ticker": sig["ticker"], "direction": sig["direction"],
                "entry": sig["entry"], "sl": sig["sl"], "target": sig["target"],
                "rrr": sig["rrr"], "qty": sig["qty"],
                "confidence": confidence, "recommendation": recommendation,
                "signal_id": record_result.get("signal_id", "N/A"),
            })
            logger.info("MWA signal card sent: %s %s conf=%d", sig["ticker"], sig["direction"], confidence)

    except Exception as e:
        logger.error("MWA signal generation failed: %s", e)

    global _last_mwa_scan_time
    _last_mwa_scan_time = _now_ist()

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
        "data_fetched": data_diag,
        "mwa_signal_cards": mwa_signal_cards,
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
async def api_overview(
    exchange: str = "",
    asset_class: str = "",
    db: Session = Depends(get_db),
):
    """Dashboard overview data. Optional filter by exchange/asset_class."""
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

    # Latest MWA
    latest_mwa = db.query(MWAScore).order_by(desc(MWAScore.score_date)).first()

    # Win rate (filtered by exchange/asset_class via Signal join)
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

    # Market status
    from mcp_server.market_calendar import get_market_status
    ms = get_market_status("NSE")
    reason = ms.get("reason", "CLOSED")
    status_map = {"OPEN": "LIVE", "PRE_MARKET": "PRE", "POST_MARKET": "POST"}
    market_status = status_map.get(reason, "CLOSED")

    # Live index prices (cached for 60s via yfinance)
    nifty_price, nifty_change, nifty_change_pct = 0.0, 0.0, 0.0
    banknifty_price, banknifty_change, banknifty_change_pct = 0.0, 0.0, 0.0
    try:
        import yfinance as yf

        for sym, setter in [
            ("^NSEI", "nifty"),
            ("^NSEBANK", "banknifty"),
        ]:
            tk = yf.Ticker(sym)
            info = tk.fast_info
            price = float(getattr(info, "last_price", 0) or 0)
            prev = float(getattr(info, "previous_close", 0) or 0)
            change = round(price - prev, 2) if prev else 0.0
            change_pct = round((change / prev) * 100, 2) if prev else 0.0
            if setter == "nifty":
                nifty_price, nifty_change, nifty_change_pct = price, change, change_pct
            else:
                banknifty_price, banknifty_change, banknifty_change_pct = price, change, change_pct
    except Exception as e:
        logger.debug("Index price fetch failed: %s", e)

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


@app.get("/api/signals")
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


@app.post("/api/signals/cleanup-duplicates")
async def api_cleanup_duplicate_signals(db: Session = Depends(get_db)):
    """Remove duplicate OPEN signals keeping the oldest per ticker+direction."""
    from sqlalchemy import func

    # Find ticker+direction combos with more than 1 OPEN signal
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
            # Also remove linked ActiveTrade
            db.query(ActiveTrade).filter(ActiveTrade.signal_id == sig.id).delete()
            removed.append({"id": sig.id, "ticker": sig.ticker, "direction": sig.direction})
            db.delete(sig)

    db.commit()
    return {"removed_count": len(removed), "removed": removed}


@app.delete("/api/signals/{signal_id}")
async def api_delete_signal(signal_id: int, db: Session = Depends(get_db)):
    """Delete a signal and its linked ActiveTrade."""
    sig = db.query(Signal).filter(Signal.id == signal_id).first()
    if not sig:
        raise HTTPException(status_code=404, detail="Signal not found")
    db.query(ActiveTrade).filter(ActiveTrade.signal_id == signal_id).delete()
    db.delete(sig)
    db.commit()
    return {"deleted": signal_id, "ticker": sig.ticker}


@app.get("/api/trades/active")
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


@app.get("/api/mwa/latest")
async def api_mwa_latest(db: Session = Depends(get_db)):
    """Latest MWA score for dashboard."""
    score = db.query(MWAScore).order_by(desc(MWAScore.score_date)).first()
    if not score:
        return {"status": "no_data"}

    # Normalize scanner_results: upgrade old int-count format to ScannerResult
    raw_sr = score.scanner_results or {}
    scanner_results = {}
    from mcp_server.mwa_scanner import SCANNERS
    for k, v in raw_sr.items():
        if isinstance(v, dict) and "name" in v:
            scanner_results[k] = v  # already structured
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
async def api_accuracy(
    exchange: str = "",
    asset_class: str = "",
    db: Session = Depends(get_db),
):
    """Accuracy metrics for dashboard with breakdowns. Optional filter by exchange/asset_class."""
    # Build filtered base queries
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

    # Need fresh queries for aggregates to avoid double-join
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

    # By pattern breakdown
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

    # By direction breakdown
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

    # Monthly PnL (compute in Python for cross-DB compatibility)
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


class BacktestRequest(BaseModel):
    ticker: str
    strategy: str = "rrms"
    days: int = 180


class BacktestCompareRequest(BaseModel):
    ticker: str
    days: int = 1095


@app.post("/api/backtest")
async def api_backtest(req: BacktestRequest):
    """Run backtest from dashboard."""
    from mcp_server.backtester import run_backtest

    result = run_backtest(req.ticker, strategy=req.strategy, days=req.days)
    return result


@app.post("/api/backtest/compare")
async def api_backtest_compare(req: BacktestCompareRequest):
    """Compare all 6 strategies side-by-side with equity curves."""
    from mcp_server.backtester import run_backtest_all_strategies

    result = run_backtest_all_strategies(req.ticker, days=req.days)

    # Reshape comparison into strategies array for frontend
    strategies = result.get("comparison", [])

    # Extract equity curves per strategy from detail results
    equity_curves: dict = {}
    details = result.get("details", {})
    for strat_name, detail in details.items():
        if isinstance(detail, dict) and "equity_curve" in detail:
            equity_curves[strat_name] = detail["equity_curve"]

    return {
        "ticker": result.get("ticker", req.ticker),
        "period": result.get("period", f"{req.days} days"),
        "strategies": strategies,
        "equity_curves": equity_curves,
        "best_strategy": result.get("best_strategy", "none"),
    }


# ============================================================
# Options Greeks Endpoints
# ============================================================


class GreeksRequest(BaseModel):
    spot: float
    strike: float
    expiry_days: float
    rate: float = 0.065
    volatility: float = 0.20
    option_type: str = "CE"


class OptionChainRequest(BaseModel):
    spot: float
    expiry_days: float
    strike_start: float = 0
    strike_end: float = 0
    strike_step: float = 50
    rate: float = 0.065


@app.post("/api/options/greeks")
async def api_options_greeks(req: GreeksRequest):
    """Calculate Greeks for a single option."""
    from mcp_server.options_greeks import calculate_greeks
    from dataclasses import asdict as _asdict

    result = calculate_greeks(
        spot=req.spot,
        strike=req.strike,
        expiry_days=req.expiry_days,
        rate=req.rate,
        volatility=req.volatility,
        option_type=req.option_type,
    )
    return {"status": "ok", **_asdict(result)}


@app.get("/api/options/chain")
async def api_options_chain(
    spot: float = Query(...),
    expiry_days: float = Query(default=30),
    strike_start: float = Query(default=0),
    strike_end: float = Query(default=0),
    strike_step: float = Query(default=50),
    rate: float = Query(default=0.065),
):
    """Build option chain with Greeks for all strikes."""
    from mcp_server.options_greeks import build_greeks_chain

    # Auto-calculate strike range if not provided
    if strike_start <= 0:
        strike_start = spot * 0.90
    if strike_end <= 0:
        strike_end = spot * 1.10

    # Round to nearest step
    strike_start = round(strike_start / strike_step) * strike_step
    strike_end = round(strike_end / strike_step) * strike_step

    strikes = []
    s = strike_start
    while s <= strike_end:
        strikes.append(s)
        s += strike_step

    chain = build_greeks_chain(
        spot=spot,
        strikes=strikes,
        expiry_days=expiry_days,
        rate=rate,
    )

    # Find ATM strike and max pain
    atm_strike = min(strikes, key=lambda k: abs(k - spot)) if strikes else 0

    return {
        "status": "ok",
        "spot": spot,
        "expiry_days": expiry_days,
        "atm_strike": atm_strike,
        "strikes_count": len(strikes),
        "chain": chain,
    }


# ============================================================
# Options Payoff Endpoints
# ============================================================


class PayoffLegInput(BaseModel):
    strike: float
    premium: float
    qty: int = 1
    option_type: str = "CE"
    action: str = "BUY"


class PayoffRequest(BaseModel):
    legs: list[PayoffLegInput]
    spot_min: float = 0
    spot_max: float = 0
    num_points: int = 200


@app.post("/api/options/payoff")
async def api_options_payoff(req: PayoffRequest):
    """Calculate multi-leg options payoff curve."""
    from mcp_server.options_payoff import OptionLeg, calculate_payoff
    from dataclasses import asdict as _asdict

    legs = [
        OptionLeg(
            strike=leg.strike,
            premium=leg.premium,
            qty=leg.qty,
            option_type=leg.option_type,
            action=leg.action,
        )
        for leg in req.legs
    ]

    result = calculate_payoff(
        legs, spot_min=req.spot_min, spot_max=req.spot_max,
        num_points=req.num_points,
    )

    return {
        "status": "ok",
        "points": [_asdict(p) for p in result.points],
        "breakevens": result.breakevens,
        "max_profit": result.max_profit,
        "max_loss": result.max_loss,
        "net_premium": result.net_premium,
    }


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
        _order_manager = OrderManager(
            kite=None, capital=100000, paper_mode=settings.PAPER_MODE,
        )
    return _order_manager


@app.post("/tools/place_order")
@limiter.limit("5/minute")
async def tool_place_order(request: Request, req: PlaceOrderRequest):
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
@limiter.limit("5/minute")
async def tool_close_all(request: Request):
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


@app.post("/tools/update_trailing_sl")
async def tool_update_trailing_sl(ticker: str = Query(...), current_price: float = Query(...)):
    """Update trailing SL for a position given current market price."""
    manager = _get_order_manager()
    return manager.update_trailing_sl(ticker, current_price)


def _get_live_ltp(ticker: str) -> float | None:
    """Get LTP: try WebSocket cache first (<1ms), then Kite, then multi-source provider."""
    # Fastest: WebSocket tick cache
    if _realtime_engine:
        sym = ticker.replace("NSE:", "").replace("BSE:", "")
        ws_ltp = _realtime_engine.get_ltp(sym)
        if ws_ltp and ws_ltp > 0:
            return float(ws_ltp)
    # Kite REST API
    manager = _get_order_manager()
    if manager.kite:
        try:
            exchange, symbol = ticker.split(":", 1) if ":" in ticker else ("NSE", ticker)
            ltp_data = manager.kite.ltp(f"{exchange}:{symbol}")
            ltp = list(ltp_data.values())[0]["last_price"] if ltp_data else None
            if ltp and ltp > 0:
                return float(ltp)
        except Exception:
            pass
    # Fallback: Goodwill → NSE India → Angel
    from mcp_server.data_provider import get_provider
    ltp = get_provider().get_ltp(ticker)
    return ltp if ltp and ltp > 0 else None


@app.post("/tools/update_all_trailing_sl")
async def tool_update_all_trailing_sl():
    """Update trailing SL for ALL open positions using live prices."""
    manager = _get_order_manager()

    results = []
    for pos in manager.open_positions:
        ticker = pos.get("ticker", "")
        try:
            ltp = _get_live_ltp(ticker)
            if ltp:
                result = manager.update_trailing_sl(ticker, ltp)
                result["ticker"] = ticker
                result["ltp"] = ltp
                results.append(result)
        except Exception as e:
            results.append({"ticker": ticker, "updated": False, "message": str(e)})

    return {"positions_checked": len(results), "results": results}


@app.post("/tools/refresh_trade_prices")
async def tool_refresh_trade_prices(db: Session = Depends(get_db)):
    """Fetch live prices for all active trades and update DB."""
    from datetime import datetime as _dt
    trades = db.query(ActiveTrade).options(joinedload(ActiveTrade.signal)).all()
    updated = []
    for t in trades:
        try:
            ltp = _get_live_ltp(t.ticker)
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


@app.post("/tools/tier3_monitor")
async def tool_tier3_monitor(db: Session = Depends(get_db)):
    """Run Tier 3 active trade monitoring — updates prices, checks SL/target hits."""
    from mcp_server.tier_monitor import tier3_monitor
    alerts = tier3_monitor(db)
    return {"alerts": len(alerts), "details": alerts}


@app.post("/tools/tier2_monitor")
async def tool_tier2_monitor(db: Session = Depends(get_db)):
    """Run Tier 2 watchlist monitoring — checks entry zones, S&R breaches."""
    from mcp_server.tier_monitor import tier2_monitor
    alerts = tier2_monitor(db)
    return {"alerts": len(alerts), "details": alerts}


@app.get("/tools/portfolio_exposure")
async def tool_portfolio_exposure():
    """Get current portfolio sector/asset-class exposure breakdown."""
    from mcp_server.portfolio_risk import get_portfolio_exposure
    manager = _get_order_manager()
    return get_portfolio_exposure(manager.open_positions, manager.capital)


@app.post("/tools/check_exit_strategies")
async def tool_check_exit_strategies():
    """Evaluate exit strategy for ALL open positions using live prices."""
    manager = _get_order_manager()

    results = []
    for pos in manager.open_positions:
        ticker = pos.get("ticker", "")
        try:
            ltp = _get_live_ltp(ticker)
            if ltp:
                result = manager.evaluate_exit_strategy(ticker, ltp)
                result["ticker"] = ticker
                result["ltp"] = ltp
                results.append(result)
        except Exception as e:
            results.append({"ticker": ticker, "action": "ERROR", "message": str(e)})

    return {"checked": len(results), "results": results}


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


@app.post("/tools/refresh_kite_token")
async def tool_refresh_kite_token():
    """Refresh Kite access token via TOTP login (standalone, no order manager needed)."""
    try:
        from mcp_server.kite_auth import refresh_kite_token
        access_token = refresh_kite_token()
        return {
            "success": True,
            "message": "Kite token refreshed",
            "token_prefix": access_token[:8] + "..." if access_token else None,
        }
    except Exception as e:
        logger.error("Kite token refresh failed: %s", e)
        return {
            "success": False,
            "message": f"Token refresh failed: {e}",
        }


# ============================================================
# Angel One SmartAPI Integration
# ============================================================


@app.post("/tools/connect_angel")
async def tool_connect_angel():
    """Connect Angel One to the order manager using angel_auth."""
    manager = _get_order_manager()
    if manager.broker is not None:
        return {"angel_connected": True, "message": "Already connected"}

    try:
        from mcp_server.angel_auth import get_authenticated_angel
        client = get_authenticated_angel()

        # Wrap in AngelSource so OrderManager gets .place_order / .cancel_order
        from mcp_server.data_provider import AngelSource
        angel = AngelSource()
        angel.client = client
        angel.logged_in = True

        manager.broker = angel

        # Update capital from Angel RMS margins
        try:
            rms = client.rms()
            if rms and rms.get("data"):
                net = rms["data"].get("net", rms["data"].get("availablecash", 0))
                if net:
                    manager.capital = float(net)
        except Exception:
            pass  # Keep default capital

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


@app.post("/tools/refresh_angel_token")
async def tool_refresh_angel_token():
    """Refresh Angel access token via TOTP login (standalone)."""
    try:
        from mcp_server.angel_auth import refresh_angel_token
        refresh_angel_token()
        return {
            "success": True,
            "message": "Angel token refreshed",
        }
    except Exception as e:
        logger.error("Angel token refresh failed: %s", e)
        return {
            "success": False,
            "message": f"Angel token refresh failed: {e}",
        }


@app.get("/tools/angel_status")
async def tool_angel_status():
    """Get Angel One connection status + positions/holdings count."""
    manager = _get_order_manager()
    angel = manager.broker

    if angel is None or not getattr(angel, "logged_in", False):
        return {
            "logged_in": False,
            "message": "Angel not connected — call /tools/connect_angel first",
        }

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


# ============================================================
# Kite Manual Login (browser-based OAuth flow)
# ============================================================


@app.get("/api/kite_callback")
async def api_kite_callback(request_token: str = Query(...)):
    """Browser redirect callback from Kite Connect login.

    User logs in at Kite → Kite redirects here with ?request_token=XXX
    → we generate a session, cache the token, and show a success page.
    """
    try:
        from mcp_server.kite_auth import handle_kite_callback
        access_token = handle_kite_callback(request_token)

        # Connect order manager to the fresh Kite instance
        try:
            from kiteconnect import KiteConnect
            kite = KiteConnect(api_key=settings.KITE_API_KEY)
            kite.set_access_token(access_token)
            manager = _get_order_manager()
            manager.kite = kite
            logger.info("Order manager connected to Kite via manual login")
        except Exception as e:
            logger.warning("Order manager Kite connect skipped: %s", e)

        # Reset Kite-failed-today flag so data provider retries Kite
        try:
            from mcp_server import data_provider
            data_provider._kite_failed_today = False
        except Exception:
            pass

        # Send Telegram confirmation
        try:
            from mcp_server.telegram_bot import send_telegram_message
            import asyncio
            asyncio.ensure_future(send_telegram_message(
                "\u2705 Kite Login Successful\n"
                f"Token cached at {_now_ist().strftime('%H:%M IST')}",
                force=True,
            ))
        except Exception:
            pass

        return HTMLResponse(
            "<html><body style='font-family:sans-serif;text-align:center;padding:60px'>"
            "<h1>\u2705 Kite Login Successful</h1>"
            "<p>Access token has been cached. You can close this window.</p>"
            "<p style='color:#888;font-size:14px'>Token will be valid until end of day.</p>"
            "</body></html>"
        )
    except Exception as e:
        logger.error("Kite callback failed: %s", e)
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;text-align:center;padding:60px'>"
            f"<h1>\u274c Kite Login Failed</h1><p>{e}</p>"
            "</body></html>",
            status_code=500,
        )


@app.get("/api/kite_login_url")
async def api_kite_login_url():
    """Return the Kite Connect login URL for manual browser login."""
    try:
        from mcp_server.kite_auth import get_kite_login_url
        url = get_kite_login_url()
        return {
            "login_url": url,
            "instructions": "Open this URL in your browser, complete Zerodha 2FA, "
                            "and the system will automatically capture the token.",
        }
    except Exception as e:
        return {"error": str(e)}


# ============================================================
# GWC (Goodwill) OAuth Login
# ============================================================


@app.get("/api/gwc_callback")
async def api_gwc_callback(request_token: str = Query(...)):
    """Browser redirect callback from GWC OAuth login.

    User logs in at GWC → GWC redirects here with ?request_token=XXX
    → we exchange it for an access token and activate the GWC source.
    """
    try:
        import hashlib
        api_key = settings.GWC_API_KEY
        api_secret = settings.GWC_API_SECRET
        if not api_key or not api_secret:
            raise ValueError("GWC_API_KEY or GWC_API_SECRET not configured")

        # Generate signature: SHA-256(api_key + request_token + api_secret)
        raw = api_key + request_token + api_secret
        signature = hashlib.sha256(raw.encode()).hexdigest()

        # Exchange request_token for access_token
        resp = requests.post(
            "https://api.gwcindia.in/v1/login-response",
            json={
                "api_key": api_key,
                "request_token": request_token,
                "signature": signature,
            },
            headers={"x-api-key": api_key},
            timeout=15,
        )
        data = resp.json()
        if data.get("status") != "success":
            raise ValueError(f"GWC login-response failed: {data.get('error_msg', data)}")

        access_token = data["data"]["access_token"]

        # Inject token into data provider's GoodwillSource
        from mcp_server.data_provider import get_provider
        provider = get_provider()
        provider.gwc.set_access_token(access_token)
        provider._sources["gwc"] = True

        # Send Telegram confirmation
        try:
            from mcp_server.telegram_bot import send_telegram_message
            import asyncio
            asyncio.ensure_future(send_telegram_message(
                "\u2705 GWC Login Successful\n"
                f"Token set at {_now_ist().strftime('%H:%M IST')}\n"
                "Goodwill is now the primary LTP source.",
                force=True,
            ))
        except Exception:
            pass

        return HTMLResponse(
            "<html><body style='font-family:sans-serif;text-align:center;padding:60px'>"
            "<h1>\u2705 GWC Login Successful</h1>"
            "<p>Goodwill access token has been set. You can close this window.</p>"
            "<p style='color:#888;font-size:14px'>GWC is now the primary live price source.</p>"
            "</body></html>"
        )
    except Exception as e:
        logger.error("GWC callback failed: %s", e)
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;text-align:center;padding:60px'>"
            f"<h1>\u274c GWC Login Failed</h1><p>{e}</p>"
            "</body></html>",
            status_code=500,
        )


@app.get("/api/gwc_login_url")
async def api_gwc_login_url():
    """Return the GWC OAuth login URL for manual browser login."""
    if not settings.GWC_API_KEY:
        return {"error": "GWC_API_KEY not configured"}
    return {
        "login_url": f"https://api.gwcindia.in/v1/login?api_key={settings.GWC_API_KEY}",
        "instructions": "Open this URL in your browser, complete Goodwill 2FA, "
                        "and the system will automatically capture the token.",
    }


# ============================================================
# System Health (for Telegram /health command)
# ============================================================


def get_system_health() -> dict:
    """Collect comprehensive system health data for the /health command."""
    health: dict = {}

    # Uptime
    if _server_start_time:
        delta = _now_ist() - _server_start_time
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes = remainder // 60
        health["uptime"] = f"{hours}h {minutes}m"
        health["server_ok"] = True
    else:
        health["uptime"] = "unknown"
        health["server_ok"] = False

    # Database
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        health["db_ok"] = True
    except Exception:
        health["db_ok"] = False

    # Kite
    health["kite_connected"] = bool(_order_manager and _order_manager.kite)

    # GWC (Goodwill)
    try:
        from mcp_server.data_provider import get_provider
        health["gwc_connected"] = get_provider()._sources.get("gwc", False)
    except Exception:
        health["gwc_connected"] = False

    # Kite failed today flag
    try:
        from mcp_server import data_provider
        health["kite_failed_today"] = getattr(data_provider, "_kite_failed_today", False)
    except Exception:
        health["kite_failed_today"] = False

    # Market status
    try:
        from mcp_server.market_calendar import get_market_status
        for exchange in ("NSE", "MCX", "CDS"):
            ms = get_market_status(exchange)
            health[f"market_{exchange.lower()}"] = ms.get("reason", "CLOSED")
    except Exception:
        health["market_nse"] = "UNKNOWN"

    # Signal / trade counts
    try:
        db = SessionLocal()
        health["open_signals"] = db.query(Signal).filter(Signal.status == "OPEN").count()
        health["active_trades"] = db.query(ActiveTrade).count()
        health["today_signals"] = db.query(Signal).filter(Signal.signal_date == date.today()).count()
        db.close()
    except Exception:
        health["open_signals"] = 0
        health["active_trades"] = 0
        health["today_signals"] = 0

    # Order manager status
    try:
        manager = _get_order_manager()
        status = manager.get_status()
        health["kill_switch"] = status.get("kill_switch_active", False)
        health["daily_pnl"] = status.get("daily_pnl", 0)
        health["paper_mode"] = status.get("paper_mode", False)
    except Exception:
        health["kill_switch"] = False
        health["daily_pnl"] = 0
        health["paper_mode"] = True

    # MWA latest
    try:
        db = SessionLocal()
        latest_mwa = db.query(MWAScore).order_by(desc(MWAScore.score_date)).first()
        if latest_mwa:
            health["mwa_direction"] = latest_mwa.direction
            health["mwa_bull_pct"] = float(latest_mwa.bull_pct or 0)
            health["mwa_bear_pct"] = float(latest_mwa.bear_pct or 0)
        else:
            health["mwa_direction"] = "N/A"
        db.close()
    except Exception:
        health["mwa_direction"] = "N/A"

    # Last MWA scan time
    if _last_mwa_scan_time:
        from datetime import timezone, timedelta as _td
        _ist = timezone(_td(hours=5, minutes=30))
        _scan_ist = _last_mwa_scan_time.replace(tzinfo=timezone.utc).astimezone(_ist)
        health["last_mwa_scan"] = _scan_ist.strftime("%I:%M %p IST")
    else:
        health["last_mwa_scan"] = "Not run yet"

    return health


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

    # Also log to sheets_sync tab format (with segment routing)
    import asyncio
    asyncio.ensure_future(_auto_sync_sheets(signal_data={
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


@app.post("/tools/check_signals")
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


@app.post("/tools/pretrade_check")
async def tool_pretrade_check(signal_id: int = Query(...), db: Session = Depends(get_db)):
    """Run 10 automated pre-trade checks for a signal."""
    from mcp_server.pretrade_check import run_pretrade_checks
    return run_pretrade_checks(signal_id, db)


@app.post("/tools/clear_sheets")
async def tool_clear_sheets():
    """Clear all Google Sheets data rows (keep headers) for a fresh start."""
    from mcp_server.sheets_sync import _get_sheets_client

    _, sheet = _get_sheets_client()
    if not sheet:
        return {"error": "Google Sheets not configured"}

    cleared = []
    errors = []

    # All known tabs with their headers
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
        "SIGNALS_EQUITY": None,  # same as Signals
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

    # Default segment headers (same as Signals master)
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
    timeframe: str = "1D"
    source: str = "tradingview"


@app.post("/api/tv_webhook")
@limiter.limit("60/minute")
async def api_tv_webhook(request: Request, payload: TVWebhookPayload):
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
    exchange_str = ticker.split(":")[0] if ":" in ticker else "NSE"
    asset_class_str = get_asset_class(ticker).value
    signal_data = {
        "ticker": ticker,
        "direction": direction,
        "entry_price": payload.entry,
        "stop_loss": payload.sl,
        "target": payload.target,
        "rrr": rrr,
        "pattern": "RRMS (TradingView)",
        "confidence": confidence,
        "exchange": exchange_str,
        "asset_class": asset_class_str,
        "timeframe": payload.timeframe,
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
            direction=direction,
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

    # Step 3: Send Telegram notification (only for signals with >50% confidence)
    if confidence > 50:
        try:
            from mcp_server.telegram_bot import send_telegram_message
            emoji = "\U0001f7e2" if recommendation == "ALERT" else "\U0001f7e1" if recommendation == "WATCHLIST" else "\U0001f534"
            exchange_str = ticker.split(":")[0] if ":" in ticker else "NSE"
            asset_class_str = get_asset_class(ticker).value

            # Segment label
            segment_map = {
                "NSE": "NSE Equity", "BSE": "BSE Equity",
                "MCX": "Commodity", "NFO": "F&O", "CDS": "Forex",
            }
            segment_label = segment_map.get(exchange_str, exchange_str)

            # Timeframe classification
            tf = payload.timeframe
            tf_category_map = {
                "5m": "Intraday", "15m": "Intraday", "30m": "Intraday", "1H": "Intraday",
                "4H": "Swing", "1D": "Swing", "day": "Swing",
                "1W": "Positional", "week": "Positional", "1M": "Positional",
            }
            tf_category = tf_category_map.get(tf, "Swing")

            msg = (
                f"{emoji} TradingView Signal\n"
                f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
                f"Ticker: {ticker}\n"
                f"Segment: {segment_label} | {asset_class_str}\n"
                f"Timeframe: {tf} ({tf_category})\n"
                f"Direction: {direction}\n"
                f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
                f"Entry: \u20b9{payload.entry} | SL: \u20b9{payload.sl} | TGT: \u20b9{payload.target}\n"
                f"RRR: {rrr} | Qty: {payload.qty}\n"
                f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
                f"AI Confidence: {confidence}% ({recommendation})\n"
                f"Signal ID: {record_result.get('signal_id', 'N/A')}"
            )
            await send_telegram_message(msg, exchange=exchange_str, force=True)
        except Exception as e:
            logger.debug("Telegram notification skipped: %s", e)
    else:
        logger.info("Telegram skipped for %s — confidence %d%% below 50%% threshold", ticker, confidence)

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


# ============================================================
# News / Macro Event Monitor
# ============================================================


@app.get("/api/news")
async def api_news(
    hours: int = Query(default=24, ge=1, le=168),
    min_impact: str = Query(default="LOW"),
):
    """Get latest news items classified by impact. For dashboard consumption."""
    from mcp_server.news_monitor import get_latest_news
    from dataclasses import asdict as _asdict

    items = get_latest_news(hours=hours, min_impact=min_impact.upper())
    return [_asdict(item) for item in items[:100]]


@app.get("/tools/market_news")
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


@app.post("/tools/check_news_alerts")
async def tool_check_news_alerts():
    """Trigger news check and send HIGH-impact alerts to Telegram."""
    from mcp_server.news_monitor import check_and_alert

    result = await check_and_alert()
    return {"status": "ok", "tool": "check_news_alerts", **result}


@app.post("/tools/ai_report")
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


@app.post("/tools/news_sentiment")
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


# ============================================================
# Momentum Ranking Module
# ============================================================

@app.get("/api/momentum")
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


@app.get("/tools/momentum_rankings")
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


@app.post("/tools/momentum_rebalance")
@limiter.limit("30/minute")
async def tool_momentum_rebalance(request: Request, top_n: int = Query(default=10, ge=1, le=50)):
    """
    Trigger full universe momentum scan and generate rebalance signals.
    Takes ~40-75s due to rate-limited yfinance calls.
    """
    from mcp_server.momentum_ranker import (
        rank_universe,
        generate_rebalance_signals,
        get_momentum_portfolio,
        save_momentum_portfolio,
    )
    from dataclasses import asdict as _asdict

    # Get current holdings (if any)
    prev = get_momentum_portfolio()
    current_holdings = prev.get("holdings", []) if prev else []

    # Run full scan
    rankings = rank_universe(top_n=top_n)
    signals = generate_rebalance_signals(current_holdings, rankings, top_n=top_n)

    # Persist
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


# ============================================================
# Market Movers — Top Gainers / Losers / 52W High / Most Active
# ============================================================

# In-memory cache for market movers (refreshed every 5 min during market hours)
_market_movers_cache: dict = {}
_market_movers_ts: datetime | None = None


def _fetch_market_movers() -> dict:
    """Fetch top gainers, losers, 52W highs, most-active across all segments."""
    import yfinance as yf
    from mcp_server.nse_scanner import _get_nse_universe
    from mcp_server.asset_registry import MCX_UNIVERSE, CDS_UNIVERSE, MCX_YF_PROXY

    results: dict[str, list[dict]] = {
        "gainers": [], "losers": [], "week52_high": [],
        "week52_low": [], "most_active": [],
    }

    # ── Helper: fetch batch quotes via yfinance ──────────────
    def _fetch_segment(tickers: list[str], exchange: str, yf_suffix: str = ".NS"):
        items: list[dict] = []
        batch: list[str] = []
        ticker_map: dict[str, str] = {}

        for t in tickers:
            if exchange == "MCX":
                yf_sym = MCX_YF_PROXY.get(t, "")
                if not yf_sym:
                    continue
            elif exchange == "CDS":
                yf_sym = f"{t}=X" if "INR" in t else t
            else:
                yf_sym = f"{t}{yf_suffix}"
            batch.append(yf_sym)
            ticker_map[yf_sym] = t

        if not batch:
            return items

        try:
            data = yf.download(batch, period="2d", interval="1d",
                               group_by="ticker", progress=False, threads=True)
        except Exception as e:
            logger.warning("yf.download failed for %s: %s", exchange, e)
            return items

        for yf_sym, clean_name in ticker_map.items():
            try:
                if len(batch) == 1:
                    df = data
                else:
                    df = data[yf_sym] if yf_sym in data.columns.get_level_values(0) else None
                if df is None or df.empty or len(df) < 1:
                    continue

                row = df.iloc[-1]
                prev_close = df.iloc[-2]["Close"] if len(df) >= 2 else row["Open"]
                close = float(row["Close"])
                change = close - float(prev_close)
                pct = (change / float(prev_close)) * 100 if prev_close else 0
                volume = int(row.get("Volume", 0))
                high = float(row.get("High", close))
                low = float(row.get("Low", close))
                opn = float(row.get("Open", close))

                items.append({
                    "ticker": clean_name,
                    "exchange": exchange,
                    "ltp": round(close, 2),
                    "change": round(change, 2),
                    "pct_change": round(pct, 2),
                    "open": round(opn, 2),
                    "high": round(high, 2),
                    "low": round(low, 2),
                    "prev_close": round(float(prev_close), 2),
                    "volume": volume,
                })
            except Exception:
                continue

        return items

    # ── Fetch all segments ───────────────────────────────────
    nse_stocks = _get_nse_universe()
    nse_items = _fetch_segment(nse_stocks, "NSE")
    mcx_items = _fetch_segment(MCX_UNIVERSE[:6], "MCX")
    cds_items = _fetch_segment(CDS_UNIVERSE, "CDS")

    all_items = nse_items + mcx_items + cds_items

    # ── Sort into categories ─────────────────────────────────
    by_pct = sorted(all_items, key=lambda x: x["pct_change"], reverse=True)
    results["gainers"] = [i for i in by_pct if i["pct_change"] > 0][:30]
    results["losers"] = sorted(
        [i for i in all_items if i["pct_change"] < 0],
        key=lambda x: x["pct_change"],
    )[:30]
    results["most_active"] = sorted(
        all_items, key=lambda x: x["volume"], reverse=True,
    )[:30]

    # 52-week high/low: check if today's high >= prev close * 1.0 (approximation)
    # Full 52W check needs more data; use daily high vs open as proxy for now
    results["week52_high"] = sorted(
        [i for i in all_items if i["high"] >= i["ltp"] * 0.999],
        key=lambda x: x["pct_change"], reverse=True,
    )[:30]
    results["week52_low"] = sorted(
        [i for i in all_items if i["low"] <= i["ltp"] * 1.001 and i["pct_change"] < 0],
        key=lambda x: x["pct_change"],
    )[:30]

    results["fetched_at"] = _now_ist().isoformat()
    results["total_stocks"] = len(all_items)

    return results


@app.get("/api/market-movers")
async def api_market_movers(
    category: str = Query(default="gainers", regex="^(gainers|losers|week52_high|week52_low|most_active)$"),
    exchange: str = Query(default="ALL"),
):
    """
    Market movers: top gainers, losers, 52W high/low, most active.
    Cached for 5 minutes during market hours.
    """
    global _market_movers_cache, _market_movers_ts

    now = _now_ist()
    stale = (
        _market_movers_ts is None
        or (now - _market_movers_ts).total_seconds() > 300
    )

    if stale or not _market_movers_cache:
        try:
            _market_movers_cache = _fetch_market_movers()
            _market_movers_ts = now
        except Exception as e:
            logger.error("Market movers fetch failed: %s", e)
            if not _market_movers_cache:
                return {"category": category, "stocks": [], "error": str(e)}

    stocks = _market_movers_cache.get(category, [])

    # Exchange filter
    if exchange != "ALL":
        stocks = [s for s in stocks if s["exchange"] == exchange.upper()]

    return {
        "category": category,
        "exchange": exchange,
        "stocks": stocks,
        "total": len(stocks),
        "fetched_at": _market_movers_cache.get("fetched_at"),
        "total_universe": _market_movers_cache.get("total_stocks", 0),
    }


# ============================================================
# OHLCV Cache Management
# ============================================================


@app.get("/api/cache/stats")
async def api_cache_stats():
    """Cache size, hit rate, unique tickers, interval breakdown."""
    from mcp_server.ohlcv_cache import get_cache_stats

    db_session = SessionLocal()
    try:
        stats = get_cache_stats(db_session)
        return {"status": "ok", **stats}
    finally:
        db_session.close()


class CacheRefreshRequest(BaseModel):
    ticker: str
    interval: str = "1d"
    period: str = "1y"


@app.post("/tools/cache_refresh")
async def tool_cache_refresh(req: CacheRefreshRequest):
    """Force-refresh cached data for a ticker (invalidate + re-fetch)."""
    from mcp_server.ohlcv_cache import invalidate_ticker
    from mcp_server.data_provider import get_stock_data

    # Invalidate existing cache
    db_session = SessionLocal()
    try:
        deleted = invalidate_ticker(db_session, req.ticker, req.interval)
    finally:
        db_session.close()

    # Force re-fetch (will populate cache)
    df = get_stock_data(req.ticker, period=req.period, interval=req.interval, force_refresh=True)

    return {
        "status": "ok",
        "tool": "cache_refresh",
        "ticker": req.ticker,
        "interval": req.interval,
        "deleted_rows": deleted,
        "new_bars": len(df) if df is not None and not df.empty else 0,
    }


class CachePurgeRequest(BaseModel):
    days_to_keep: int = 1825


@app.post("/tools/cache_purge")
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


# ============================================================
# Dashboard — serve frontend static files (SPA)
# ============================================================
DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard_dist"

if DASHBOARD_DIR.is_dir():
    # Mount static assets (js, css, images) at /assets
    assets_dir = DASHBOARD_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="dashboard-assets")

    # Serve root → dashboard index.html
    @app.get("/", include_in_schema=False)
    async def serve_root():
        return FileResponse(str(DASHBOARD_DIR / "index.html"))

    # SPA catch-all: serve index.html for all unmatched routes
    # This MUST be the last route defined so API routes take priority
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        # Try to serve the exact file first (e.g. vite.svg, favicon.ico)
        file_path = DASHBOARD_DIR / full_path
        if file_path.is_file() and DASHBOARD_DIR in file_path.resolve().parents:
            return FileResponse(str(file_path))
        # Fallback to index.html for SPA client-side routing
        return FileResponse(str(DASHBOARD_DIR / "index.html"))

    logger.info("Dashboard frontend enabled from %s", DASHBOARD_DIR)
else:
    # API-only mode when no dashboard build exists
    @app.get("/", include_in_schema=False)
    async def root_api_only():
        return {
            "service": "MKUMARAN Trading OS",
            "version": "1.9",
            "status": "running",
            "docs": "/docs",
        }

    logger.info("Dashboard frontend not found at %s — API-only mode", DASHBOARD_DIR)


# ── RealtimeEngine API endpoints ──────────────────────────────────────────────

@app.get("/api/live-prices")
async def api_live_prices(symbols: str = Query(..., description="Comma-separated symbols")):
    """Batch LTP from WebSocket tick cache."""
    syms = [s.strip() for s in symbols.split(",") if s.strip()]
    if _realtime_engine:
        return _realtime_engine.cache.get_multiple_ltps(syms)
    return {s: None for s in syms}


@app.get("/api/realtime/status")
async def api_realtime_status():
    """RealtimeEngine health / status."""
    if not _realtime_engine:
        return {"active": False, "reason": "engine_not_started"}
    return {
        "active": _realtime_engine._active,
        "websocket_connected": (
            _realtime_engine.gwc_ws.connected if _realtime_engine.gwc_ws else False
        ),
        "subscribed_symbols": len(_realtime_engine._subscribed_symbols),
        "monitored_positions": len(_realtime_engine.monitor.positions),
        "redis_available": _realtime_engine.cache._available,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.MCP_SERVER_HOST, port=settings.MCP_SERVER_PORT)
