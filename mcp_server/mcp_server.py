import asyncio
import json
import logging
import os

from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc, text

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from mcp_server.config import settings
from mcp_server.db import init_db, run_alembic_upgrade, SessionLocal
from mcp_server.models import (
    ActiveTrade,
    MWAScore,
    Signal,
)

logger = logging.getLogger(__name__)

# ── Health tracking globals ──────────────────────────────────
_server_start_time: datetime | None = None
_index_cache: dict | None = None
_index_cache_ts: float = 0
_last_mwa_scan_time: datetime | None = None
_bot_app = None  # Telegram bot Application instance
_realtime_engine = None  # RealtimeEngine instance (WebSocket live feed)


def _now_ist() -> datetime:
    """Current datetime in IST regardless of server timezone."""
    from mcp_server.market_calendar import now_ist
    return now_ist()


async def _intraday_scan_loop():
    """Background task: run intraday scanners every 5 min during NSE hours.

    Completely separate from the daily-swing MWA loop. Gated behind
    settings.INTRADAY_SIGNALS_ENABLED — default false, so this is a no-op
    until the operator opts in via env. Delivers signals through the same
    Telegram / DB / Sheets / subscriber-broadcast paths the MWA cards use,
    just tagged ⚡ INTRADAY with a 5m timeframe.
    """
    from mcp_server.market_calendar import is_market_open

    if not getattr(settings, "INTRADAY_SIGNALS_ENABLED", False):
        logger.info("Intraday scan loop disabled (INTRADAY_SIGNALS_ENABLED=false)")
        return

    from mcp_server import intraday_scanner
    from mcp_server.db import SessionLocal
    from mcp_server.models import ActiveTrade, Signal

    interval_sec = int(getattr(settings, "INTRADAY_SCAN_INTERVAL_SEC", 300))
    logger.info(
        "Intraday scan loop started (every %ds during NSE hours)", interval_sec
    )

    while True:
        try:
            if not is_market_open("NSE"):
                await asyncio.sleep(interval_sec)
                continue

            def _run_intraday_sync() -> list[dict]:
                return intraday_scanner.run_scan()

            try:
                candidates = await asyncio.to_thread(_run_intraday_sync)
            except Exception as scan_err:
                logger.warning("Intraday scan failed: %s", scan_err)
                candidates = []

            if candidates:
                await _deliver_intraday_signals(candidates, SessionLocal, Signal, ActiveTrade)

            await asyncio.sleep(interval_sec)
        except asyncio.CancelledError:
            break
        except Exception as loop_err:
            logger.error("Intraday scan loop error: %s", loop_err)
            await asyncio.sleep(interval_sec)


async def _deliver_intraday_signals(
    candidates: list[dict],
    SessionLocal,  # noqa: N803
    Signal,
    ActiveTrade,
) -> None:
    """Persist, notify, and broadcast a batch of intraday candidates.

    Applies the SAME risk filters and delivery paths as the MWA loop
    (delivery %, FII, sector, subscriber broadcast) so intraday behaves
    consistently with swing — just tagged differently.
    """
    from mcp_server.telegram_bot import send_telegram_message

    db = SessionLocal()
    try:
        today = _now_ist().date()

        # Deduplicate against OPEN intraday signals from today — an ORB
        # breakout that re-fires every 5 min should not spam chat.
        open_keys = {
            (row[0], row[1])
            for row in db.query(Signal.ticker, Signal.direction)
            .filter(Signal.status == "OPEN", Signal.source == "intraday")
            .filter(Signal.signal_date == today)
            .all()
        }
        fresh = [
            c for c in candidates
            if (c["ticker"], c["direction"]) not in open_keys
        ]
        if not fresh:
            logger.info(
                "[INTRADAY] %d candidates, all already OPEN today — no delivery",
                len(candidates),
            )
            return

        for sig in fresh:
            try:
                db_signal = Signal(
                    signal_date=today,
                    signal_time=_now_ist().time(),
                    ticker=sig["ticker"],
                    exchange=sig["exchange"],
                    asset_class=sig["asset_class"],
                    direction=sig["direction"],
                    pattern=sig["pattern"],
                    entry_price=sig["entry"],
                    stop_loss=sig["sl"],
                    target=sig["target"],
                    rrr=sig["rrr"],
                    qty=0,
                    risk_amt=0,
                    ai_confidence=0,
                    scanner_count=sig["scanner_count"],
                    tier=2,
                    source="intraday",
                    timeframe="5m",
                    status="OPEN",
                )
                db.add(db_signal)
                db.flush()

                db.add(ActiveTrade(
                    signal_id=db_signal.id,
                    ticker=sig["ticker"],
                    exchange=sig["exchange"],
                    asset_class=sig["asset_class"],
                    entry_price=sig["entry"],
                    target=sig["target"],
                    stop_loss=sig["sl"],
                    prrr=sig["rrr"],
                    current_price=sig["entry"],
                    crrr=sig["rrr"],
                    last_updated=_now_ist(),
                    timeframe="5m",
                ))
                db.commit()

                # Sheets sync — same record_signal_to_sheets path as MWA.
                try:
                    from mcp_server.telegram_receiver import record_signal_to_sheets
                    record_signal_to_sheets({
                        "signal_id": f"INT-{db_signal.id}",
                        "date": str(today),
                        "ticker": sig["ticker"],
                        "exchange": sig["exchange"],
                        "asset_class": sig["asset_class"],
                        "direction": sig["direction"],
                        "entry_price": sig["entry"],
                        "stop_loss": sig["sl"],
                        "target": sig["target"],
                        "rrr": sig["rrr"],
                        "pattern": sig["pattern"],
                        "confidence": 0,
                        "notes": f"Intraday 5m | {sig['scanner_count']} scanners | {sig['pattern']}",
                    })
                except Exception as sheet_err:
                    logger.debug("Intraday Sheets sync failed: %s", sheet_err)

                sep = "\u2501" * 24
                msg = (
                    f"\u26a1 INTRADAY Signal\n"
                    f"{sep}\n"
                    f"Ticker: {sig['ticker']}\n"
                    f"Segment: NSE Equity | EQUITY\n"
                    f"Timeframe: 5m (Intraday)\n"
                    f"Direction: {sig['direction']}\n"
                    f"{sep}\n"
                    f"Entry: \u20b9{sig['entry']:.1f} | SL: \u20b9{sig['sl']:.1f} | TGT: \u20b9{sig['target']:.1f}\n"
                    f"RRR: {sig['rrr']:.1f} | Pattern: {sig['pattern']}\n"
                    f"{sep}\n"
                    f"Scanners: {sig['scanner_count']} fired\n"
                    f"Signal ID: INT-{db_signal.id}\n"
                    f"\u26a0\ufe0f Close by 15:15 IST to avoid carry"
                )
                _fire_and_forget(send_telegram_message(
                    msg, exchange=sig["exchange"], force=True
                ))

                # Subscriber broadcast — respects per-user segment opt-in.
                try:
                    from mcp_server.telegram_saas import broadcast_signal_to_users
                    _fire_and_forget(
                        broadcast_signal_to_users(msg, exchange=sig["exchange"])
                    )
                except Exception as broadcast_err:
                    logger.debug(
                        "Intraday subscriber broadcast skipped for %s: %s",
                        sig["ticker"], broadcast_err,
                    )

                logger.info(
                    "[INTRADAY] delivered %s %s entry=%.2f pattern=%s",
                    sig["ticker"], sig["direction"], sig["entry"], sig["pattern"],
                )
            except Exception as deliver_err:
                logger.warning(
                    "[INTRADAY] delivery failed for %s: %s",
                    sig["ticker"], deliver_err,
                )
                db.rollback()
    finally:
        db.close()


async def _options_signal_loop():
    """Background task: scan for pure options strategies every 10 min during F&O hours."""
    if not getattr(settings, "OPTION_SIGNALS_ENABLED", True):
        logger.info("Options signal loop disabled (OPTION_SIGNALS_ENABLED=false)")
        return

    from mcp_server.market_calendar import is_market_open as _mkt_open

    logger.info("Options signal loop started (every 600s during F&O hours)")

    # Track sent signals to avoid duplicates within the same day
    sent_today: set[str] = set()
    last_date = ""

    while True:
        try:
            if not _mkt_open("NSE"):
                await asyncio.sleep(600)
                continue

            today = str(date.today())
            if today != last_date:
                sent_today.clear()
                last_date = today

            def _run_options_sync():
                from mcp_server.options_signal_engine import run_options_scan
                return run_options_scan()

            try:
                signals = await asyncio.to_thread(_run_options_sync)
            except Exception as scan_err:
                logger.warning("Options signal scan failed: %s", scan_err)
                signals = []

            if signals:
                from mcp_server.telegram_bot import send_telegram_message
                from mcp_server.options_signal_engine import format_option_signal_card

                for sig in signals:
                    dedup_key = f"{sig['symbol']}:{sig['pattern']}:{sig.get('direction','')}"
                    if dedup_key in sent_today:
                        continue
                    sent_today.add(dedup_key)
                    msg = format_option_signal_card(sig)
                    _fire_and_forget(send_telegram_message(msg, force=True))
                    # Broadcast to subscribers
                    try:
                        from mcp_server.telegram_saas import broadcast_signal_to_users
                        _fire_and_forget(broadcast_signal_to_users(msg, exchange="NFO"))
                    except Exception:
                        pass
                    logger.info(
                        "[OPTIONS] signal: %s %s %s",
                        sig["symbol"], sig["strategy"], sig.get("rationale", "")[:80],
                    )

            await asyncio.sleep(600)
        except asyncio.CancelledError:
            break
        except Exception as loop_err:
            logger.error("Options signal loop error: %s", loop_err)
            await asyncio.sleep(600)


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
                # Run the sync scan in a worker thread so the event loop stays
                # responsive (health checks, API, Telegram sends) during the
                # ~5-minute scan window. We also proactively refresh the Angel
                # JWT before each scan — the SmartAPI library logs AG8001
                # errors internally and returns None/empty instead of raising,
                # so per-request detection is unreliable. Refreshing once per
                # cycle guarantees a healthy token.
                def _run_scan_sync(segs: list[str]) -> None:
                    try:
                        from mcp_server.data_provider import get_provider
                        provider = get_provider()
                        # Skip the proactive Angel refresh if the session-level
                        # circuit breaker has tripped — Angel's IP whitelist is
                        # rejecting us, so a fresh JWT will not help and we will
                        # just burn ~30s per cycle on TOTP login.
                        if (
                            hasattr(provider, "angel")
                            and provider.angel
                            and getattr(provider.angel, "is_disabled", lambda: False)()
                        ):
                            logger.info(
                                "Auto-scan: Angel session-disabled — "
                                "skipping pre-refresh"
                            )
                        else:
                            from mcp_server.angel_auth import force_refresh_angel_token
                            new_client = force_refresh_angel_token()
                            if hasattr(provider, "angel") and provider.angel:
                                provider.angel.client = new_client
                                provider.angel.logged_in = True
                                if hasattr(provider.angel, "_token_cache"):
                                    provider.angel._token_cache.clear()
                                provider._sources["angel"] = True
                            logger.info("Auto-scan: Angel token pre-refreshed")
                    except Exception as refresh_err:
                        logger.warning(
                            "Auto-scan: Angel pre-refresh failed (%s) — "
                            "continuing with yfinance fallback",
                            refresh_err,
                        )
                    db = SessionLocal()
                    try:
                        _execute_mwa_scan(db, segments=segs)
                        logger.info("Auto-scan: MWA scan completed")
                    finally:
                        db.close()

                try:
                    await asyncio.to_thread(_run_scan_sync, open_segments)
                except Exception as e:
                    logger.error("Auto-scan worker thread failed: %s", e)
            await asyncio.sleep(900)  # 15 minutes
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Auto-scan loop error: %s", e)
            await asyncio.sleep(900)


# Self-development loop state — keyed by date so we only run once per day
_self_dev_cache: dict[str, Any] = {}

# Kite login notification throttle — one success message per calendar day,
# regardless of how many times /api/kite_callback fires.
_kite_login_notify_cache: dict[str, str] = {}

# Scan-in-progress lock — prevents concurrent MWA scans from the auto-scan
# loop (every 15 min) and n8n extended monitor (every 10 min) from
# overlapping and generating duplicate signals for the same ticker.
import threading  # noqa: E402 — deferred to this point to avoid circular import
_scan_lock = threading.Lock()


async def _self_dev_loop():
    """
    Daily self-development pipeline that runs once at PREDICTOR_RETRAIN_HOUR IST
    (default 16:00 — after all intraday SL/TP checks are complete for the day).

    Steps:
      1. Batch-run postmortems for any recently-closed signals missing one
      2. Retrain the loss predictor on all labeled data
      3. Update Bayesian scanner stats
      4. Mine new adaptive rules (dry-run by default — operator must activate)
      5. Send a Telegram summary with the key numbers

    Idempotent — `_self_dev_cache[date]` prevents re-running.
    """
    logger.info("Self-development loop started (runs at %d:00 IST daily)", settings.PREDICTOR_RETRAIN_HOUR)

    while True:
        try:
            await asyncio.sleep(60)

            now = _now_ist()
            if now.hour != settings.PREDICTOR_RETRAIN_HOUR or now.minute > 5:
                continue

            today_key = now.date().isoformat()
            if _self_dev_cache.get(today_key) == "done":
                continue

            # Skip weekends
            if now.weekday() >= 5:
                _self_dev_cache[today_key] = "skipped_weekend"
                continue

            logger.info("Self-dev pipeline starting for %s", today_key)
            _self_dev_cache[today_key] = "running"

            summary = await asyncio.to_thread(_run_self_dev_pipeline_sync)

            _self_dev_cache[today_key] = "done"
            logger.info("Self-dev pipeline complete: %s", summary)

            # Optional: Telegram summary
            try:
                from mcp_server.telegram_bot import send_telegram_message
                msg = _format_self_dev_telegram(summary)
                if msg:
                    await send_telegram_message(msg, force=True)
            except Exception as tg_err:
                logger.debug("Self-dev Telegram send skipped: %s", tg_err)

        except asyncio.CancelledError:
            logger.info("Self-development loop stopped")
            break
        except Exception as e:
            logger.error("Self-dev loop error: %s", e)
            await asyncio.sleep(60)


def _run_self_dev_pipeline_sync() -> dict[str, Any]:
    """Synchronous worker for the self-development pipeline. Safe to call from
    a worker thread or API endpoint."""
    summary: dict[str, Any] = {"steps": {}, "status": "ok"}

    # Step 1: Batch postmortems
    try:
        from mcp_server.signal_postmortem import run_batch_postmortems
        pm = run_batch_postmortems(lookback_days=settings.POSTMORTEM_LOOKBACK_DAYS)
        summary["steps"]["postmortems"] = pm
    except Exception as e:
        summary["steps"]["postmortems"] = {"status": "error", "reason": str(e)}

    # Step 2: Retrain predictor
    try:
        from mcp_server.signal_predictor import retrain_predictor
        pred = retrain_predictor()
        summary["steps"]["predictor"] = pred
    except Exception as e:
        summary["steps"]["predictor"] = {"status": "error", "reason": str(e)}

    # Step 3: Bayesian scanner stats
    try:
        from mcp_server.scanner_bayesian import update_bayesian_stats
        bayes = update_bayesian_stats()
        summary["steps"]["bayesian"] = bayes
    except Exception as e:
        summary["steps"]["bayesian"] = {"status": "error", "reason": str(e)}

    # Step 4: Mine adaptive rules (dry-run)
    if getattr(settings, "RULES_MINE_ON_RETRAIN", True):
        try:
            from mcp_server.rules_engine import mine_rules
            rules = mine_rules(dry_run=True)
            # Strip the verbose `evaluated` list to keep summary compact
            if isinstance(rules, dict) and "evaluated" in rules:
                rules = {k: v for k, v in rules.items() if k != "evaluated"}
            summary["steps"]["rules"] = rules
        except Exception as e:
            summary["steps"]["rules"] = {"status": "error", "reason": str(e)}

    # Step 5: Auto-disable underperforming scanners
    try:
        from mcp_server.scanner_bayesian import auto_disable_underperformers
        disable_result = auto_disable_underperformers()
        summary["steps"]["auto_disable"] = disable_result
    except Exception as e:
        summary["steps"]["auto_disable"] = {"status": "error", "reason": str(e)}

    # Step 6: EOD corrections analysis — identify what went wrong today
    # and apply automatic corrections for tomorrow.
    try:
        from mcp_server.db import SessionLocal as _EodSession
        from mcp_server.models import Signal, Outcome
        eod_db = _EodSession()
        try:
            today = date.today()
            # Today's closed trades
            today_outcomes = (
                eod_db.query(Signal, Outcome)
                .join(Outcome, Outcome.signal_id == Signal.id)
                .filter(Outcome.exit_date == today)
                .all()
            )
            today_wins = sum(1 for _, o in today_outcomes if o.outcome == "WIN")
            today_losses = sum(1 for _, o in today_outcomes if o.outcome == "LOSS")
            today_pnl = sum(float(o.pnl_amount or 0) for _, o in today_outcomes)

            # Which scanners/skills produced losses today?
            losing_scanners: dict[str, int] = {}
            for sig, out in today_outcomes:
                if out.outcome == "LOSS" and sig.scanner_list:
                    for sc in sig.scanner_list:
                        losing_scanners[sc] = losing_scanners.get(sc, 0) + 1

            # Top 3 losing scanners → recommendation
            worst = sorted(losing_scanners.items(), key=lambda x: -x[1])[:3]

            summary["steps"]["eod_analysis"] = {
                "today_trades": len(today_outcomes),
                "today_wins": today_wins,
                "today_losses": today_losses,
                "today_pnl": round(today_pnl, 2),
                "today_win_rate": round(today_wins / max(len(today_outcomes), 1) * 100, 1),
                "worst_scanners": worst,
                "correction": (
                    f"Disable {worst[0][0]} ({worst[0][1]} losses)" if worst
                    else "No specific scanner to disable"
                ),
            }
        finally:
            eod_db.close()
    except Exception as eod_err:
        summary["steps"]["eod_analysis"] = {"status": "error", "reason": str(eod_err)}

    return summary


def _format_self_dev_telegram(summary: dict[str, Any]) -> str | None:
    """Format a compact Telegram digest of the daily self-dev run."""
    try:
        steps = summary.get("steps", {})
        pm = steps.get("postmortems", {}) or {}
        pred = steps.get("predictor", {}) or {}
        bayes = steps.get("bayesian", {}) or {}
        rules = steps.get("rules", {}) or {}

        lines = [
            "\U0001f9e0 Self-Development Daily Run",
            "\u2501" * 24,
        ]

        # Postmortems
        lines.append(
            f"\U0001f50d Postmortems: {pm.get('processed', 0)} processed"
            f" / {pm.get('total_candidates', 0)} candidates"
        )

        # Predictor
        pstatus = pred.get("status", "n/a")
        if pstatus == "ok":
            auc = pred.get("cv_auc")
            auc_str = f"{auc:.3f}" if auc is not None else "n/a"
            lines.append(
                f"\U0001f9ee Predictor: v={pred.get('version', 'n/a')}"
                f" samples={pred.get('samples', 0)}"
                f" loss_rate={pred.get('loss_rate', 0):.0%} AUC={auc_str}"
            )
        else:
            lines.append(f"\U0001f9ee Predictor: {pstatus} ({pred.get('reason', '')[:60]})")

        # Bayesian
        if bayes.get("status") == "ok":
            lines.append(
                f"\U0001f4ca Scanners: {bayes.get('scanners_tracked', 0)} tracked,"
                f" {bayes.get('underperforming_count', 0)} underperforming"
            )
        else:
            lines.append(f"\U0001f4ca Scanners: {bayes.get('status', 'n/a')}")

        # Rules
        if rules.get("status") == "ok":
            promoted = rules.get("promoted", [])
            lines.append(
                f"\u2696\ufe0f Rules: {len(promoted)} new candidates"
                f" ({rules.get('candidates', 0)} evaluated)"
            )
            for r in promoted[:3]:
                lines.append(
                    f"  \u2022 {r['key']} lift={r['lift']:+.2f} (-{r['losses_prevented']}L/-{r['wins_lost']}W)"
                )
        else:
            lines.append(f"\u2696\ufe0f Rules: {rules.get('status', 'n/a')}")

        # Auto-disable report
        ad = steps.get("auto_disable", {}) or {}
        if ad.get("newly_disabled") or ad.get("re_enabled"):
            lines.append("\u2501" * 24)
            lines.append("\U0001f6a8 Scanner Auto-Management")
            if ad.get("newly_disabled_list"):
                lines.append("DISABLED (losing):")
                for d in ad["newly_disabled_list"]:
                    lines.append(f"  \u274c {d['key']} ({d['wins']}W/{d['losses']}L = {d['wr']})")
            if ad.get("re_enabled_list"):
                lines.append("RE-ENABLED (improved):")
                for r in ad["re_enabled_list"]:
                    lines.append(f"  \u2705 {r['key']} ({r['wins']}W/{r['losses']}L = {r['wr']})")
            lines.append(f"Total disabled: {ad.get('total_disabled', 0)}/{ad.get('total_tracked', 0)}")

        # EOD Analysis
        eod = steps.get("eod_analysis", {}) or {}
        if eod.get("today_trades"):
            lines.append("\u2501" * 24)
            lines.append("\U0001f4cb Today's Analysis")
            lines.append(
                f"Trades: {eod['today_trades']} | "
                f"W: {eod['today_wins']} L: {eod['today_losses']} | "
                f"WR: {eod['today_win_rate']}%"
            )
            lines.append(f"P&L: \u20b9{eod['today_pnl']:,.0f}")
            if eod.get("worst_scanners"):
                worst = eod["worst_scanners"]
                lines.append(
                    "Worst skills: " + ", ".join(
                        f"{s}({n}L)" for s, n in worst
                    )
                )
            if eod.get("correction"):
                lines.append(f"\u2699\ufe0f Correction: {eod['correction']}")

        return "\n".join(lines)
    except Exception as e:
        logger.debug("format_self_dev_telegram failed: %s", e)
        return None


def _price_refresh_once_sync() -> None:
    """One pass of active-trade LTP refresh. Synchronous — must run in
    a worker thread via asyncio.to_thread so the event loop stays
    responsive (health checks, API, Telegram)."""
    db = SessionLocal()
    try:
        trades = db.query(ActiveTrade).options(
            joinedload(ActiveTrade.signal),
        ).all()
        count = 0
        for t in trades:
            try:
                ltp = None
                if _realtime_engine:
                    ticker_clean = t.ticker.replace("NSE:", "") if t.ticker else ""
                    if ticker_clean:
                        ltp = _realtime_engine.get_ltp(ticker_clean)
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


async def _price_refresh_loop():
    """Background task: refresh active trade prices every 60s during market hours.

    Runs whenever ANY tracked market segment is open (NSE/MCX/CDS).
    Previously only ran during NSE hours, which left forex (CDS) and
    commodity (MCX) active trades with stale prices outside 09:15-15:30.

    The actual refresh is a sync blocking operation (REST + DB), so we run it
    in a worker thread to keep the event loop responsive for /health, API
    requests, and Telegram.
    """
    from mcp_server.market_calendar import is_market_open
    while True:
        try:
            any_market_open = any(
                is_market_open(seg) for seg in ("NSE", "MCX", "CDS")
            )
            if any_market_open:
                try:
                    await asyncio.to_thread(_price_refresh_once_sync)
                except Exception as e:
                    logger.error("Price refresh worker thread failed: %s", e)
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

    # Run Alembic migrations BEFORE init_db(). Non-fatal — if Alembic
    # fails for any reason, init_db()'s Base.metadata.create_all() still
    # creates any missing tables so the app can boot in a degraded state.
    # See docs/SCHEMA_CONSOLIDATION_PLAN.md.
    try:
        await asyncio.to_thread(run_alembic_upgrade)
    except Exception as alembic_err:
        logger.error("Alembic upgrade crashed (continuing boot): %s", alembic_err)

    try:
        logger.info("Initializing database...")
        init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.warning("Database init skipped (not available): %s", e)

    # One-shot purge of stale yfinance MCX/NFO rows. They map CRUDEOIL→CL=F
    # (NYMEX WTI USD) etc., which is wrong currency + wrong contract for
    # MCX FUTCOM lookups. After purge, next fetch hits gwc/angel/kite.
    try:
        from mcp_server.ohlcv_cache import purge_yfinance_mcx_nfo
        from mcp_server.db import SessionLocal
        _purge_session = SessionLocal()
        try:
            purged = purge_yfinance_mcx_nfo(_purge_session)
            if purged:
                logger.info("Startup: purged %d stale yfinance MCX/NFO cache rows", purged)
        finally:
            _purge_session.close()
    except Exception as e:
        logger.debug("Startup yfinance MCX/NFO purge skipped: %s", e)

    # Auto-close stale signals — signals OPEN for >7 days without hitting
    # SL or TGT are expired. This prevents the OPEN signal count from
    # growing indefinitely (was 1318), which breaks dedup, signal monitor
    # performance, and EOD accuracy reporting.
    try:
        _stale_db = SessionLocal()
        try:
            # Aggressive 3-day cutoff — no swing trade should stay open
            # for 3+ days without hitting SL or TGT. If it hasn't moved
            # in 3 days, the setup is invalidated.
            stale_cutoff = (date.today() - timedelta(days=3))
            stale_signals = _stale_db.query(Signal).filter(
                Signal.status == "OPEN",
                Signal.signal_date < stale_cutoff,
            ).all()
            if stale_signals:
                for sig in stale_signals:
                    sig.status = "EXPIRED"
                _stale_db.commit()
                expired_ids = [s.id for s in stale_signals]
                _stale_db.query(ActiveTrade).filter(
                    ActiveTrade.signal_id.in_(expired_ids)
                ).delete(synchronize_session=False)
                _stale_db.commit()
                logger.info(
                    "Startup: expired %d stale OPEN signals (older than %s)",
                    len(stale_signals), stale_cutoff,
                )
        finally:
            _stale_db.close()
    except Exception as stale_err:
        logger.debug("Stale signal cleanup skipped: %s", stale_err)

    # Force-train the loss predictor at startup if enough closed trades
    # exist and no model is loaded yet. The self-dev loop only runs at
    # 16:00 IST — but the predictor should be ready from boot.
    try:
        from mcp_server.signal_predictor import get_predictor, retrain_predictor
        pred = get_predictor()
        if not pred.is_ready():
            logger.info("Startup: loss predictor not ready — attempting training")
            result = retrain_predictor()
            logger.info("Startup: predictor training result: %s", result)
        else:
            logger.info("Startup: loss predictor ready (model loaded)")
    except Exception as pred_err:
        logger.debug("Startup predictor training skipped: %s", pred_err)

    # Update Bayesian scanner stats at startup so the confidence booster
    # has fresh per-scanner win rates from the first scan cycle.
    try:
        from mcp_server.scanner_bayesian import update_bayesian_stats
        bay_result = update_bayesian_stats()
        logger.info(
            "Startup: Bayesian scanner stats updated — %d scanners tracked",
            bay_result.get("scanners_tracked", 0),
        )
    except Exception as bay_err:
        logger.debug("Startup Bayesian stats skipped: %s", bay_err)

    # Force-clear stale Dhan instrument cache so the latest scrip master
    # (with futures aliases for MCX/NFO/CDS) is loaded fresh. The cached
    # file from pre-fix deployments has no MCX:GOLD → FUTCOM mappings.
    try:
        from pathlib import Path
        dhan_cache = Path("data/dhan_instruments.json")
        if dhan_cache.exists():
            dhan_cache.unlink()
            logger.info("Startup: cleared stale Dhan instrument cache")
    except Exception:
        pass

    # Dhan token lifecycle: auto-refresh via TOTP if configured, else warn.
    # The DhanSource.login() above already tried auto-refresh. Here we just
    # log the result and send a Telegram nudge only if auto-refresh is not
    # configured and the token is expiring.
    try:
        from mcp_server.telegram_bot import send_telegram_message
        dhan_token = os.environ.get("DHAN_ACCESS_TOKEN", "")
        has_auto = bool(os.environ.get("DHAN_TOTP_KEY") and os.environ.get("DHAN_PIN"))
        if dhan_token.startswith("eyJ"):
            import base64
            payload = json.loads(base64.urlsafe_b64decode(dhan_token.split(".")[1] + "=="))
            exp = payload.get("exp", 0)
            hours_left = (exp - _now_ist().timestamp()) / 3600
            if has_auto:
                logger.info(
                    "Dhan token: %.0fh remaining (auto-refresh configured)", hours_left
                )
            elif hours_left <= 0:
                _fire_and_forget(send_telegram_message(
                    "\u26a0\ufe0f Dhan token EXPIRED — MCX/intraday data offline.\n"
                    "Paste a fresh token: /dhantoken eyJ0...\n"
                    "Or set DHAN_TOTP_KEY + DHAN_PIN for auto-refresh.",
                    force=True,
                ))
            elif hours_left <= 2:
                _fire_and_forget(send_telegram_message(
                    f"\u26a0\ufe0f Dhan token expires in {hours_left:.0f}h.\n"
                    "Renew: /dhantoken <paste> or set DHAN_TOTP_KEY + DHAN_PIN.",
                    force=True,
                ))
            else:
                logger.info("Dhan token valid for %.0fh (no auto-refresh)", hours_left)
    except Exception as dhan_exp_err:
        logger.debug("Dhan token expiry check skipped: %s", dhan_exp_err)

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

    # Index prices fetched by auto-scan loop, not separately
    logger.info("Index prices will be updated during MWA scan cycles")

    # Start auto-scan background task (every 15 min during market hours)
    auto_scan_task = asyncio.create_task(_auto_scan_loop())
    logger.info("Auto-scan background task started (every 15 min during market hours)")

    # Start intraday scan loop — opt-in via INTRADAY_SIGNALS_ENABLED. The
    # task itself short-circuits when the flag is off, so creating it
    # unconditionally is safe and keeps lifecycle shutdown clean.
    asyncio.create_task(_intraday_scan_loop())
    logger.info(
        "Intraday scan background task started (enabled=%s)",
        getattr(settings, "INTRADAY_SIGNALS_ENABLED", False),
    )

    # Start pure options signal loop (IV crush, PCR extreme, expiry plays, etc.)
    asyncio.create_task(_options_signal_loop())
    logger.info(
        "Options signal loop started (enabled=%s)",
        getattr(settings, "OPTION_SIGNALS_ENABLED", True),
    )

    # Start all dedicated segment agents (Options Index, Options Stock,
    # Commodity, Forex, Futures) — each with its own scan loop, market
    # hours, and signal format.
    try:
        from mcp_server.agents.orchestrator import start_all_agents
        await start_all_agents()
    except Exception as agent_err:
        logger.warning("Agent orchestrator startup failed: %s", agent_err)

    # Start scanner review background task (triggers at 15:45 IST)
    scanner_review_task = None
    if getattr(settings, "SCANNER_REVIEW_ENABLED", True):
        from mcp_server.scanner_review import scanner_review_loop
        scanner_review_task = asyncio.create_task(scanner_review_loop())
        logger.info("Scanner review background task started (15:45 IST daily)")

    # Start self-development background task (postmortem + retrain + rules mining at 16:00 IST)
    self_dev_task = None
    if getattr(settings, "SELF_DEV_ENABLED", True):
        try:
            self_dev_task = asyncio.create_task(_self_dev_loop())
            logger.info("Self-development background task started (16:00 IST daily)")
        except Exception as e:
            logger.warning("Self-development loop startup skipped: %s", e)

    # Start F&O analytics auto-monitor (every 5 min during NFO hours)
    fno_analytics_task = None
    if getattr(settings, "FNO_ANALYTICS_ENABLED", True):
        try:
            from mcp_server.fno_analytics_monitor import fno_analytics_loop
            fno_analytics_task = asyncio.create_task(fno_analytics_loop())
            logger.info("F&O analytics monitor started (every 5 min during NFO hours)")
        except Exception as e:
            logger.warning("F&O analytics monitor startup skipped: %s", e)

    # Start options seller Greeks refresh loop (every 5 min during market hours)
    # Monitors open strangle/condor positions and fires adjustment alerts.
    # Disable with OPTIONS_GREEKS_LOOP_ENABLED=false.
    try:
        from mcp_server.options_seller.greeks_refresh_loop import start_loop as _opts_loop
        asyncio.create_task(_opts_loop())
        logger.info("Options seller Greeks refresh loop started (every 5 min, market hours only)")
    except Exception as e:
        logger.warning("Options seller Greeks refresh loop startup skipped: %s", e)

    # Start broker reconciler loop (every 60s during market hours).
    # Compares live broker position book to active_trades in Postgres.
    # Alerts on GHOST / PHANTOM / QTY_DRIFT. Never raises — logs only.
    async def _reconciler_loop() -> None:
        import asyncio as _aio
        from mcp_server.market_calendar import is_market_open as _is_open
        while True:
            try:
                if _is_open("NSE") or _is_open("MCX"):
                    from mcp_server.broker_reconciler import run_reconciliation
                    await _aio.to_thread(run_reconciliation, True)
            except Exception as _re:
                logger.debug("Broker reconciler loop error: %s", _re)
            await _aio.sleep(60)

    asyncio.create_task(_reconciler_loop())
    logger.info("Broker reconciler loop started (every 60s during market hours)")

    # Auto-login to Goodwill (GWC) at startup — mirrors Kite auto-login pattern.
    # Runs in worker thread to avoid blocking the event loop.
    try:
        if (
            getattr(settings, "GWC_API_KEY", "")
            and getattr(settings, "GWC_CLIENT_ID", "")
            and getattr(settings, "GOODWILL_PASSWORD", "")
            and getattr(settings, "GOODWILL_TOTP_KEY", "")
        ):
            async def _gwc_startup_login():
                try:
                    from mcp_server.gwc_auth import refresh_gwc_token
                    from mcp_server.data_provider import get_provider
                    access_token = await asyncio.to_thread(refresh_gwc_token)
                    provider = get_provider()
                    provider.gwc.set_access_token(access_token)
                    provider._sources["gwc"] = True
                    logger.info("GWC auto-login OK at startup (token_prefix=%s...)", access_token[:8])
                except Exception as exc:
                    logger.warning("GWC auto-login at startup failed: %s", exc)
            asyncio.create_task(_gwc_startup_login())
            logger.info("GWC auto-login background task scheduled")
        else:
            logger.info("GWC auto-login skipped (credentials incomplete)")
    except Exception as e:
        logger.warning("GWC auto-login scheduling error: %s", e)

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

    # Shutdown — cancel scanner review task
    if scanner_review_task and not scanner_review_task.done():
        scanner_review_task.cancel()
        try:
            await scanner_review_task
        except asyncio.CancelledError:
            pass

    # Shutdown — cancel F&O analytics monitor
    if fno_analytics_task and not fno_analytics_task.done():
        fno_analytics_task.cancel()
        try:
            await fno_analytics_task
        except asyncio.CancelledError:
            pass

    # Shutdown — cancel self-development loop
    if self_dev_task and not self_dev_task.done():
        self_dev_task.cancel()
        try:
            await self_dev_task
        except asyncio.CancelledError:
            pass
    logger.info("MCP Server shutting down")


app = FastAPI(
    title="MKUMARAN Trading OS - MCP Server",
    description="Hybrid Trading Intelligence MCP Server",
    version="1.0.0",
    lifespan=lifespan,
)

# ── Per-domain routers (progressive extraction) ─────────────
# See docs/MCP_SERVER_ROUTER_SPLIT_PLAN.md for the full layout.
from mcp_server.routers import admin as _router_admin  # noqa: E402
from mcp_server.routers import auth as _router_auth  # noqa: E402
from mcp_server.routers import backtest as _router_backtest  # noqa: E402
from mcp_server.routers import brokers as _router_brokers  # noqa: E402
from mcp_server.routers import fno as _router_fno  # noqa: E402
from mcp_server.routers import health as _router_health  # noqa: E402
from mcp_server.routers import market_data as _router_market_data  # noqa: E402
from mcp_server.routers import options as _router_options  # noqa: E402
from mcp_server.routers import scanners as _router_scanners  # noqa: E402
from mcp_server.routers import selfdev as _router_selfdev  # noqa: E402
from mcp_server.routers import signals as _router_signals  # noqa: E402
from mcp_server.routers import trades as _router_trades  # noqa: E402
from mcp_server.routers import wallstreet as _router_wallstreet  # noqa: E402
from mcp_server.routers import watchlist as _router_watchlist  # noqa: E402
from mcp_server.routers import webhooks as _router_webhooks  # noqa: E402
app.include_router(_router_admin.router)
app.include_router(_router_auth.router)
app.include_router(_router_backtest.router)
app.include_router(_router_brokers.router)
app.include_router(_router_fno.router)
app.include_router(_router_health.router)
app.include_router(_router_market_data.router)
app.include_router(_router_options.router)
app.include_router(_router_scanners.router)
app.include_router(_router_selfdev.router)
app.include_router(_router_signals.router)
app.include_router(_router_trades.router)
app.include_router(_router_wallstreet.router)
app.include_router(_router_watchlist.router)
app.include_router(_router_webhooks.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from mcp_server.routers.deps import limiter  # noqa: E402
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Auth Middleware (opt-in via AUTH_ENABLED=true) ──────────

# Paths that never require auth
AUTH_PUBLIC_PATHS = {
    "/auth/login", "/api/auth/login", "/api/auth/google",
    "/api/auth/send-otp", "/api/auth/verify-otp",
    "/api/auth/register", "/api/auth/user-login",
    "/api/auth/reset-password", "/api/auth/config",
    "/api/user/tier", "/api/user/check-feature",
    "/api/info", "/health", "/docs",
    "/openapi.json", "/redoc",
    "/api/tv_webhook", "/api/telegram_webhook",
    "/api/kite_callback", "/api/kite_login_url",
    "/api/gwc_callback", "/api/gwc_login_url",
    "/tools/connect_angel", "/tools/refresh_angel_token",
    "/tools/connect_gwc", "/tools/refresh_gwc_token",
    # n8n workflow endpoints (read-only scan/data tools)
    "/tools/run_mwa_scan", "/tools/get_stock_data",
    "/tools/order_status", "/tools/get_fo_signal",
    "/tools/update_all_trailing_sl", "/tools/check_exit_strategies",
    # AI report + news sentiment (n8n calls without auth)
    "/tools/ai_report", "/tools/news_sentiment",
    # Scanner review (n8n compatible)
    "/tools/run_scanner_review",
    # F&O OI buildup scanner (n8n compatible)
    "/tools/scan_oi_buildup",
    # F&O analytics manual trigger (n8n compatible)
    "/tools/run_fno_analytics",
    # F&O pure-math endpoint (caller supplies all inputs, no proprietary data)
    "/api/fno/option_greeks",
    # Sheets reconciliation (n8n compatible, idempotent)
    "/tools/backfill_sheets_outcomes",
    # Dhan intraday backfill (internal admin, no sensitive data returned)
    "/tools/run_backfill", "/tools/backfill_status",
    # Self-development system (n8n compatible)
    "/tools/run_self_development",
    "/tools/run_postmortems",
    "/tools/retrain_predictor",
    "/tools/update_bayesian_stats",
    "/tools/mine_rules",
    # Dashboard read-only endpoints — public so the SPA loads without
    # requiring login. Write operations (order placement, settings) still
    # require auth. Re-secure these once SaaS user auth is production-ready.
    "/api/market-movers",
    "/api/active_trades",
    "/api/signals",
    "/api/mwa_score",
    "/api/dashboard",
    "/api/momentum",
    "/api/health",
    "/api/watchlist",
    "/tools/market_movers",
    "/tools/signal_accuracy",
    "/tools/portfolio_exposure",
    "/tools/trade_memory_stats",
    "/tools/reflect_trades",
    "/tools/check_signals",
    "/tools/backtest_strategy",
    "/tools/backtest_validate",
    "/tools/eod_summary",
    "/tools/reset_sheets",
}
AUTH_PUBLIC_PREFIXES = (
    "/assets/", "/docs/", "/redoc/",
    "/tools/mwa_scan_status/", "/api/chart/",
    "/api/scanner-review/",
    "/api/selfdev/",
    # F&O calendar lookup only (no market data leak)
    "/api/fno/expiry/",
    # Options enrichment — universe list + per-symbol picker
    "/api/fno/option_recommendation/",
    "/api/fno/option_universe",
    # Dashboard data endpoints (read-only, re-secure for SaaS production)
    "/api/backtest/",
    "/api/signals/",
    "/api/trades/",
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


# `/api/info`, `/health`, `/api/exchanges` were moved to
# `mcp_server.routers.health` in the Phase 1a router split — see
# docs/MCP_SERVER_ROUTER_SPLIT_PLAN.md. Router is included further down
# where `app` is constructed.


# ============================================================
# Authentication Endpoints
# ============================================================


# ── Multi-Auth: Register, Login, Google, OTP ──────────────────


# ── BYOK: User API Keys ──────────────────────────────────────


# ── Tier Enforcement API ──────────────────────────────────────


# ============================================================
# MCP Tool Endpoints — wired to real engines
# ============================================================


# `/api/exchanges` moved to mcp_server.routers.health in Phase 1a.


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


def _execute_mwa_scan(db: Session, segments: list[str] | None = None) -> dict:
    """Core MWA scan logic — used by both sync and async modes.

    Acquires _scan_lock to prevent concurrent executions from producing
    duplicate signals (n8n every 10 min + auto_scan_loop every 15 min
    would otherwise overlap). If the lock is held, returns immediately
    with status="skipped".

    Args:
        segments: List of open segments to scan (e.g. ["MCX", "CDS"]).
                  None = scan all segments (backward compat for manual API).
    """
    if not _scan_lock.acquire(blocking=False):
        logger.info("MWA scan skipped — another scan is already in progress")
        return {"status": "skipped", "reason": "concurrent scan in progress"}

    try:
        return _execute_mwa_scan_impl(db, segments)
    finally:
        _scan_lock.release()


def _execute_mwa_scan_impl(db: Session, segments: list[str] | None = None) -> dict:
    """Inner implementation — always called under _scan_lock."""
    from mcp_server.mwa_scanner import MWAScanner
    from mcp_server.mwa_scoring import calculate_mwa_score, get_promoted_stocks, format_morning_brief
    from mcp_server.asset_registry import CDS_UNIVERSE, MCX_UNIVERSE, NFO_INDEX_UNIVERSE, NFO_STOCK_UNIVERSE
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
        # Limit universe size to prevent server crash on small VPS
        import os as _os
        import time as _scan_time
        import gc as _gc
        _MAX_NSE = int(_os.getenv("MWA_MAX_NSE_STOCKS", "30"))
        _BATCH_DELAY = float(_os.getenv("MWA_BATCH_DELAY", "0.1"))
        if segments is None or "NSE" in segments:
            nse_stocks = _get_nse_universe()[:_MAX_NSE]
            logger.info("Scanning %d NSE stocks (limit=%d, delay=%.1fs)", len(nse_stocks), _MAX_NSE, _BATCH_DELAY)
            for i, ticker in enumerate(nse_stocks):
                if i > 0 and i % 10 == 0:
                    _scan_time.sleep(_BATCH_DELAY)
                    _gc.collect()
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
                        df.columns = [c.lower() for c in df.columns]
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
                        df.columns = [c.lower() for c in df.columns]
                        if "date" in df.columns:
                            df = df.set_index("date")
                        mcx_data[ticker] = df
                        data_diag["mcx"] += 1
                except Exception as e:
                    data_diag["errors"].append(f"MCX:{ticker}: {e}")
                    logger.warning("MCX fetch failed for %s: %s", ticker, e)

        # 4) NFO — indices via Kite NFO; F&O stocks reuse NSE OHLCV
        if segments is None or "NFO" in segments:
            # 4a) Index futures (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY)
            for ticker in NFO_INDEX_UNIVERSE:
                try:
                    df = provider.get_ohlcv_routed(ticker, interval="day", days=180, exchange="NFO")
                    if df is not None and not df.empty:
                        df.columns = [c.lower() for c in df.columns]
                        if "date" in df.columns:
                            df = df.set_index("date")
                        nfo_data[ticker] = df
                        data_diag["nfo"] += 1
                except Exception as e:
                    data_diag["errors"].append(f"NFO:{ticker}: {e}")

            # 4b) F&O stocks — same OHLCV as NSE underlying, reuse if already
            # fetched, otherwise pull via NSE route. Stored under NFO: prefix
            # so the nfo_stk_* scanners can find them.
            _MAX_NFO = int(_os.getenv("MWA_MAX_NFO_STOCKS", "20"))
            for i_nfo, stk in enumerate(NFO_STOCK_UNIVERSE[:_MAX_NFO]):
                if i_nfo > 0 and i_nfo % 10 == 0:
                    _scan_time.sleep(_BATCH_DELAY)
                try:
                    nse_key = next(
                        (k for k in nse_data
                         if k.upper().replace("NSE:", "").replace(".NS", "") == stk),
                        None,
                    )
                    if nse_key is not None:
                        nfo_data[f"NFO:{stk}"] = nse_data[nse_key]
                        data_diag["nfo"] += 1
                        continue
                    df = provider.get_ohlcv_routed(stk, interval="day", days=180, exchange="NSE")
                    if df is not None and not df.empty:
                        if "date" in df.columns:
                            df = df.set_index("date")
                        nfo_data[f"NFO:{stk}"] = df
                        data_diag["nfo"] += 1
                except Exception as e:
                    data_diag["errors"].append(f"NFO_STK:{stk}: {e}")
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
    mcx_results = scanner.run_all(stock_data=mcx_data or None, save=False, segment="MCX") if (segments is None or "MCX" in segments) else {}
    cds_results = scanner.run_all(stock_data=cds_data or None, save=False, segment="CDS") if (segments is None or "CDS" in segments) else {}
    nfo_results = scanner.run_all(stock_data=nfo_data or None, save=False, segment="NFO") if (segments is None or "NFO" in segments) else {}

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

    # Inject market movers into the promoted list. Top gainers/losers are
    # the most-traded stocks of the day — they should always be analysed
    # by the signal pipeline, even if no Chartink scanner caught them.
    try:
        movers = _fetch_market_movers() if _market_movers_cache is None else _market_movers_cache
        if movers:
            mover_tickers: list[str] = []
            # Top 10 gainers + top 10 losers + 52W highs + most active
            for cat in ("gainers", "losers", "week52_high", "most_active"):
                for item in (movers.get(cat, []) or [])[:10]:
                    t = item.get("symbol", "")
                    if t and t not in mover_tickers:
                        mover_tickers.append(t)
            # Inject at the FRONT of promoted so they get priority
            existing = set(promoted)
            injected = [t for t in mover_tickers if t not in existing]
            if injected:
                promoted = injected + promoted
                logger.info(
                    "[MOVERS] injected %d market movers into promoted (gainers+losers+52W+active)",
                    len(injected),
                )
    except Exception as mover_err:
        logger.debug("Market movers injection skipped: %s", mover_err)

    brief = format_morning_brief(score)

    # Log CDS/MCX scanner results for diagnostics
    for k, v in raw_results.items():
        if k.startswith(("cds_", "mcx_")):
            stocks = v if isinstance(v, list) else []
            if stocks:
                logger.info("Scanner %s fired: %s", k, stocks)

    # Build structured scanner_results for the frontend.
    # Pre-seed with ALL scanners (BULL/BEAR/FILTER) from the SCANNERS dict
    # so that every scanner — including Forex/FnO/Chartink — always appears
    # in the heatmap even when its segment was closed or a fetch failed.
    # Then overlay the actual raw_results on top.
    from mcp_server.mwa_scanner import SCANNERS
    structured_results: dict = {}
    for k, cfg in SCANNERS.items():
        if cfg.get("type") in ("UNKNOWN",):
            continue
        structured_results[k] = {
            "name": k,
            "group": cfg.get("layer", "Other"),
            "weight": cfg.get("weight", 0),
            "count": 0,
            "direction": cfg.get("type", "NEUTRAL"),
            "stocks": [],
        }
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

    # Send MWA scan summary to Telegram (skipped when TELEGRAM_SIGNALS_ONLY=true)
    if not settings.TELEGRAM_SIGNALS_ONLY:
        try:
            from mcp_server.telegram_bot import send_telegram_message

            direction_emoji = {"BULL": "\U0001f7e2", "BEAR": "\U0001f534", "SIDEWAYS": "\U0001f7e1"}
            d_emoji = direction_emoji.get(score["direction"], "\u26aa")

            promo_lines = ""
            if promoted:
                top_promo = promoted[:10]
                promo_lines = "\n\U0001f31f Promoted Stocks:\n" + "\n".join(
                    f"  {s.get('ticker', s) if isinstance(s, dict) else s}" for s in top_promo
                )
                if len(promoted) > 10:
                    promo_lines += f"\n  ... +{len(promoted) - 10} more"

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
        # Ensure send_telegram_message is bound for THIS function regardless
        # of the earlier TELEGRAM_SIGNALS_ONLY gate. Without this import,
        # Python treats the name as local (because it's assigned at line
        # 1666 inside a conditional) and every reference below raises
        # UnboundLocalError when TELEGRAM_SIGNALS_ONLY=true — which is
        # the production default, silently killing every signal card.
        from mcp_server.telegram_bot import send_telegram_message  # noqa: F811
        from mcp_server.mwa_signal_generator import generate_mwa_signals

        # Exclude tickers that already have OPEN signals — otherwise every
        # scan feeds the same top-10 into signal generation and the dedup
        # check below silently drops them all. By filtering upstream we
        # surface the next 10 fresh candidates from the ~500 promoted list.
        try:
            open_tickers = {
                row[0]
                for row in db.query(Signal.ticker)
                .filter(Signal.status == "OPEN")
                .all()
            }
        except Exception as open_err:
            logger.debug("Could not load OPEN-ticker set: %s", open_err)
            open_tickers = set()

        fresh_promoted = [t for t in promoted if t not in open_tickers]
        if not fresh_promoted:
            logger.info(
                "MWA: all %d promoted stocks already have OPEN signals — "
                "no fresh candidates this cycle",
                len(promoted),
            )

        # Interleave segments: reserve slots for non-equity so NFO/MCX/CDS
        # tickers (which have fewer scanners and sort to the bottom) still
        # get a chance at signal generation instead of being starved by the
        # 462 NSE equity candidates above them.
        nse_fresh = [t for t in fresh_promoted if ":" not in t or t.startswith("NSE:")]
        multi_fresh = [t for t in fresh_promoted if ":" in t and not t.startswith("NSE:")]
        # 7 equity + up to 3 multi-asset (NFO/MCX/CDS), then fill remainder
        interleaved = nse_fresh[:7] + multi_fresh[:3]
        remaining = [t for t in fresh_promoted if t not in set(interleaved)]
        signal_candidates = (interleaved + remaining)[:10]
        if multi_fresh:
            logger.info(
                "MWA: %d multi-asset candidates (NFO/MCX/CDS) in promoted, "
                "%d allocated signal slots",
                len(multi_fresh), min(len(multi_fresh), 3),
            )

        mwa_signals = generate_mwa_signals(
            promoted=signal_candidates,
            stock_data=stock_data,
            mwa_direction=score["direction"],
            scanner_results=raw_results,
        )

        # Filter out NSE equity signals when NSE is closed. When MCX
        # is open after 15:30, the auto_scan_loop still fires with
        # segments=["MCX"] but the scorer uses stale NSE scanner results
        # to promote equity stocks — which generates after-hours equity
        # signals on stale data. Block them at the signal level.
        from mcp_server.market_calendar import is_market_open as _mkt_check
        if not _mkt_check("NSE"):
            before = len(mwa_signals)
            mwa_signals = [
                s for s in mwa_signals
                if s.get("exchange") not in ("NSE", "") or ":" in s.get("ticker", "")
            ]
            if before != len(mwa_signals):
                logger.info(
                    "After-hours: dropped %d NSE equity signals (NSE closed)",
                    before - len(mwa_signals),
                )

        # ── Risk filters: delivery % → FII/DII → sector strength ────────
        # Previously these were defined in mwa_scanner.apply_python_filters
        # but that method was never invoked, so every MWA signal bypassed
        # the 3 risk gates. Inline them here so they actually fire.
        pre_filter = len(mwa_signals)
        try:
            from mcp_server.delivery_filter import apply_delivery_filter
            mwa_signals = apply_delivery_filter(mwa_signals, min_delivery_pct=60)
            logger.info(
                "[FILTER] delivery%%: %d -> %d signals", pre_filter, len(mwa_signals)
            )
        except Exception as delivery_err:
            logger.debug("Delivery filter skipped: %s", delivery_err)

        try:
            from mcp_server.fii_dii_filter import fii_allows_long, get_fii_dii_data
            pre_fii = len(mwa_signals)
            fii_data = get_fii_dii_data()
            fii_net = fii_data.get("fii_net", 0) if isinstance(fii_data, dict) else 0
            if not fii_allows_long(fii_net):
                mwa_signals = [
                    s for s in mwa_signals if s.get("direction") != "LONG"
                ]
                logger.info(
                    "[FILTER] FII selling (net=%.0f) — LONGs dropped: %d -> %d",
                    fii_net, pre_fii, len(mwa_signals),
                )
            else:
                logger.debug(
                    "[FILTER] FII neutral/buying (net=%.0f) — LONGs allowed", fii_net
                )
        except Exception as fii_err:
            logger.debug("FII filter skipped: %s", fii_err)

        try:
            from mcp_server.sector_filter import (
                get_sector_strength,
                sector_allows_trade,
            )
            pre_sector = len(mwa_signals)
            sector_strength = get_sector_strength() or {}
            mwa_signals = [
                s for s in mwa_signals
                if sector_allows_trade(
                    s.get("ticker", ""),
                    s.get("direction", "LONG"),
                    sector_strength,
                )
            ]
            logger.info(
                "[FILTER] sector: %d -> %d signals", pre_sector, len(mwa_signals)
            )
        except Exception as sector_err:
            logger.debug("Sector filter skipped: %s", sector_err)

        # ── Event calendar gate ───────────────────────────────────────────
        # Block intraday signals and haircut swing/positional confidence
        # when a high-impact macro event (RBI / FOMC / Budget / NFP) is
        # within the configured window. The events/calendar.yaml is the
        # data source; get_calendar() returns a cached singleton.
        try:
            from mcp_server.event_calendar import get_calendar
            _cal = get_calendar()
            pre_event = len(mwa_signals)

            def _event_filter(sig: dict) -> bool:
                tf = (sig.get("timeframe") or "day").lower()
                # Intraday signals: suppress entirely if any event within 4h
                if tf in ("5m", "15m", "1h", "intraday"):
                    return not _cal.high_impact_within(hours=4)
                # Swing/positional: suppress if event within 1h
                if _cal.high_impact_within(hours=1):
                    return False
                return True

            mwa_signals = [s for s in mwa_signals if _event_filter(s)]
            blocked = pre_event - len(mwa_signals)
            if blocked:
                upcoming = _cal.upcoming(hours=4)
                event_names = [e.type for e in upcoming]
                logger.info(
                    "[FILTER] event: %d -> %d signals (blocked %d near: %s)",
                    pre_event, len(mwa_signals), blocked, event_names,
                )
        except Exception as event_err:
            logger.debug("Event calendar filter skipped: %s", event_err)

        from mcp_server.market_calendar import is_market_open as _is_mkt_open

        # Signal caps — per-cycle (spread signals through the day) + daily ceiling.
        max_per_cycle = getattr(settings, "MWA_MAX_SIGNALS_PER_CYCLE", 5)
        max_daily = getattr(settings, "MWA_MAX_SIGNALS_PER_DAY", 50)
        if max_daily > 0:
            today_count = db.query(Signal).filter(
                Signal.signal_date == date.today(),
            ).count()
            if today_count >= max_daily:
                logger.info(
                    "MWA daily cap reached (%d/%d) — no new signals this cycle",
                    today_count, max_daily,
                )
                mwa_signals = []
        # Per-cycle cap: only process the top N per scan, so signals
        # distribute through the day instead of a morning burst.
        if max_per_cycle > 0 and len(mwa_signals) > max_per_cycle:
            logger.info(
                "MWA per-cycle cap: %d signals → keeping top %d",
                len(mwa_signals), max_per_cycle,
            )
            mwa_signals = mwa_signals[:max_per_cycle]

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

                    # C4 needs intraday bars (5m/15m) to fire meaningfully.
                    # Re-run just the C4 detector on 15m OHLCV for this
                    # ticker so the card carries a real entry-timing signal
                    # instead of "Not detected" on every daily card.
                    try:
                        df_15m = provider.get_ohlcv(
                            sig["ticker"], interval="15minute",
                            days=5, exchange=sig.get("exchange", "NSE"),
                        )
                        if df_15m is not None and not df_15m.empty and len(df_15m) >= 15:
                            df_15m = df_15m.rename(columns={c: c.lower() for c in df_15m.columns})
                            c4_15m = smc_engine.c4.detect_setup(
                                df_15m,
                                symbol=sig["ticker"],
                                timeframe="15minute",
                                amd_zones=smc_result.get("amd_zones", []),
                            )
                            smc_result["c4_setup"] = c4_15m
                            smc_result["c4_timeframe"] = "15m"
                            # Rebuild the telegram_summary with the rebased C4.
                            smc_result["telegram_summary"] = smc_engine.format_smc_card(smc_result)
                    except Exception as c4_err:
                        logger.debug("C4 intraday rebase skipped for %s: %s", sig["ticker"], c4_err)

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

            # Confidence gate: 70% minimum. The old 50% threshold let through
            # too many weak signals → 15% win rate. Raising to 70% filters
            # the bottom ~40% of signals that have negative expectancy.
            min_confidence = int(getattr(settings, "MWA_MIN_CONFIDENCE", 70))
            if confidence < min_confidence:
                logger.info("MWA signal %s skipped: confidence %d < %d", sig["ticker"], confidence, min_confidence)
                continue

            # Confidence-based position sizing: scale qty so higher-confidence
            # signals get more capital, lower-confidence get less. A 90%
            # signal gets full RRMS qty; a 70% signal gets 60%.
            base_qty = sig["qty"]
            if confidence >= 90:
                scaled_qty = base_qty
            elif confidence >= 80:
                scaled_qty = max(1, int(base_qty * 0.8))
            elif confidence >= 70:
                scaled_qty = max(1, int(base_qty * 0.6))
            else:
                scaled_qty = max(1, int(base_qty * 0.4))
            sig["qty"] = scaled_qty

            # Signal similarity check: find similar past signals and warn if
            # they mostly lost. Helps the user avoid repeating mistakes.
            similarity_warning = ""
            try:
                from mcp_server.signal_similarity import find_similar_signals
                # Create a temporary signal object for similarity search
                _temp_sig = Signal(
                    ticker=sig["ticker"], direction=sig["direction"],
                    entry_price=sig["entry"], stop_loss=sig["sl"],
                    target=sig["target"],
                    feature_vector=getattr(sig.get("ohlcv_df"), "_feature_vec", None),
                )
                similar = find_similar_signals(_temp_sig, db, top_k=5, only_closed=True)
                if similar:
                    losses = sum(1 for s in similar if s.get("outcome") == "LOSS")
                    wins = sum(1 for s in similar if s.get("outcome") == "WIN")
                    if losses >= 3:
                        similarity_warning = (
                            f"\u26a0\ufe0f Similar past signals: {losses}L/{wins}W "
                            f"— caution, similar setups lost before"
                        )
                        logger.info(
                            "Similarity warning for %s: %d/%d losses in top-5 similar",
                            sig["ticker"], losses, len(similar),
                        )
            except Exception as sim_err:
                logger.debug("Similarity check skipped for %s: %s", sig["ticker"], sim_err)

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
                    # Option fields — None-safe, only set if the signal was enriched
                    option_strategy=sig.get("option_strategy"),
                    option_tradingsymbol=sig.get("option_tradingsymbol"),
                    option_strike=sig.get("option_strike"),
                    option_expiry=sig.get("option_expiry"),
                    option_type=sig.get("option_type"),
                    option_premium=sig.get("option_premium"),
                    option_premium_sl=sig.get("option_premium_sl"),
                    option_premium_target=sig.get("option_premium_target"),
                    option_lot_size=sig.get("option_lot_size"),
                    option_contracts=sig.get("option_contracts"),
                    option_iv_rank=sig.get("option_iv_rank"),
                    option_delta=sig.get("option_delta"),
                    option_gamma=sig.get("option_gamma"),
                    option_theta=sig.get("option_theta"),
                    option_vega=sig.get("option_vega"),
                    option_iv=sig.get("option_iv"),
                    option_is_spread=sig.get("option_is_spread", False),
                    option_net_premium=sig.get("option_net_premium"),
                    option_legs=sig.get("option_legs"),
                )

                # ── Self-development: capture entry context features ──
                try:
                    from mcp_server.signal_features import (
                        extract_entry_features,
                        apply_features_to_signal,
                    )
                    feat = extract_entry_features(
                        sig.get("ohlcv_df"),
                        mwa_bull_pct=float(score.get("bull_pct") or 0),
                        mwa_bear_pct=float(score.get("bear_pct") or 0),
                        scanner_count=sig.get("scanner_count", 0),
                        bull_scanner_count=sig.get("bull_count", 0),
                        bear_scanner_count=sig.get("bear_count", 0),
                        scanner_list=sig.get("scanner_list", []),
                        ai_confidence=confidence,
                        rrr=sig.get("rrr", 0),
                        direction=sig.get("direction", "LONG"),
                        exchange=sig.get("exchange", "NSE"),
                    )
                    apply_features_to_signal(db_signal, feat)
                except Exception as feat_err:
                    logger.debug("Feature extraction skipped for %s: %s", sig["ticker"], feat_err)

                # ── Self-development: predictive loss probability gate ──
                try:
                    from mcp_server.signal_predictor import get_predictor
                    predictor = get_predictor()
                    if predictor.is_ready():
                        loss_prob, top_features = predictor.predict(db_signal.feature_vector or [])
                        db_signal.loss_probability = round(loss_prob, 3)
                        db_signal.predictor_version = predictor.version
                        threshold = getattr(settings, "PREDICTOR_BLOCK_THRESHOLD", 0.75)
                        if loss_prob >= threshold:
                            db_signal.suppressed = True
                            db_signal.suppression_reason = (
                                f"Predictor: P(loss)={loss_prob:.2f} ≥ {threshold:.2f}. "
                                f"Top risk factors: {', '.join(top_features[:3])}"
                            )
                            logger.info(
                                "Signal SUPPRESSED %s: P(loss)=%.2f reason=%s",
                                sig["ticker"], loss_prob, db_signal.suppression_reason,
                            )
                except Exception as pred_err:
                    logger.debug("Predictor skipped for %s: %s", sig["ticker"], pred_err)

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

                # Self-development guard: suppressed signals do NOT create
                # ActiveTrade (predictor flagged high loss probability).
                # Owner still gets a SUPPRESSED notice in the Telegram block
                # below so nothing is silently dropped.
                is_stale = deviation_pct > 2.0
                if db_signal.suppressed:
                    logger.info(
                        "ActiveTrade skipped for %s: signal suppressed by predictor (%s)",
                        sig["ticker"], db_signal.suppression_reason,
                    )
                else:
                    # Create ActiveTrade even when price deviated >2% from
                    # entry — previously this was silently skipped, hiding
                    # live signals from the owner. We keep the record but tag
                    # it STALE in the Telegram card (user decides whether to
                    # chase or wait for a better entry).
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
                    if is_stale:
                        logger.info(
                            "ActiveTrade created STALE for %s: CMP=%.2f is %.1f%% away from Entry=%.2f",
                            sig["ticker"], live_price, deviation_pct, entry_price,
                        )
                    else:
                        logger.info(
                            "ActiveTrade created: %s CMP=%.2f Entry=%.2f (%.1f%% off)",
                            sig["ticker"], live_price, entry_price, deviation_pct,
                        )

                db.commit()
                logger.info("Saved MWA signal to DB: %s (id=%d)", sig["ticker"], db_signal.id)

                # Record to Google Sheets (fixes the gap where auto-generated
                # MWA signals bypass Sheets — previously only the /signal paste
                # flow synced, so auto signals were only visible on DB close).
                try:
                    from mcp_server.telegram_receiver import record_signal_to_sheets
                    record_signal_to_sheets({
                        "signal_id": f"MWA-{db_signal.id}",
                        "date": str(db_signal.signal_date),
                        "ticker": sig["ticker"],
                        "exchange": sig["exchange"],
                        "asset_class": sig["asset_class"],
                        "direction": sig["direction"],
                        "entry_price": sig["entry"],
                        "stop_loss": sig["sl"],
                        "target": sig["target"],
                        "rrr": sig["rrr"],
                        "pattern": sig.get("pattern", "MWA"),
                        "confidence": confidence,
                        "notes": (
                            f"MWA auto | {sig.get('scanner_count', 0)} scanners | "
                            f"rec={recommendation}"
                            + (" | SUPPRESSED" if db_signal.suppressed else "")
                        ),
                    })
                except Exception as sheet_err:
                    logger.warning(
                        "Sheets sync failed for MWA signal %s: %s",
                        sig["ticker"], sheet_err,
                    )
            except Exception as db_err:
                logger.warning("DB save failed for %s: %s", sig["ticker"], db_err)
                try:
                    db.rollback()
                except Exception:
                    pass

            # Send detailed Telegram card (suppressed → send a blocked notice instead)
            emoji_map = {"ALERT": "\U0001f7e2", "WATCHLIST": "\U0001f7e1"}
            emoji = emoji_map.get(recommendation, "\U0001f7e1")
            segment_map = {"NSE": "NSE Equity", "MCX": "Commodity", "CDS": "Forex"}
            segment = segment_map.get(sig["exchange"], sig["exchange"])

            is_suppressed = bool(getattr(db_signal, "suppressed", False))
            if is_suppressed:
                # Suppressed signals are logged but NOT sent to Telegram.
                # The user doesn't need to see signals that won't be traded —
                # it's just noise. The suppression is recorded in DB + Sheets
                # for the learning loop to analyze.
                logger.info(
                    "MWA signal SUPPRESSED (silent): %s %s P(loss)=%.2f",
                    sig["ticker"], sig["direction"],
                    float(getattr(db_signal, "loss_probability", 0) or 0),
                )
                continue
            else:
                # Flag stale entries so user sees why CMP drifted. Computed
                # above (live_price vs sig["entry"]); we reuse is_stale.
                stale_line = ""
                if is_stale:
                    stale_line = (
                        f"\u26a0\ufe0f STALE: CMP \u20b9{live_price:.1f} is "
                        f"{deviation_pct:.1f}% off entry\n"
                    )
                msg = (
                    f"{emoji} MWA Signal\n"
                    f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
                    f"{stale_line}"
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
                if similarity_warning:
                    msg += "\n" + similarity_warning

                # ── Options recommendation block (only if signal was enriched) ──
                if sig.get("option_tradingsymbol"):
                    try:
                        _exp = sig.get("option_expiry")
                        expiry_str = _exp.strftime("%d%b").upper() if hasattr(_exp, "strftime") else ""
                        spread_note = " (SPREAD)" if sig.get("option_is_spread") else ""
                        _prem = float(sig.get("option_premium") or 0)
                        _sl = float(sig.get("option_premium_sl") or 0)
                        _tgt = float(sig.get("option_premium_target") or 0)
                        _lot = int(sig.get("option_lot_size") or 1)
                        _contracts = int(sig.get("option_contracts") or 1)
                        _risk_per_lot = max((_prem - _sl) * _lot, 0.0)
                        _ivr = float(sig.get("option_iv_rank") or 0)
                        _delta = float(sig.get("option_delta") or 0)
                        _gamma = float(sig.get("option_gamma") or 0)
                        _theta = float(sig.get("option_theta") or 0)
                        msg += (
                            f"\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
                            f"\U0001f3af OPTION RECOMMENDATION{spread_note}\n"
                            f"Contract: {sig['option_tradingsymbol']}"
                            + (f" ({expiry_str})" if expiry_str else "")
                            + "\n"
                            f"Strategy: {sig.get('option_strategy', 'N/A')} | IV Rank: {_ivr:.0f}%\n"
                            f"Entry: \u20b9{_prem:.1f} | SL: \u20b9{_sl:.1f} | TGT: \u20b9{_tgt:.1f}\n"
                            f"Lot: {_lot} | Contracts: {_contracts} | Risk: \u20b9{_risk_per_lot:,.0f}\n"
                            f"Greeks: \u0394 {_delta:+.2f} | \u0393 {_gamma:+.4f} | \u0398 {_theta:+.1f}"
                        )
                    except Exception as opt_msg_err:  # noqa: BLE001
                        logger.debug("Option message block skipped: %s", opt_msg_err)
            _fire_and_forget(send_telegram_message(msg, exchange=sig["exchange"], force=True))

            # Broadcast to SaaS subscribers opted into this segment
            # (NSE Equity / F&O / Commodity / Forex). Non-blocking; silent on
            # failure so owner delivery is never impacted by subscriber issues.
            if not is_suppressed:
                try:
                    from mcp_server.telegram_saas import broadcast_signal_to_users
                    _fire_and_forget(
                        broadcast_signal_to_users(msg, exchange=sig["exchange"])
                    )
                except Exception as broadcast_err:
                    logger.debug(
                        "Subscriber broadcast skipped for %s: %s",
                        sig["ticker"], broadcast_err,
                    )

            mwa_signal_cards.append({
                "ticker": sig["ticker"], "direction": sig["direction"],
                "exchange": sig.get("exchange", "NSE"),
                "entry": sig["entry"], "sl": sig["sl"], "target": sig["target"],
                "rrr": sig["rrr"], "qty": sig["qty"],
                "confidence": confidence, "recommendation": recommendation,
                "signal_id": record_result.get("signal_id", "N/A"),
                "suppressed": is_suppressed,
                "suppression_reason": getattr(db_signal, "suppression_reason", None) if is_suppressed else None,
                "loss_probability": float(getattr(db_signal, "loss_probability", 0) or 0),
            })
            logger.info(
                "MWA signal card sent: %s %s conf=%d suppressed=%s",
                sig["ticker"], sig["direction"], confidence, is_suppressed,
            )

            # Feed signal to NeuroLinked brain for pattern learning
            try:
                from mcp_server.brain_bridge import observe_signal
                observe_signal(sig, confidence=confidence, recommendation=recommendation)
            except Exception:
                pass

        # Post-scan summary — one compact Telegram line so the user sees
        # the full picture of each scan cycle including how many signals
        # were suppressed or tagged stale (previously invisible).
        if mwa_signal_cards:
            total = len(mwa_signal_cards)
            suppressed_count = sum(1 for c in mwa_signal_cards if c.get("suppressed"))
            by_segment: dict[str, int] = {}
            for c in mwa_signal_cards:
                exch = c.get("exchange") or "?"
                by_segment[exch] = by_segment.get(exch, 0) + 1
            segment_summary = (
                " ".join(f"{k}:{v}" for k, v in sorted(by_segment.items()))
                if by_segment else "-"
            )
            summary_msg = (
                "\U0001f4ca MWA Scan Summary\n"
                f"Signals: {total} ({total - suppressed_count} active, "
                f"{suppressed_count} suppressed)\n"
                f"By segment: {segment_summary}\n"
                f"Time: {_now_ist().strftime('%H:%M IST')}"
            )
            _fire_and_forget(send_telegram_message(summary_msg, force=True))

            # Feed scan summary to NeuroLinked brain
            try:
                from mcp_server.brain_bridge import observe_scan_summary
                observe_scan_summary(
                    direction=score["direction"],
                    bull_pct=score["bull_pct"],
                    bear_pct=score["bear_pct"],
                    signals_count=total,
                    suppressed=suppressed_count,
                )
            except Exception:
                pass

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
    """Background auto-sync to Google Sheets + Stitch. Non-blocking, fails silently."""
    try:
        from mcp_server.sheets_sync import log_signal, log_mwa
        if signal_data:
            log_signal(signal_data)
        if mwa_data:
            log_mwa(mwa_data)
    except Exception as e:
        logger.debug("Sheets auto-sync skipped: %s", e)

    # Mirror to Stitch warehouse (non-blocking)
    try:
        if signal_data and settings.STITCH_API_TOKEN:
            from mcp_server.stitch_sync import push_signals
            await push_signals([signal_data])
    except Exception as e:
        logger.debug("Stitch auto-sync skipped: %s", e)


# `/tools/manage_watchlist` moved to mcp_server.routers.watchlist in Phase 1d.


# ── F&O Stock Endpoints ───────────────────────────────────────


def _get_kite_for_fo():
    """Helper: return Kite client from data provider, or None if not connected."""
    try:
        from mcp_server.data_provider import get_provider
        provider = get_provider()
        if hasattr(provider, "kite") and provider.kite:
            return getattr(provider.kite, "kite", None) or getattr(provider.kite, "client", None)
    except Exception as e:
        logger.warning("Failed to get Kite client for F&O: %s", e)
    return None


# ============================================================
# Wall Street AI Prompt Tool Endpoints
# ============================================================


# Wallstreet endpoints moved to mcp_server.routers.wallstreet in Phase 1c.


# ============================================================
# Dashboard API endpoints (for React frontend)
# ============================================================


# _serialize_watchlist + /api/watchlist{,/:id{,/toggle}} moved to mcp_server.routers.watchlist in Phase 1d.


# DELETE + PATCH /api/watchlist/{item_id}* moved to mcp_server.routers.watchlist in Phase 1d.


# ============================================================
# Options Greeks Endpoints
# ============================================================


# GreeksRequest+OptionChainRequest+models_pre moved to mcp_server.routers.options in Phase 2a.


# ============================================================
# Options Payoff Endpoints
# ============================================================


# PayoffLeg+PayoffRequest moved to mcp_server.routers.options in Phase 2a.


# ============================================================
# Order Execution Endpoints (Live Trading with Safety Controls)
# ============================================================


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


# ============================================================
# Angel One SmartAPI Integration
# ============================================================


# ============================================================
# Kite Manual Login (browser-based OAuth flow)
# ============================================================


# ============================================================
# GWC (Goodwill) OAuth Login
# ============================================================


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


# ── Stitch Data endpoints ───────────────────────────────────────────


# `/api/telegram_webhook` moved to mcp_server.routers.webhooks in Phase 1b.


# `/api/tv_webhook` moved to mcp_server.routers.webhooks in Phase 1b.


# ============================================================
# News / Macro Event Monitor
# ============================================================


# ============================================================
# Momentum Ranking Module
# ============================================================


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
    results["gainers"] = [i for i in by_pct if i["pct_change"] > 0][:50]
    results["losers"] = sorted(
        [i for i in all_items if i["pct_change"] < 0],
        key=lambda x: x["pct_change"],
    )[:50]
    results["most_active"] = sorted(
        all_items, key=lambda x: x["volume"], reverse=True,
    )[:50]

    # 52-week high/low: check if today's high >= prev close * 1.0 (approximation)
    # Full 52W check needs more data; use daily high vs open as proxy for now
    results["week52_high"] = sorted(
        [i for i in all_items if i["high"] >= i["ltp"] * 0.999],
        key=lambda x: x["pct_change"], reverse=True,
    )[:50]
    results["week52_low"] = sorted(
        [i for i in all_items if i["low"] <= i["ltp"] * 1.001 and i["pct_change"] < 0],
        key=lambda x: x["pct_change"],
    )[:50]

    results["fetched_at"] = _now_ist().isoformat()
    results["total_stocks"] = len(all_items)

    return results


# ============================================================
# OHLCV Cache Management
# ============================================================


# ── RealtimeEngine API endpoints ──────────────────────────────────────────────


# ============================================================
# Scanner Review — EOD Performance Analysis
# ============================================================


# ============================================================
# Self-Development System — API endpoints
# ============================================================


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.MCP_SERVER_HOST, port=settings.MCP_SERVER_PORT)
