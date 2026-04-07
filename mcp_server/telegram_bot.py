"""Telegram bot for MKUMARAN Trading OS."""
import asyncio
import logging
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from mcp_server.config import settings
from mcp_server.db import SessionLocal
from mcp_server.models import Watchlist

logger = logging.getLogger(__name__)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    await update.message.reply_text(
        "\U0001f916 MKUMARAN Trading OS Bot\n\n"
        "Commands:\n"
        "/health \u2014 Full system health report\n"
        "/kitelogin \u2014 Get Kite login URL\n"
        "/gwclogin \u2014 Get GWC (Goodwill) login URL\n"
        "/add NSE:TICKER [timeframe] [ltrp=X pivot=Y] \u2014 Add to watchlist\n"
        "/remove NSE:TICKER \u2014 Remove from watchlist\n"
        "/pause NSE:TICKER \u2014 Pause alerts\n"
        "/resume NSE:TICKER \u2014 Resume alerts\n"
        "/watchlist [tier] \u2014 Show watchlist\n"
        "/close NSE:TICKER \u2014 Log trade exit\n"
        "/status \u2014 Alias for /health"
    )


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /add NSE:TICKER [timeframe] [ltrp=X pivot=Y]"""
    if not context.args:
        await update.message.reply_text("Usage: /add NSE:TICKER [timeframe] [ltrp=X] [pivot=Y]")
        return

    ticker = context.args[0].upper()
    if not ticker.startswith("NSE:"):
        ticker = f"NSE:{ticker}"

    timeframe = "day"
    ltrp = None
    pivot = None

    for arg in context.args[1:]:
        if arg in ("day", "week", "60minute", "15minute"):
            timeframe = arg
        elif arg.startswith("ltrp="):
            try:
                ltrp = float(arg.split("=")[1])
            except ValueError:
                pass
        elif arg.startswith("pivot="):
            try:
                pivot = float(arg.split("=")[1])
            except ValueError:
                pass

    db = SessionLocal()
    try:
        existing = db.query(Watchlist).filter(Watchlist.ticker == ticker).first()
        if existing:
            await update.message.reply_text(f"\u26a0\ufe0f {ticker} already in watchlist (Tier {existing.tier})")
            return

        item = Watchlist(
            ticker=ticker,
            timeframe=timeframe,
            tier=2,
            ltrp=ltrp,
            pivot_high=pivot,
            active=True,
            source="telegram",
            added_by="telegram",
        )
        db.add(item)
        db.commit()

        msg = f"\u2705 Added {ticker} to Tier 2 watchlist"
        if ltrp:
            msg += f"\nLTRP: \u20b9{ltrp:,.2f}"
        if pivot:
            msg += f"\nPivot: \u20b9{pivot:,.2f}"
        msg += f"\nTimeframe: {timeframe}"

        await update.message.reply_text(msg)

    except Exception as e:
        logger.error("Error adding %s: %s", ticker, e)
        await update.message.reply_text(f"\u274c Error: {e}")
    finally:
        db.close()


async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /remove NSE:TICKER"""
    if not context.args:
        await update.message.reply_text("Usage: /remove NSE:TICKER")
        return

    ticker = context.args[0].upper()
    if not ticker.startswith("NSE:"):
        ticker = f"NSE:{ticker}"

    db = SessionLocal()
    try:
        item = db.query(Watchlist).filter(Watchlist.ticker == ticker).first()
        if not item:
            await update.message.reply_text(f"\u26a0\ufe0f {ticker} not found in watchlist")
            return

        db.delete(item)
        db.commit()
        await update.message.reply_text(f"\U0001f5d1\ufe0f Removed {ticker} from watchlist")

    except Exception as e:
        logger.error("Error removing %s: %s", ticker, e)
        await update.message.reply_text(f"\u274c Error: {e}")
    finally:
        db.close()


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /pause NSE:TICKER"""
    if not context.args:
        await update.message.reply_text("Usage: /pause NSE:TICKER")
        return

    ticker = context.args[0].upper()
    if not ticker.startswith("NSE:"):
        ticker = f"NSE:{ticker}"

    db = SessionLocal()
    try:
        item = db.query(Watchlist).filter(Watchlist.ticker == ticker).first()
        if not item:
            await update.message.reply_text(f"\u26a0\ufe0f {ticker} not found")
            return

        item.active = False
        db.commit()
        await update.message.reply_text(f"\u23f8\ufe0f Paused alerts for {ticker}")

    except Exception as e:
        await update.message.reply_text(f"\u274c Error: {e}")
    finally:
        db.close()


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /resume NSE:TICKER"""
    if not context.args:
        await update.message.reply_text("Usage: /resume NSE:TICKER")
        return

    ticker = context.args[0].upper()
    if not ticker.startswith("NSE:"):
        ticker = f"NSE:{ticker}"

    db = SessionLocal()
    try:
        item = db.query(Watchlist).filter(Watchlist.ticker == ticker).first()
        if not item:
            await update.message.reply_text(f"\u26a0\ufe0f {ticker} not found")
            return

        item.active = True
        db.commit()
        await update.message.reply_text(f"\u25b6\ufe0f Resumed alerts for {ticker}")

    except Exception as e:
        await update.message.reply_text(f"\u274c Error: {e}")
    finally:
        db.close()


async def cmd_watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /watchlist [tier]"""
    tier_filter = None
    if context.args:
        try:
            tier_filter = int(context.args[0])
        except ValueError:
            pass

    db = SessionLocal()
    try:
        query = db.query(Watchlist)
        if tier_filter:
            query = query.filter(Watchlist.tier == tier_filter)

        items = query.order_by(Watchlist.tier, Watchlist.ticker).all()

        if not items:
            await update.message.reply_text("\U0001f4cb Watchlist is empty")
            return

        lines = [f"\U0001f4cb WATCHLIST ({len(items)} stocks)"]
        lines.append("\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501")

        current_tier = None
        for item in items:
            if item.tier != current_tier:
                current_tier = item.tier
                lines.append(f"\n\U0001f3f7\ufe0f Tier {current_tier}:")

            status = "\u2705" if item.active else "\u23f8\ufe0f"
            ltrp_str = f" LTRP:\u20b9{float(item.ltrp):,.0f}" if item.ltrp else ""
            lines.append(f"  {status} {item.ticker}{ltrp_str}")

        await update.message.reply_text("\n".join(lines))

    except Exception as e:
        await update.message.reply_text(f"\u274c Error: {e}")
    finally:
        db.close()


async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /health and /status commands — full system diagnostics."""
    try:
        from mcp_server.mcp_server import get_system_health
        h = get_system_health()

        # Status indicators
        server_icon = "\U0001f7e2" if h.get("server_ok") else "\U0001f534"
        db_icon = "\U0001f7e2" if h.get("db_ok") else "\U0001f534"
        kite_icon = "\U0001f7e2" if h.get("kite_connected") else "\U0001f534"
        gwc_icon = "\U0001f7e2" if h.get("gwc_connected") else "\U0001f534"

        # Market status line
        market_parts = []
        for ex in ("nse", "mcx", "cds"):
            ms = h.get(f"market_{ex}", "UNKNOWN")
            market_parts.append(f"{ex.upper()} {ms}")
        market_line = " | ".join(market_parts)

        # Kill switch
        ks_text = "ON \u26a0\ufe0f" if h.get("kill_switch") else "OFF"
        mode_text = "PAPER" if h.get("paper_mode") else "LIVE"

        # MWA info
        mwa_dir = h.get("mwa_direction", "N/A")
        mwa_bull = h.get("mwa_bull_pct", 0)
        mwa_bear = h.get("mwa_bear_pct", 0)

        # Issues
        issues = []
        if not h.get("kite_connected"):
            issues.append("\u2022 Kite not connected \u2014 use /kitelogin")
        if not h.get("gwc_connected"):
            issues.append("\u2022 GWC not connected \u2014 use /gwclogin")
        if h.get("kite_failed_today"):
            issues.append("\u2022 Kite data failed today (using yfinance fallback)")
        if h.get("kill_switch"):
            issues.append("\u2022 Kill switch is ACTIVE \u2014 orders blocked")
        if not h.get("db_ok"):
            issues.append("\u2022 Database connection failed")

        issues_block = ""
        if issues:
            issues_block = "\n\n\u26a0\ufe0f Issues Detected\n" + "\n".join(issues)

        msg = (
            f"\U0001f916 MKUMARAN Trading OS \u2014 Health Report\n"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            f"{server_icon} Server     : Online (uptime: {h.get('uptime', '?')})\n"
            f"{db_icon} Database   : {'Connected' if h.get('db_ok') else 'ERROR'}\n"
            f"{kite_icon} Kite       : {'Connected' if h.get('kite_connected') else 'Not connected'}\n"
            f"{gwc_icon} GWC        : {'Connected' if h.get('gwc_connected') else 'Not connected'}\n"
            f"\U0001f7e2 Market     : {market_line}\n"
            f"\n\U0001f4ca Trading Status\n"
            f"  Mode          : {mode_text}\n"
            f"  Open Signals  : {h.get('open_signals', 0)}\n"
            f"  Active Trades : {h.get('active_trades', 0)}\n"
            f"  Today Signals : {h.get('today_signals', 0)}\n"
            f"  Kill Switch   : {ks_text}\n"
            f"  Daily P&L     : {h.get('daily_pnl', 0)}\n"
            f"\n\U0001f4c8 Last MWA Scan\n"
            f"  Time      : {h.get('last_mwa_scan', 'N/A')}\n"
            f"  Direction : {mwa_dir}\n"
            f"  Bull/Bear : {mwa_bull}% / {mwa_bear}%"
            f"{issues_block}"
        )
        await update.message.reply_text(msg)

    except Exception as e:
        logger.error("Health command failed: %s", e)
        await update.message.reply_text(f"\U0001f534 Health check failed: {e}")


async def cmd_kitelogin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /kitelogin — send Kite login URL to user."""
    try:
        from mcp_server.kite_auth import get_kite_login_url
        url = get_kite_login_url()
        await update.message.reply_text(
            "\U0001f510 Kite Manual Login\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            "1. Open this URL in your browser:\n\n"
            f"{url}\n\n"
            "2. Complete Zerodha login + 2FA\n"
            "3. You'll see a success page when done\n"
            "4. Run /health to verify Kite is connected"
        )
    except Exception as e:
        await update.message.reply_text(f"\u274c Kite login URL failed: {e}")


async def cmd_gwclogin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /gwclogin — send GWC OAuth login URL to user."""
    try:
        if not settings.GWC_API_KEY:
            await update.message.reply_text(
                "\u26a0\ufe0f GWC_API_KEY not configured.\n"
                "Set GWC_API_KEY, GWC_API_SECRET, GWC_CLIENT_ID in Coolify env vars first."
            )
            return

        login_url = f"https://api.gwcindia.in/v1/login?api_key={settings.GWC_API_KEY}"
        await update.message.reply_text(
            "\U0001f510 GWC (Goodwill) Manual Login\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            "1. Open this URL in your browser:\n\n"
            f"{login_url}\n\n"
            "2. Complete Goodwill login + 2FA\n"
            "3. You'll be redirected to a success page\n"
            "4. Run /health to verify GWC is connected"
        )
    except Exception as e:
        await update.message.reply_text(f"\u274c GWC login URL failed: {e}")


async def cmd_close(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /close NSE:TICKER -- log trade exit."""
    if not context.args:
        await update.message.reply_text("Usage: /close NSE:TICKER [exit_price] [reason]")
        return

    ticker = context.args[0].upper()
    if not ticker.startswith("NSE:"):
        ticker = f"NSE:{ticker}"

    await update.message.reply_text(f"\U0001f4dd Trade exit logged for {ticker}\n(Full implementation in Phase 3)")


async def send_telegram_message(
    text: str,
    exchange: str = "NSE",
    force: bool = False,
) -> None:
    """Send a message to the configured Telegram chat.

    Uses direct httpx calls to the Telegram Bot HTTP API with explicit
    timeouts and retries. This is more reliable than constructing a
    ``telegram.Bot`` instance per call (which does a handshake + getMe
    and was prone to time out under scan load).

    Args:
        text: Message content.
        exchange: Exchange code for market hours check (NSE, MCX, CDS, etc.).
        force: If True, send regardless of market hours (for kill switch / system alerts).
    """
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured -- skipping message")
        return

    # Market hours gate — skip non-forced messages when market is closed
    if not force:
        from mcp_server.market_calendar import is_market_open
        if not is_market_open(exchange):
            from mcp_server.market_calendar import get_market_status
            status = get_market_status(exchange)
            logger.info(
                "Telegram SKIPPED (%s market %s): %.40s...",
                exchange, status.get("reason", "CLOSED"), text,
            )
            return

    # Telegram hard limit is 4096 chars; trim to be safe.
    if len(text) > 4000:
        text = text[:3990] + "…"

    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": settings.TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }

    # httpx is already a dependency (FastAPI). Use generous timeouts and retry
    # up to 3 times with exponential backoff to tolerate transient network hiccups.
    import httpx

    timeout = httpx.Timeout(connect=10.0, read=25.0, write=10.0, pool=10.0)
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload)
            if resp.status_code == 200 and resp.json().get("ok"):
                logger.info("Telegram message sent (%d chars)", len(text))
                return
            # 429 = rate-limited, 5xx = transient — retry
            if resp.status_code in (429, 500, 502, 503, 504):
                last_err = RuntimeError(
                    f"Telegram HTTP {resp.status_code}: {resp.text[:160]}"
                )
            else:
                logger.error(
                    "Telegram send failed (non-retryable HTTP %d): %s",
                    resp.status_code, resp.text[:200],
                )
                return
        except Exception as e:
            last_err = e
        if attempt < 2:
            await asyncio.sleep(1.5 * (2 ** attempt))
    logger.error("Failed to send Telegram message after 3 attempts: %s", last_err)


def create_bot_application() -> Application:
    """Create and configure the Telegram bot application."""
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set -- bot disabled")
        return None

    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("health", cmd_health))
    app.add_handler(CommandHandler("status", cmd_health))  # alias
    app.add_handler(CommandHandler("kitelogin", cmd_kitelogin))
    app.add_handler(CommandHandler("gwclogin", cmd_gwclogin))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("watchlist", cmd_watchlist))
    app.add_handler(CommandHandler("close", cmd_close))

    logger.info("Telegram bot configured with 11 command handlers")
    return app
