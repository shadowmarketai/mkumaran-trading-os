"""Telegram bot for MKUMARAN Trading OS."""
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
        "/add NSE:TICKER [timeframe] [ltrp=X pivot=Y] \u2014 Add to watchlist\n"
        "/remove NSE:TICKER \u2014 Remove from watchlist\n"
        "/pause NSE:TICKER \u2014 Pause alerts\n"
        "/resume NSE:TICKER \u2014 Resume alerts\n"
        "/watchlist [tier] \u2014 Show watchlist\n"
        "/close NSE:TICKER \u2014 Log trade exit\n"
        "/status \u2014 System status"
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


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command."""
    db = SessionLocal()
    try:
        watchlist_count = db.query(Watchlist).filter(Watchlist.active == True).count()  # noqa: E712

        status = f"""\U0001f916 MKUMARAN Trading OS
\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501
Status    : \U0001f7e2 Online
Watchlist : {watchlist_count} active stocks
MCP Server: http://localhost:8001
Dashboard : http://localhost:3000"""

        await update.message.reply_text(status)

    except Exception as e:
        await update.message.reply_text(f"Status: \U0001f7e1 Degraded\nError: {e}")
    finally:
        db.close()


async def cmd_close(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /close NSE:TICKER -- log trade exit."""
    if not context.args:
        await update.message.reply_text("Usage: /close NSE:TICKER [exit_price] [reason]")
        return

    ticker = context.args[0].upper()
    if not ticker.startswith("NSE:"):
        ticker = f"NSE:{ticker}"

    await update.message.reply_text(f"\U0001f4dd Trade exit logged for {ticker}\n(Full implementation in Phase 3)")


async def send_telegram_message(text: str) -> None:
    """Send a message to the configured Telegram chat."""
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured -- skipping message")
        return

    try:
        from telegram import Bot
        bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
        await bot.send_message(
            chat_id=settings.TELEGRAM_CHAT_ID,
            text=text,
            parse_mode=None,
        )
        logger.info("Telegram message sent (%d chars)", len(text))
    except Exception as e:
        logger.error("Failed to send Telegram message: %s", e)


def create_bot_application() -> Application:
    """Create and configure the Telegram bot application."""
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set -- bot disabled")
        return None

    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("watchlist", cmd_watchlist))
    app.add_handler(CommandHandler("close", cmd_close))
    app.add_handler(CommandHandler("status", cmd_status))

    logger.info("Telegram bot configured with 8 command handlers")
    return app
