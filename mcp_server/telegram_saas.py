"""
MKUMARAN Trading OS — SaaS Telegram Bot (Multi-User)

Shared bot commands for SaaS users:
  /login email password     — Link Telegram to account
  /register                 — Register new account via Telegram
  /segments                 — View/toggle trading segments
  /alerts on/off            — Pause/resume signal alerts
  /setkey provider key      — Set BYOK API key
  /mykeys                   — View saved API keys (masked)
  /removekey provider       — Remove an API key
  /mystats                  — Personal signal accuracy
  /plan                     — View current subscription

Multi-user signal broadcast:
  broadcast_signal_to_users() — sends signals filtered by user segments + tier
"""

import logging
from datetime import date

from telegram import Update
from telegram.ext import ContextTypes

from mcp_server.config import settings
from mcp_server.db import SessionLocal

logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS = ["grok", "kimi", "openai", "claude", "gemini", "deepseek"]
TIER_DAILY_LIMITS = {"free": 3, "pro": -1, "elite": -1}  # -1 = unlimited


# ── Helpers ───────────────────────────────────────────────────

def _get_user_by_chat_id(db, chat_id: str) -> dict | None:
    from sqlalchemy import text
    row = db.execute(
        text("SELECT * FROM app_users WHERE telegram_chat_id = :cid AND is_active = true"),
        {"cid": str(chat_id)}
    ).mappings().first()
    return dict(row) if row else None


def _ensure_table(db):
    from mcp_server.auth_providers import _ensure_app_users_table
    _ensure_app_users_table(db)


# ── /login — Link Telegram to account ─────────────────────────

async def cmd_user_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /login email password"""
    if len(context.args) < 2:
        await update.message.reply_text(
            "\U0001f510 Link your account:\n/login your@email.com yourpassword"
        )
        return

    email = context.args[0].lower().strip()
    password = context.args[1]
    chat_id = str(update.effective_chat.id)

    db = SessionLocal()
    try:
        _ensure_table(db)
        from sqlalchemy import text
        from mcp_server.auth_providers import _verify_pw

        user = db.execute(
            text("SELECT id, email, name, password_hash, trading_segments, subscription_tier FROM app_users WHERE email = :e"),
            {"e": email}
        ).mappings().first()

        if not user:
            await update.message.reply_text("\u274c Account not found. Register at money.shadowmarket.ai first.")
            return

        if not _verify_pw(password, user["password_hash"]):
            await update.message.reply_text("\u274c Wrong password.")
            return

        # Link Telegram chat ID
        db.execute(
            text("UPDATE app_users SET telegram_chat_id = :cid, last_login = NOW() WHERE id = :id"),
            {"cid": chat_id, "id": user["id"]}
        )
        db.commit()

        segs = user["trading_segments"] or "None set"
        tier = user["subscription_tier"] or "free"
        await update.message.reply_text(
            f"\u2705 Logged in as {user['name'] or email}\n"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            f"Plan: {tier.upper()}\n"
            f"Segments: {segs}\n"
            f"Alerts: ON\n\n"
            f"You'll receive signals for your segments.\n"
            f"Use /segments to change, /alerts off to pause."
        )
    finally:
        db.close()


# ── /segments — View/toggle segments ──────────────────────────

async def cmd_segments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /segments [toggle segment_name]"""
    chat_id = str(update.effective_chat.id)
    db = SessionLocal()
    try:
        _ensure_table(db)
        user = _get_user_by_chat_id(db, chat_id)
        if not user:
            await update.message.reply_text("\u274c Not logged in. Use /login email password")
            return

        current = user.get("trading_segments", "") or ""
        current_list = [s.strip() for s in current.split(",") if s.strip()]

        all_segments = ["NSE Equity", "F&O", "Commodity", "Forex", "Options"]

        if context.args:
            # Toggle a segment
            seg = " ".join(context.args)
            # Find closest match
            matched = next((s for s in all_segments if s.lower() == seg.lower()), None)
            if not matched:
                await update.message.reply_text(
                    "\u274c Unknown segment. Available:\n" +
                    "\n".join(f"  \u2022 {s}" for s in all_segments)
                )
                return

            if matched in current_list:
                current_list.remove(matched)
                action = "removed"
            else:
                current_list.append(matched)
                action = "added"

            new_segs = ",".join(current_list)
            from sqlalchemy import text
            db.execute(
                text("UPDATE app_users SET trading_segments = :s WHERE telegram_chat_id = :cid"),
                {"s": new_segs, "cid": chat_id}
            )
            db.commit()

            await update.message.reply_text(f"\u2705 {matched} {action}.\nActive: {new_segs or 'None'}")
        else:
            # Show current segments
            lines = []
            for seg in all_segments:
                icon = "\u2705" if seg in current_list else "\u26aa"
                lines.append(f"  {icon} {seg}")

            await update.message.reply_text(
                "\U0001f4cb Your Segments:\n" +
                "\n".join(lines) +
                "\n\nToggle: /segments NSE Equity"
            )
    finally:
        db.close()


# ── /alerts — Toggle alerts ───────────────────────────────────

async def cmd_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    db = SessionLocal()
    try:
        _ensure_table(db)
        user = _get_user_by_chat_id(db, chat_id)
        if not user:
            await update.message.reply_text("\u274c Not logged in. Use /login email password")
            return

        from sqlalchemy import text
        if context.args and context.args[0].lower() == "off":
            db.execute(text("UPDATE app_users SET alert_enabled = false WHERE telegram_chat_id = :c"), {"c": chat_id})
            db.commit()
            await update.message.reply_text("\u23f8\ufe0f Alerts paused. Use /alerts on to resume.")
        elif context.args and context.args[0].lower() == "on":
            db.execute(text("UPDATE app_users SET alert_enabled = true WHERE telegram_chat_id = :c"), {"c": chat_id})
            db.commit()
            await update.message.reply_text("\u25b6\ufe0f Alerts resumed!")
        else:
            status = "ON" if user.get("alert_enabled", True) else "OFF"
            await update.message.reply_text(f"Alerts: {status}\nUse /alerts on or /alerts off")
    finally:
        db.close()


# ── /setkey — Set BYOK API key ────────────────────────────────

async def cmd_setkey(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /setkey provider api_key"""
    if len(context.args) < 2:
        await update.message.reply_text(
            "\U0001f511 Set your AI API key:\n\n"
            "/setkey grok xai-abc123...\n"
            "/setkey kimi sk-abc123...\n"
            "/setkey openai sk-abc123...\n"
            "/setkey claude sk-ant-abc123...\n"
            "/setkey gemini AIzaSy...\n"
            "/setkey deepseek sk-abc123...\n\n"
            "Your key is encrypted and used for AI analysis."
        )
        return

    provider = context.args[0].lower()
    api_key = context.args[1]

    if provider not in SUPPORTED_PROVIDERS:
        # Try auto-detect
        from mcp_server.ai_provider import detect_provider
        detected = detect_provider(api_key)
        if detected:
            provider = detected
        else:
            await update.message.reply_text(
                f"\u274c Unknown provider '{provider}'.\n"
                f"Supported: {', '.join(SUPPORTED_PROVIDERS)}"
            )
            return

    chat_id = str(update.effective_chat.id)
    db = SessionLocal()
    try:
        _ensure_table(db)
        user = _get_user_by_chat_id(db, chat_id)
        if not user:
            await update.message.reply_text("\u274c Not logged in. Use /login email password")
            return

        # Save key via BYOK system
        from mcp_server.auth_providers import save_user_api_keys, get_user_api_keys
        existing = await get_user_api_keys(db, user["email"])
        existing[f"{provider}_key"] = api_key
        if "preferred_provider" not in existing:
            existing["preferred_provider"] = provider
        await save_user_api_keys(db, user["email"], existing)

        masked = api_key[:6] + "****" + api_key[-4:]
        await update.message.reply_text(
            f"\u2705 {provider.upper()} key saved: {masked}\n"
            f"AI calls will use YOUR key for analysis."
        )
    finally:
        db.close()


# ── /mykeys — Show saved keys ─────────────────────────────────

async def cmd_mykeys(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    db = SessionLocal()
    try:
        _ensure_table(db)
        user = _get_user_by_chat_id(db, chat_id)
        if not user:
            await update.message.reply_text("\u274c Not logged in.")
            return

        from mcp_server.auth_providers import get_user_api_keys
        keys = await get_user_api_keys(db, user["email"])

        if not keys:
            await update.message.reply_text(
                "\U0001f511 No API keys saved.\nUse /setkey provider key to add one."
            )
            return

        lines = ["\U0001f511 Your API Keys:"]
        pref = keys.get("preferred_provider", "")
        for p in SUPPORTED_PROVIDERS:
            k = keys.get(f"{p}_key", "")
            if k:
                masked = k[:4] + "****" + k[-4:]
                star = " \u2b50" if p == pref else ""
                lines.append(f"  \u2705 {p}: {masked}{star}")
            else:
                lines.append(f"  \u26aa {p}: not set")

        lines.append(f"\nPreferred: {pref or 'auto'}")
        lines.append("Remove: /removekey provider")
        await update.message.reply_text("\n".join(lines))
    finally:
        db.close()


# ── /removekey — Remove a key ─────────────────────────────────

async def cmd_removekey(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /removekey grok")
        return

    provider = context.args[0].lower()
    chat_id = str(update.effective_chat.id)
    db = SessionLocal()
    try:
        _ensure_table(db)
        user = _get_user_by_chat_id(db, chat_id)
        if not user:
            await update.message.reply_text("\u274c Not logged in.")
            return

        from mcp_server.auth_providers import get_user_api_keys, save_user_api_keys
        keys = await get_user_api_keys(db, user["email"])
        key_name = f"{provider}_key"
        if key_name in keys:
            del keys[key_name]
            await save_user_api_keys(db, user["email"], keys)
            await update.message.reply_text(f"\u2705 {provider.upper()} key removed.")
        else:
            await update.message.reply_text(f"\u26a0\ufe0f No {provider} key found.")
    finally:
        db.close()


# ── /mystats — Personal accuracy ──────────────────────────────

async def cmd_mystats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    db = SessionLocal()
    try:
        _ensure_table(db)
        user = _get_user_by_chat_id(db, chat_id)
        if not user:
            await update.message.reply_text("\u274c Not logged in.")
            return

        await update.message.reply_text(
            f"\U0001f4ca Stats for {user.get('name', 'User')}\n"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            f"Plan: {(user.get('subscription_tier') or 'free').upper()}\n"
            f"Segments: {user.get('trading_segments', 'None')}\n"
            f"Alerts: {'ON' if user.get('alert_enabled', True) else 'OFF'}\n"
            f"Joined: {str(user.get('created_at', ''))[:10]}"
        )
    finally:
        db.close()


# ── /plan — View subscription ─────────────────────────────────

async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    db = SessionLocal()
    try:
        _ensure_table(db)
        user = _get_user_by_chat_id(db, chat_id)
        if not user:
            await update.message.reply_text("\u274c Not logged in.")
            return

        tier = (user.get("subscription_tier") or "free").upper()
        limit = TIER_DAILY_LIMITS.get(tier.lower(), 3)
        limit_text = "Unlimited" if limit == -1 else f"{limit}/day"

        await update.message.reply_text(
            f"\U0001f4b3 Your Plan: {tier}\n"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            f"Signal limit: {limit_text}\n"
            f"Upgrade at money.shadowmarket.ai"
        )
    finally:
        db.close()


# ── Multi-user signal broadcast ───────────────────────────────

SEGMENT_MAP = {
    "NSE": "NSE Equity",
    "BSE": "NSE Equity",
    "NFO": "F&O",
    "MCX": "Commodity",
    "CDS": "Forex",
}


async def broadcast_signal_to_users(signal_text: str, exchange: str = "NSE") -> int:
    """Send signal to all subscribed users for this segment.

    Args:
        signal_text: Formatted signal message
        exchange: Signal exchange (NSE, NFO, MCX, CDS)

    Returns:
        Number of users notified
    """
    segment = SEGMENT_MAP.get(exchange, "NSE Equity")
    today = date.today()

    db = SessionLocal()
    try:
        _ensure_table(db)
        from sqlalchemy import text

        # Find users subscribed to this segment with alerts ON
        users = db.execute(
            text("""SELECT id, telegram_chat_id, subscription_tier, daily_signal_count, last_signal_date
                    FROM app_users
                    WHERE telegram_chat_id IS NOT NULL
                      AND alert_enabled = true
                      AND is_active = true
                      AND trading_segments LIKE :seg"""),
            {"seg": f"%{segment}%"}
        ).mappings().all()

        if not users:
            return 0

        sent = 0
        import httpx
        for user in users:
            try:
                tier = user.get("subscription_tier") or "free"
                limit = TIER_DAILY_LIMITS.get(tier, 3)
                count = user.get("daily_signal_count") or 0
                last_date = user.get("last_signal_date")

                # Reset daily count if new day
                if last_date != today:
                    count = 0

                # Check limit
                if limit != -1 and count >= limit:
                    continue

                # Send via Telegram API
                chat_id = user["telegram_chat_id"]
                url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(url, json={
                        "chat_id": chat_id,
                        "text": signal_text,
                        "disable_web_page_preview": True,
                    })

                if resp.status_code == 200:
                    sent += 1
                    # Update daily count
                    db.execute(
                        text("UPDATE app_users SET daily_signal_count = :c, last_signal_date = :d WHERE id = :id"),
                        {"c": count + 1, "d": today, "id": user["id"]}
                    )

            except Exception as e:
                logger.debug("Broadcast failed for user %s: %s", user["id"], e)

        db.commit()
        logger.info("Signal broadcast: %d/%d users notified (segment=%s)", sent, len(users), segment)
        return sent

    except Exception as e:
        logger.error("Signal broadcast failed: %s", e)
        return 0
    finally:
        db.close()
