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
        "/analyze BUY TICKER @ PRICE SL PRICE TGT PRICE \u2014 Quick AI analysis\n"
        "/signal BUY TICKER @ PRICE SL PRICE TGT PRICE \u2014 Full pipeline\n"
        "\n\U0001f464 Account:\n"
        "/login email password \u2014 Link your account\n"
        "/segments \u2014 View/toggle trading segments\n"
        "/alerts on|off \u2014 Pause/resume signals\n"
        "/plan \u2014 View subscription\n"
        "/mystats \u2014 Your stats\n"
        "\n\U0001f511 BYOK API Keys:\n"
        "/setkey grok|kimi|openai|claude|gemini|deepseek KEY\n"
        "/mykeys \u2014 View saved keys\n"
        "/removekey provider \u2014 Remove a key\n"
        "\n\U0001f527 Admin:\n"
        "/health \u2014 System health\n"
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


async def cmd_dhantoken(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /dhantoken <JWT> — hot-swap Dhan access token at runtime.

    Decodes the JWT to validate it's a real Dhan token, then replaces the
    token on the live DhanSource instance — no redeploy needed.
    """
    if not context.args:
        await update.message.reply_text(
            "\U0001f510 Dhan Token Refresh\n"
            "\u2501" * 24 + "\n"
            "Usage: /dhantoken <paste JWT here>\n\n"
            "1. Go to web.dhan.co/index/profile\n"
            "2. Generate Access Token\n"
            "3. Copy the JWT and paste:\n"
            "   /dhantoken eyJ0eXAi..."
        )
        return
    token = context.args[0].strip()
    if not token.startswith("eyJ"):
        await update.message.reply_text("\u274c That doesn't look like a JWT. Paste the full token starting with eyJ...")
        return

    try:
        import base64, json as _json
        payload = _json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
        exp = payload.get("exp", 0)
        client_id = payload.get("dhanClientId", "?")
        from datetime import datetime, timezone
        expires = datetime.fromtimestamp(exp, tz=timezone.utc)
        hours_left = (exp - datetime.now(tz=timezone.utc).timestamp()) / 3600
    except Exception:
        expires = None
        hours_left = 0
        client_id = "?"

    try:
        from mcp_server.data_provider import get_provider
        from dhanhq import dhanhq
        provider = get_provider()
        provider.dhan.client = dhanhq(client_id, token)
        provider.dhan.logged_in = True
        provider._sources["dhan"] = True
        msg = (
            "\u2705 Dhan Token Refreshed\n"
            f"Client: {client_id}\n"
            f"Expires: {expires.strftime('%Y-%m-%d %H:%M UTC') if expires else '?'}\n"
            f"Valid for: {hours_left:.0f}h\n"
            "MCX/NFO/CDS data will use fresh token."
        )
    except Exception as e:
        msg = f"\u274c Dhan token swap failed: {e}"

    await update.message.reply_text(msg)


async def cmd_close(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /close NSE:TICKER -- log trade exit."""
    if not context.args:
        await update.message.reply_text("Usage: /close NSE:TICKER [exit_price] [reason]")
        return

    ticker = context.args[0].upper()
    if not ticker.startswith("NSE:"):
        ticker = f"NSE:{ticker}"

    await update.message.reply_text(f"\U0001f4dd Trade exit logged for {ticker}\n(Full implementation in Phase 3)")


async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /analyze — parse a signal from text and run AI analysis.

    Usage:
      /analyze BUY NSE:RELIANCE @ 2500 SL 2400 TGT 2800
      /analyze SELL MCX:GOLD 72000 SL 72500 TGT 71000
    """
    if not context.args:
        await update.message.reply_text(
            "\U0001f50d Signal Analyzer\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            "Send a signal to analyze:\n\n"
            "/analyze BUY NSE:RELIANCE @ 2500 SL 2400 TGT 2800\n"
            "/analyze SELL MCX:GOLD 72000 SL 72500 TGT 71000\n\n"
            "I'll run AI analysis with entry/SL/target validation, "
            "RRR check, and a confidence score."
        )
        return

    signal_text = " ".join(context.args)
    await update.message.reply_text("\u23f3 Analyzing signal...")

    # Parse the signal
    try:
        from mcp_server.telegram_receiver import parse_signal_message
        signal = parse_signal_message(signal_text)
    except Exception as e:
        await update.message.reply_text(f"\u274c Parse error: {e}")
        return

    if signal is None:
        await update.message.reply_text(
            "\u274c Could not parse signal. Use format:\n"
            "BUY NSE:TICKER @ PRICE SL PRICE TGT PRICE"
        )
        return

    # Basic validation
    issues = []
    if signal.entry_price <= 0:
        issues.append("\u2022 Entry price missing or invalid")
    if signal.stop_loss <= 0:
        issues.append("\u2022 Stop loss missing")
    if signal.target <= 0:
        issues.append("\u2022 Target missing")
    if signal.rrr < 1.0 and signal.rrr > 0:
        issues.append(f"\u2022 RRR too low ({signal.rrr:.1f}) \u2014 minimum 1:1 recommended")

    # Direction vs price sanity
    if signal.direction in ("BUY", "LONG"):
        if signal.stop_loss > 0 and signal.stop_loss >= signal.entry_price:
            issues.append("\u2022 SL above entry for BUY \u2014 check values")
        if signal.target > 0 and signal.target <= signal.entry_price:
            issues.append("\u2022 Target below entry for BUY \u2014 check values")
    elif signal.direction in ("SELL", "SHORT"):
        if signal.stop_loss > 0 and signal.stop_loss <= signal.entry_price:
            issues.append("\u2022 SL below entry for SELL \u2014 check values")
        if signal.target > 0 and signal.target >= signal.entry_price:
            issues.append("\u2022 Target above entry for SELL \u2014 check values")

    # Risk calculation
    risk_per_share = abs(signal.entry_price - signal.stop_loss) if signal.stop_loss > 0 else 0
    reward_per_share = abs(signal.target - signal.entry_price) if signal.target > 0 else 0
    risk_pct = (risk_per_share / signal.entry_price * 100) if signal.entry_price > 0 else 0

    # Build basic report
    dir_emoji = "\U0001f7e2" if signal.direction in ("BUY", "LONG") else "\U0001f534"
    rrr_emoji = "\u2705" if signal.rrr >= 2.0 else "\u26a0\ufe0f" if signal.rrr >= 1.0 else "\u274c"

    report = (
        f"\U0001f50d Signal Analysis\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"{dir_emoji} {signal.direction} {signal.ticker}\n"
        f"Entry: \u20b9{signal.entry_price:,.2f}\n"
        f"Stop Loss: \u20b9{signal.stop_loss:,.2f} ({risk_pct:.1f}% risk)\n"
        f"Target: \u20b9{signal.target:,.2f}\n"
        f"Risk/Share: \u20b9{risk_per_share:,.2f}\n"
        f"Reward/Share: \u20b9{reward_per_share:,.2f}\n"
        f"{rrr_emoji} RRR: {signal.rrr:.2f}\n"
    )

    if issues:
        report += "\n\u26a0\ufe0f Issues:\n" + "\n".join(issues) + "\n"

    # Run AI analysis via Grok/Kimi
    ai_analysis = ""
    try:
        from mcp_server.ai_provider import call_ai

        prompt = (
            f"Analyze this Indian stock market trading signal in 4-5 bullet points. "
            f"Be concise and actionable.\n\n"
            f"Signal: {signal.direction} {signal.ticker}\n"
            f"Entry: Rs.{signal.entry_price} | SL: Rs.{signal.stop_loss} | Target: Rs.{signal.target}\n"
            f"RRR: {signal.rrr}\n\n"
            f"Cover: 1) Is the RRR acceptable? 2) Key support/resistance near these levels "
            f"3) Risk assessment 4) Verdict: TAKE / SKIP / WAIT with brief reason"
        )

        ai_analysis = call_ai(prompt=prompt, max_tokens=300)
    except Exception as e:
        logger.warning("AI analysis failed for /analyze: %s", e)
        ai_analysis = "(AI analysis unavailable)"

    if ai_analysis:
        report += f"\n\U0001f916 AI Analysis:\n{ai_analysis}\n"

    # Verdict
    if not issues and signal.rrr >= 2.0:
        report += "\n\u2705 Verdict: LOOKS GOOD \u2014 RRR and levels check out"
    elif not issues and signal.rrr >= 1.0:
        report += "\n\u26a0\ufe0f Verdict: ACCEPTABLE \u2014 but RRR could be better"
    elif issues:
        report += "\n\u274c Verdict: FIX ISSUES before taking this trade"

    report += "\n\n\u26a0\ufe0f Not SEBI advice. Do your own research."

    await update.message.reply_text(report)


async def cmd_signal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /signal — full pipeline: parse → scan → AI debate → track.

    Usage:
      /signal BUY NSE:RELIANCE @ 2500 SL 2400 TGT 2800
      /signal SELL MCX:GOLD 72000 SL 72500 TGT 71000
      /signal BUY NIFTY 24500 SL 24300 TGT 24900
    """
    if not context.args:
        await update.message.reply_text(
            "\U0001f4e1 Signal Intake Pipeline\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            "Share a signal to analyze:\n\n"
            "/signal BUY NSE:RELIANCE @ 2500 SL 2400 TGT 2800\n"
            "/signal SELL MCX:GOLD 72000 SL 72500 TGT 71000\n\n"
            "Pipeline:\n"
            "1\ufe0f\u20e3 Parse signal\n"
            "2\ufe0f\u20e3 Run 40+ scanners on ticker\n"
            "3\ufe0f\u20e3 AI debate (Grok/Kimi)\n"
            "4\ufe0f\u20e3 Confidence score + verdict\n"
            "5\ufe0f\u20e3 Auto-track if >50% confidence"
        )
        return

    signal_text = " ".join(context.args)
    await update.message.reply_text("\u23f3 Processing signal through full pipeline...")

    # ── Step 1: Parse ──────────────────────────────────────────
    try:
        from mcp_server.telegram_receiver import parse_signal_message
        signal = parse_signal_message(signal_text)
    except Exception as e:
        await update.message.reply_text(f"\u274c Parse error: {e}")
        return

    if signal is None:
        await update.message.reply_text(
            "\u274c Could not parse signal.\n"
            "Format: BUY NSE:TICKER @ PRICE SL PRICE TGT PRICE"
        )
        return

    entry = signal.entry_price
    sl = signal.stop_loss
    tgt = signal.target
    ticker = signal.ticker
    direction = signal.direction
    exchange = signal.exchange

    if entry <= 0 or sl <= 0 or tgt <= 0:
        await update.message.reply_text(
            f"\u274c Missing prices.\n"
            f"Parsed: {direction} {ticker} Entry={entry} SL={sl} TGT={tgt}\n"
            f"Please include all three: entry, SL, target."
        )
        return

    risk = abs(entry - sl)
    reward = abs(tgt - entry)
    rrr = round(reward / risk, 2) if risk > 0 else 0

    dir_emoji = "\U0001f7e2" if direction in ("BUY", "LONG") else "\U0001f534"
    parsed_msg = (
        f"{dir_emoji} Signal Parsed\n"
        f"{direction} {ticker} ({exchange})\n"
        f"Entry: \u20b9{entry:,.2f} | SL: \u20b9{sl:,.2f} | TGT: \u20b9{tgt:,.2f}\n"
        f"RRR: {rrr:.2f}\n"
    )

    # ── Step 2: Run scanners ───────────────────────────────────
    scanner_report = ""
    matched_scanners = []
    scanner_count = 0

    try:
        from mcp_server.data_provider import get_provider
        from mcp_server.mwa_scanner import MWAScanner

        provider = get_provider()
        ticker_clean = ticker.replace("NSE:", "").replace("MCX:", "").replace("NFO:", "").replace("CDS:", "")

        # Fetch OHLCV
        df = provider.get_ohlcv_routed(ticker_clean, interval="day", days=180, exchange=exchange)

        if df is not None and not df.empty:
            # Run scanners against this single stock
            scanner = MWAScanner()
            stock_data = {ticker: df}
            results = scanner.run_all(stock_data=stock_data, save=False, segment=exchange)

            # Find which scanners fired for this ticker
            for scanner_name, scanner_data in results.items():
                stocks = scanner_data.get("stocks", [])
                if ticker_clean in stocks or ticker in stocks:
                    matched_scanners.append({
                        "name": scanner_name,
                        "group": scanner_data.get("group", ""),
                        "direction": scanner_data.get("direction", ""),
                    })

            scanner_count = len(matched_scanners)

            if matched_scanners:
                scanner_lines = []
                for s in matched_scanners[:10]:
                    s_dir = "\U0001f7e2" if s["direction"] == "BULL" else "\U0001f534" if s["direction"] == "BEAR" else "\u26aa"
                    scanner_lines.append(f"  {s_dir} {s['name']} ({s['group']})")
                scanner_report = (
                    f"\n\U0001f50d Scanner Analysis ({scanner_count} hit)\n"
                    + "\n".join(scanner_lines)
                )
                if len(matched_scanners) > 10:
                    scanner_report += f"\n  ... +{len(matched_scanners) - 10} more"
            else:
                scanner_report = "\n\U0001f50d Scanners: No matching patterns found"
        else:
            scanner_report = "\n\U0001f50d Scanners: Could not fetch data for analysis"
    except Exception as e:
        logger.warning("Scanner analysis failed for %s: %s", ticker, e)
        scanner_report = f"\n\U0001f50d Scanners: Analysis failed ({str(e)[:50]})"

    # ── Step 3: AI Debate ──────────────────────────────────────
    ai_confidence = 0
    ai_recommendation = "SKIP"
    ai_reasoning = ""
    debate_method = "none"

    try:
        # Try full debate validator
        from mcp_server.debate_validator import run_debate

        # Get MWA direction
        mwa_direction = "UNKNOWN"
        try:
            from mcp_server.db import SessionLocal
            from mcp_server.models import MWAScore
            db = SessionLocal()
            latest_mwa = db.query(MWAScore).order_by(MWAScore.score_date.desc()).first()
            if latest_mwa:
                mwa_direction = latest_mwa.direction or "UNKNOWN"
            db.close()
        except Exception:
            pass

        # Pre-confidence from scanner count
        pre_confidence = min(40 + scanner_count * 8, 85)

        confidence_boosts = []
        if scanner_count >= 3:
            confidence_boosts.append(f"{scanner_count} scanners aligned")
        if rrr >= 3.0:
            confidence_boosts.append(f"Strong RRR {rrr}")

        debate_result = run_debate(
            ticker=ticker_clean,
            direction=direction,
            pattern=signal.pattern or "External Signal",
            rrr=rrr,
            entry_price=entry,
            stop_loss=sl,
            target=tgt,
            mwa_direction=mwa_direction,
            scanner_count=scanner_count,
            tv_confirmed=False,
            sector_strength="NEUTRAL",
            fii_net=0,
            delivery_pct=0,
            confidence_boosts=confidence_boosts,
            pre_confidence=pre_confidence,
        )

        ai_confidence = debate_result.final_confidence
        ai_recommendation = debate_result.recommendation
        ai_reasoning = debate_result.reasoning
        debate_method = debate_result.method

    except Exception as e:
        logger.warning("AI debate failed for %s: %s", ticker, e)
        # Fallback: simple AI call
        try:
            from mcp_server.ai_provider import call_ai
            raw = call_ai(
                prompt=(
                    f"Score this Indian market signal 0-100 for quality.\n"
                    f"Signal: {direction} {ticker} Entry=Rs.{entry} SL=Rs.{sl} TGT=Rs.{tgt} RRR={rrr}\n"
                    f"Scanners matched: {scanner_count}\n"
                    f"Respond JSON: {{\"confidence\": N, \"recommendation\": \"ALERT|WATCHLIST|SKIP\", \"reasoning\": \"...\"}}"
                ),
                max_tokens=200,
            )
            import json
            if "{" in raw:
                parsed = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
                ai_confidence = parsed.get("confidence", 50)
                ai_recommendation = parsed.get("recommendation", "WATCHLIST")
                ai_reasoning = parsed.get("reasoning", "")
                debate_method = "single_pass"
        except Exception:
            ai_confidence = pre_confidence if scanner_count > 0 else 40
            ai_recommendation = "WATCHLIST"
            debate_method = "scanner_only"

    # ── Step 4: Build Telegram report ──────────────────────────
    conf_bar = "\u2588" * (ai_confidence // 10) + "\u2591" * (10 - ai_confidence // 10)

    # Build an explicit PASS/FAIL verdict so paste replies have a hard
    # header (not just a confidence number). Reasons help the user
    # understand why a signal failed without re-reading the whole card.
    verdict_reasons: list[str] = []
    if scanner_count == 0:
        verdict_reasons.append("no scanner match")
    if rrr and rrr < 1.5:
        verdict_reasons.append(f"RRR {rrr:.1f} < 1.5")
    if ai_recommendation == "BLOCKED":
        verdict_reasons.append("debate blocked")

    if ai_confidence >= 70 and not verdict_reasons:
        verdict_emoji = "\u2705"
        verdict_text = f"VALID — STRONG ({ai_confidence}%) — Execute"
    elif ai_confidence >= 50 and not verdict_reasons:
        verdict_emoji = "\U0001f7e1"
        verdict_text = f"VALID — MODERATE ({ai_confidence}%) — Consider"
    else:
        verdict_emoji = "\u274c"
        reason = " · ".join(verdict_reasons) if verdict_reasons else f"conf {ai_confidence}% < 50"
        verdict_text = f"INVALID — Skip (reason: {reason})"

    report = (
        f"\U0001f4e1 SIGNAL ANALYSIS\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"{parsed_msg}"
        f"{scanner_report}\n"
        f"\n\U0001f916 AI Confidence: {conf_bar} {ai_confidence}%\n"
        f"Method: {debate_method}\n"
        f"Recommendation: {ai_recommendation}\n"
    )

    if ai_reasoning:
        report += f"Reasoning: {ai_reasoning[:200]}\n"

    report += (
        f"\n{verdict_emoji} VERDICT: {verdict_text}\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
    )

    # ── Step 5: Auto-track if confidence > 50% ─────────────────
    if ai_confidence >= 50:
        try:
            from mcp_server.db import SessionLocal
            from mcp_server.models import Signal, ActiveTrade
            from mcp_server.telegram_receiver import record_signal_to_sheets

            db = SessionLocal()
            try:
                # Insert signal into DB
                from mcp_server.market_calendar import now_ist
                today = now_ist().date()

                db_signal = Signal(
                    signal_date=today,
                    signal_time=now_ist().time(),
                    ticker=ticker,
                    exchange=exchange,
                    asset_class=signal.asset_class,
                    direction=direction,
                    pattern=signal.pattern or "External Signal",
                    entry_price=entry,
                    stop_loss=sl,
                    target=tgt,
                    rrr=rrr,
                    qty=0,
                    risk_amt=0,
                    ai_confidence=ai_confidence,
                    tv_confirmed=False,
                    mwa_score=mwa_direction if 'mwa_direction' in dir() else "UNKNOWN",
                    scanner_count=scanner_count,
                    tier=2,
                    source="telegram",
                    timeframe="1D",
                    status="OPEN",
                )
                db.add(db_signal)
                db.flush()

                # Add to active trades
                active = ActiveTrade(
                    signal_id=db_signal.id,
                    ticker=ticker,
                    exchange=exchange,
                    asset_class=signal.asset_class,
                    entry_price=entry,
                    target=tgt,
                    stop_loss=sl,
                    prrr=rrr,
                    current_price=entry,
                    crrr=rrr,
                    timeframe="1D",
                )
                db.add(active)
                db.commit()

                # Record to Google Sheets
                try:
                    record_signal_to_sheets({
                        "signal_id": f"TG-{now_ist().strftime('%Y%m%d%H%M%S')}",
                        "date": str(today),
                        "ticker": ticker,
                        "exchange": exchange,
                        "asset_class": signal.asset_class,
                        "direction": direction,
                        "entry_price": entry,
                        "stop_loss": sl,
                        "target": tgt,
                        "rrr": rrr,
                        "pattern": signal.pattern or "External Signal",
                        "confidence": ai_confidence,
                        "notes": f"Telegram intake | {scanner_count} scanners | {debate_method}",
                    })
                except Exception as sheet_err:
                    logger.warning("Sheets recording failed: %s", sheet_err)

                report += (
                    f"\n\u2705 AUTO-TRACKED\n"
                    f"  \u2022 Added to Active Trades (ID: {db_signal.id})\n"
                    f"  \u2022 Signal Monitor will track SL/TGT\n"
                    f"  \u2022 Recorded to Google Sheets\n"
                    f"  \u2022 Scanners matched: {', '.join(s['name'] for s in matched_scanners[:5]) or 'None'}\n"
                )
            finally:
                db.close()
        except Exception as track_err:
            logger.error("Signal tracking failed: %s", track_err)
            report += f"\n\u26a0\ufe0f Tracking failed: {str(track_err)[:100]}\n"
    else:
        report += (
            f"\n\u26a0\ufe0f NOT TRACKED (confidence {ai_confidence}% < 50%)\n"
            f"  Signal not added to active trades.\n"
            f"  Use /signal with a higher-conviction setup.\n"
        )

    report += "\n\u26a0\ufe0f Not SEBI advice. AI analytics only."

    await update.message.reply_text(report)


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
    app.add_handler(CommandHandler("dhantoken", cmd_dhantoken))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("watchlist", cmd_watchlist))
    app.add_handler(CommandHandler("close", cmd_close))
    app.add_handler(CommandHandler("analyze", cmd_analyze))
    app.add_handler(CommandHandler("signal", cmd_signal))

    # SaaS multi-user commands
    from mcp_server.telegram_saas import (
        cmd_user_login, cmd_segments, cmd_alerts, cmd_setkey,
        cmd_mykeys, cmd_removekey, cmd_mystats, cmd_plan,
    )
    app.add_handler(CommandHandler("login", cmd_user_login))
    app.add_handler(CommandHandler("segments", cmd_segments))
    app.add_handler(CommandHandler("alerts", cmd_alerts))
    app.add_handler(CommandHandler("setkey", cmd_setkey))
    app.add_handler(CommandHandler("mykeys", cmd_mykeys))
    app.add_handler(CommandHandler("removekey", cmd_removekey))
    app.add_handler(CommandHandler("mystats", cmd_mystats))
    app.add_handler(CommandHandler("plan", cmd_plan))

    logger.info("Telegram bot configured with 21 command handlers")
    return app
