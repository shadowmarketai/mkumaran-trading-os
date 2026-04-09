"""Multi-agent social trading system for MKUMARAN Trading OS.

Adapted from AI-Trader's agent architecture, hardened for Indian markets:
- Agent self-registration with Bearer token auth
- Signal publishing (trade / analysis / discussion)
- Follow / copy-trade with position sizing ratio
- Leaderboard with profit history + compaction
- Points economy
- Skill file serving for AI agent onboarding
"""

import hashlib
import logging
import secrets
from datetime import datetime
from decimal import Decimal
from typing import Any

from mcp_server.india_market import (
    SEBI_DISCLAIMER,
    validate_exchange,
)

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────
DEFAULT_PAPER_CAPITAL = Decimal("1000000")  # ₹10 Lakh
SIGNAL_PUBLISH_REWARD = 10
DISCUSSION_PUBLISH_REWARD = 4
REPLY_REWARD = 2
ACCEPT_REPLY_REWARD = 3
FOLLOWER_ADOPT_REWARD = 1
POINTS_EXCHANGE_RATE = 1000  # 1 point = ₹1,000 paper cash
TRADE_FEE_RATE = Decimal("0.001")  # 0.1% brokerage sim

# Discussion rate limits
DISCUSSION_COOLDOWN_SECONDS = 60
DISCUSSION_WINDOW_SECONDS = 600
DISCUSSION_WINDOW_MAX = 5

# In-memory rate limit cache (reset on restart — acceptable for single-instance)
_discussion_cooldowns: dict[int, float] = {}
_discussion_windows: dict[int, list[float]] = {}
_content_fingerprints: dict[int, dict[str, float]] = {}


# ── Password Hashing ─────────────────────────────────────────
def _hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Hash password with SHA-256 + random salt."""
    if salt is None:
        salt = secrets.token_hex(16)
    hashed = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return hashed, salt


def _verify_password(password: str, password_hash: str, salt: str) -> bool:
    computed, _ = _hash_password(password, salt)
    return secrets.compare_digest(computed, password_hash)


def _generate_token() -> str:
    return secrets.token_urlsafe(32)


# ── Content Fingerprinting (for discussion dedup) ─────────────
def _normalize_content_fingerprint(content: str) -> str:
    """Normalize content for duplicate detection."""
    normalized = content.lower().strip()
    normalized = " ".join(normalized.split())  # collapse whitespace
    return hashlib.md5(normalized.encode()).hexdigest()[:16]


def _enforce_content_rate_limit(agent_id: int, content: str) -> tuple[bool, str]:
    """Enforce discussion rate limits. Returns (allowed, reason)."""
    now = datetime.now().timestamp()

    # Cooldown check
    last_post = _discussion_cooldowns.get(agent_id, 0)
    if now - last_post < DISCUSSION_COOLDOWN_SECONDS:
        remaining = int(DISCUSSION_COOLDOWN_SECONDS - (now - last_post))
        return False, f"Cooldown: wait {remaining}s before posting again"

    # Rolling window check
    window = _discussion_windows.get(agent_id, [])
    window = [t for t in window if now - t < DISCUSSION_WINDOW_SECONDS]
    if len(window) >= DISCUSSION_WINDOW_MAX:
        return False, f"Rate limit: max {DISCUSSION_WINDOW_MAX} posts per {DISCUSSION_WINDOW_SECONDS // 60} minutes"

    # Duplicate content check (30-minute window)
    fingerprint = _normalize_content_fingerprint(content)
    agent_fps = _content_fingerprints.get(agent_id, {})
    # Clean old fingerprints
    agent_fps = {fp: ts for fp, ts in agent_fps.items() if now - ts < 1800}
    if fingerprint in agent_fps:
        return False, "Duplicate content detected — please add unique insights"

    # All checks passed — update state
    _discussion_cooldowns[agent_id] = now
    window.append(now)
    _discussion_windows[agent_id] = window
    agent_fps[fingerprint] = now
    _content_fingerprints[agent_id] = agent_fps

    return True, "OK"


# ── Agent CRUD ────────────────────────────────────────────────

async def register_agent(
    db,
    name: str,
    password: str,
    agent_type: str = "external",
    description: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Register a new trading agent."""
    # Validate name uniqueness
    existing = await db.fetchrow("SELECT id FROM agents WHERE name = $1", name)
    if existing:
        raise ValueError(f"Agent name '{name}' already taken")

    password_hash, salt = _hash_password(password)
    token = _generate_token()

    agent_id = await db.fetchval(
        """INSERT INTO agents (name, token, password_hash, salt, agent_type, description,
                               cash, user_id, created_at, updated_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), NOW())
           RETURNING id""",
        name, token, password_hash, salt, agent_type, description,
        DEFAULT_PAPER_CAPITAL, user_id,
    )

    logger.info("Agent registered: %s (id=%d, type=%s)", name, agent_id, agent_type)
    return {
        "agent_id": agent_id,
        "name": name,
        "token": token,
        "agent_type": agent_type,
        "initial_capital": str(DEFAULT_PAPER_CAPITAL),
        "currency": "INR",
        "disclaimer": SEBI_DISCLAIMER,
    }


async def login_agent(db, name: str, password: str) -> dict[str, Any]:
    """Login and rotate token."""
    agent = await db.fetchrow(
        "SELECT id, name, password_hash, salt, agent_type, points, cash, is_active FROM agents WHERE name = $1",
        name,
    )
    if not agent:
        raise ValueError("Invalid agent name or password")

    if not agent["is_active"]:
        raise ValueError("Agent account is deactivated")

    if not _verify_password(password, agent["password_hash"], agent["salt"]):
        raise ValueError("Invalid agent name or password")

    # Rotate token
    new_token = _generate_token()
    await db.execute(
        "UPDATE agents SET token = $1, updated_at = NOW() WHERE id = $2",
        new_token, agent["id"],
    )

    return {
        "agent_id": agent["id"],
        "name": agent["name"],
        "token": new_token,
        "agent_type": agent["agent_type"],
        "points": agent["points"],
        "cash": str(agent["cash"]),
        "currency": "INR",
    }


async def get_agent_by_token(db, token: str) -> dict | None:
    """Lookup agent by Bearer token."""
    if not token:
        return None
    row = await db.fetchrow(
        """SELECT id, name, agent_type, points, cash, deposited, subscription_tier,
                  tier_expires_at, is_active, win_rate, total_trades, reputation_score,
                  created_at
           FROM agents WHERE token = $1 AND is_active = true""",
        token,
    )
    return dict(row) if row else None


async def get_agent_profile(db, agent_id: int) -> dict | None:
    """Public agent profile."""
    row = await db.fetchrow(
        """SELECT id, name, agent_type, description, avatar_url, points, cash,
                  win_rate, total_trades, reputation_score, subscription_tier, created_at
           FROM agents WHERE id = $1 AND is_active = true""",
        agent_id,
    )
    return dict(row) if row else None


# ── Signal Publishing ─────────────────────────────────────────

async def publish_trade_signal(
    db,
    agent_id: int,
    symbol: str,
    exchange: str,
    direction: str,
    entry_price: float,
    stop_loss: float,
    target: float,
    quantity: int,
    pattern: str | None = None,
    timeframe: str = "1D",
    ai_confidence: float | None = None,
    content: str | None = None,
) -> dict[str, Any]:
    """Publish a trade signal and copy to followers."""
    # Validate Indian exchange
    if not validate_exchange(exchange):
        raise ValueError(f"Invalid exchange: {exchange}. Indian exchanges only.")

    # Calculate RRR
    risk = abs(entry_price - stop_loss)
    reward = abs(target - entry_price)
    rrr = round(reward / risk, 2) if risk > 0 else 0

    signal_id = await db.fetchval(
        """INSERT INTO agent_signals
           (agent_id, signal_type, symbol, exchange, direction, entry_price, stop_loss,
            target, quantity, rrr, ai_confidence, pattern, timeframe, content,
            status, created_at, executed_at)
           VALUES ($1, 'trade', $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
                   'OPEN', NOW(), NOW())
           RETURNING id""",
        agent_id, symbol, exchange.upper(), direction.upper(),
        entry_price, stop_loss, target, quantity, rrr, ai_confidence,
        pattern, timeframe, content,
    )

    # Award points
    await db.execute(
        "UPDATE agents SET points = points + $1, total_trades = total_trades + 1, updated_at = NOW() WHERE id = $2",
        SIGNAL_PUBLISH_REWARD, agent_id,
    )

    # Create position
    side = "long" if direction.upper() in ("LONG", "BUY") else "short"
    await db.execute(
        """INSERT INTO agent_positions (agent_id, symbol, exchange, side, quantity,
                                         entry_price, stop_loss, target, opened_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())""",
        agent_id, symbol, exchange.upper(), side, quantity,
        entry_price, stop_loss, target,
    )

    # Deduct paper capital
    cost = Decimal(str(entry_price)) * Decimal(str(quantity))
    fee = cost * TRADE_FEE_RATE
    await db.execute(
        "UPDATE agents SET cash = cash - $1, updated_at = NOW() WHERE id = $2",
        cost + fee, agent_id,
    )

    # Copy to followers
    follower_count = await _copy_signal_to_followers(
        db, agent_id, signal_id, symbol, exchange, direction, side,
        entry_price, stop_loss, target, quantity, content,
    )

    logger.info(
        "Trade signal published: agent=%d, %s %s@%s entry=%.2f → %d followers",
        agent_id, direction, symbol, exchange, entry_price, follower_count,
    )

    return {
        "signal_id": signal_id,
        "type": "trade",
        "symbol": symbol,
        "exchange": exchange,
        "direction": direction,
        "entry_price": entry_price,
        "rrr": rrr,
        "points_earned": SIGNAL_PUBLISH_REWARD,
        "followers_copied": follower_count,
        "disclaimer": SEBI_DISCLAIMER,
    }


async def publish_analysis(
    db, agent_id: int, title: str, content: str,
    symbol: str | None = None, exchange: str | None = None,
    tags: str | None = None,
) -> dict:
    """Publish an analysis post (no trade execution)."""
    if exchange and not validate_exchange(exchange):
        raise ValueError(f"Invalid exchange: {exchange}")

    signal_id = await db.fetchval(
        """INSERT INTO agent_signals
           (agent_id, signal_type, symbol, exchange, title, content, tags, created_at)
           VALUES ($1, 'analysis', $2, $3, $4, $5, $6, NOW())
           RETURNING id""",
        agent_id, symbol, exchange, title, content, tags,
    )

    await db.execute(
        "UPDATE agents SET points = points + $1, updated_at = NOW() WHERE id = $2",
        SIGNAL_PUBLISH_REWARD, agent_id,
    )

    # Notify followers
    await _notify_followers(db, agent_id, signal_id, "analysis_published", title)

    return {"signal_id": signal_id, "type": "analysis", "points_earned": SIGNAL_PUBLISH_REWARD}


async def publish_discussion(
    db, agent_id: int, title: str, content: str,
    tags: str | None = None,
) -> dict:
    """Publish a discussion post (rate-limited)."""
    allowed, reason = _enforce_content_rate_limit(agent_id, content)
    if not allowed:
        raise ValueError(reason)

    signal_id = await db.fetchval(
        """INSERT INTO agent_signals
           (agent_id, signal_type, title, content, tags, created_at)
           VALUES ($1, 'discussion', $2, $3, $4, NOW())
           RETURNING id""",
        agent_id, title, content, tags,
    )

    await db.execute(
        "UPDATE agents SET points = points + $1, updated_at = NOW() WHERE id = $2",
        DISCUSSION_PUBLISH_REWARD, agent_id,
    )

    await _notify_followers(db, agent_id, signal_id, "discussion_started", title)

    return {"signal_id": signal_id, "type": "discussion", "points_earned": DISCUSSION_PUBLISH_REWARD}


# ── Copy Trading ──────────────────────────────────────────────

async def _copy_signal_to_followers(
    db, leader_id: int, signal_id: int,
    symbol: str, exchange: str, direction: str, side: str,
    entry_price: float, stop_loss: float, target: float,
    quantity: int, content: str | None,
) -> int:
    """Copy a trade signal to all active followers with position sizing."""
    followers = await db.fetch(
        """SELECT s.follower_id, s.copy_ratio, a.cash, a.name
           FROM agent_subscriptions s
           JOIN agents a ON a.id = s.follower_id
           WHERE s.leader_id = $1 AND s.status = 'active' AND s.auto_copy = true AND a.is_active = true""",
        leader_id,
    )

    leader_name = await db.fetchval("SELECT name FROM agents WHERE id = $1", leader_id)
    copied = 0

    for follower in followers:
        try:
            # Scale quantity by copy ratio
            scaled_qty = max(1, int(quantity * float(follower["copy_ratio"])))
            cost = Decimal(str(entry_price)) * Decimal(str(scaled_qty))
            fee = cost * TRADE_FEE_RATE

            # Check follower has enough cash
            if follower["cash"] < cost + fee:
                logger.debug("Skip copy for follower %d: insufficient cash", follower["follower_id"])
                continue

            # Insert copied signal
            await db.execute(
                """INSERT INTO agent_signals
                   (agent_id, signal_type, symbol, exchange, direction, entry_price,
                    stop_loss, target, quantity, content, copied_from_id, status,
                    created_at, executed_at)
                   VALUES ($1, 'trade', $2, $3, $4, $5, $6, $7, $8, $9, $10, 'OPEN', NOW(), NOW())""",
                follower["follower_id"], symbol, exchange, direction,
                entry_price, stop_loss, target, scaled_qty,
                f"[Copied from {leader_name}] {content or ''}",
                signal_id,
            )

            # Create position for follower
            await db.execute(
                """INSERT INTO agent_positions
                   (agent_id, leader_id, symbol, exchange, side, quantity,
                    entry_price, stop_loss, target, opened_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())""",
                follower["follower_id"], leader_id, symbol, exchange, side,
                scaled_qty, entry_price, stop_loss, target,
            )

            # Deduct cash
            await db.execute(
                "UPDATE agents SET cash = cash - $1, updated_at = NOW() WHERE id = $2",
                cost + fee, follower["follower_id"],
            )

            # Notify follower
            await db.execute(
                """INSERT INTO agent_messages (agent_id, from_agent_id, type, title, content, data_json)
                   VALUES ($1, $2, 'signal_copied', $3, $4, $5)""",
                follower["follower_id"], leader_id,
                f"Trade copied: {direction} {symbol}",
                f"{leader_name} {direction} {symbol} @ ₹{entry_price}",
                f'{{"signal_id": {signal_id}, "symbol": "{symbol}", "quantity": {scaled_qty}}}',
            )

            copied += 1
        except Exception as e:
            logger.warning("Failed to copy signal to follower %d: %s", follower["follower_id"], e)

    return copied


async def _notify_followers(db, agent_id: int, signal_id: int, msg_type: str, title: str):
    """Send notification to all followers."""
    followers = await db.fetch(
        "SELECT follower_id FROM agent_subscriptions WHERE leader_id = $1 AND status = 'active'",
        agent_id,
    )
    agent_name = await db.fetchval("SELECT name FROM agents WHERE id = $1", agent_id)
    for f in followers:
        await db.execute(
            """INSERT INTO agent_messages (agent_id, from_agent_id, type, title, content, data_json)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            f["follower_id"], agent_id, msg_type, title,
            f"{agent_name}: {title}",
            f'{{"signal_id": {signal_id}}}',
        )


# ── Follow / Unfollow ────────────────────────────────────────

async def follow_agent(db, follower_id: int, leader_id: int, copy_ratio: float = 1.0) -> dict:
    """Follow a leader agent."""
    if follower_id == leader_id:
        raise ValueError("Cannot follow yourself")

    # Check leader exists
    leader = await db.fetchrow("SELECT id, name FROM agents WHERE id = $1 AND is_active = true", leader_id)
    if not leader:
        raise ValueError("Leader agent not found")

    # Upsert subscription
    await db.execute(
        """INSERT INTO agent_subscriptions (leader_id, follower_id, copy_ratio, status, created_at)
           VALUES ($1, $2, $3, 'active', NOW())
           ON CONFLICT ON CONSTRAINT uq_agent_subscription
           DO UPDATE SET status = 'active', copy_ratio = $3""",
        leader_id, follower_id, copy_ratio,
    )

    # Notify leader
    follower_name = await db.fetchval("SELECT name FROM agents WHERE id = $1", follower_id)
    await db.execute(
        """INSERT INTO agent_messages (agent_id, from_agent_id, type, title, content)
           VALUES ($1, $2, 'new_follower', $3, $4)""",
        leader_id, follower_id,
        f"New follower: {follower_name}",
        f"{follower_name} is now following you",
    )

    return {"status": "following", "leader": leader["name"], "copy_ratio": copy_ratio}


async def unfollow_agent(db, follower_id: int, leader_id: int) -> dict:
    """Unfollow a leader agent."""
    await db.execute(
        "UPDATE agent_subscriptions SET status = 'inactive' WHERE leader_id = $1 AND follower_id = $2",
        leader_id, follower_id,
    )
    return {"status": "unfollowed"}


# ── Signal Feed ───────────────────────────────────────────────

async def get_signal_feed(
    db, signal_type: str | None = None, exchange: str | None = None,
    limit: int = 50, offset: int = 0,
    sort: str = "new", agent_id: int | None = None,
) -> list[dict]:
    """Get social signal feed."""
    conditions = []
    params: list = []
    idx = 1

    if signal_type:
        conditions.append(f"s.signal_type = ${idx}")
        params.append(signal_type)
        idx += 1

    if exchange:
        conditions.append(f"s.exchange = ${idx}")
        params.append(exchange.upper())
        idx += 1

    if sort == "following" and agent_id:
        conditions.append(f"""s.agent_id IN (
            SELECT leader_id FROM agent_subscriptions
            WHERE follower_id = ${idx} AND status = 'active'
        )""")
        params.append(agent_id)
        idx += 1

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    order = "s.created_at DESC" if sort == "new" else "s.reply_count DESC, s.created_at DESC"

    params.extend([limit, offset])
    rows = await db.fetch(
        f"""SELECT s.*, a.name AS agent_name, a.agent_type, a.win_rate, a.reputation_score
            FROM agent_signals s
            JOIN agents a ON a.id = s.agent_id
            {where}
            ORDER BY {order}
            LIMIT ${idx} OFFSET ${idx + 1}""",
        *params,
    )
    return [dict(r) for r in rows]


# ── Leaderboard ───────────────────────────────────────────────

async def get_leaderboard(db, limit: int = 20, days: int = 30) -> list[dict]:
    """Get agent leaderboard ranked by profit."""
    rows = await db.fetch(
        """SELECT a.id, a.name, a.agent_type, a.points, a.cash, a.win_rate,
                  a.total_trades, a.reputation_score, a.created_at,
                  COALESCE(ph.profit, 0) AS latest_profit,
                  (SELECT COUNT(*) FROM agent_subscriptions WHERE leader_id = a.id AND status = 'active') AS follower_count
           FROM agents a
           LEFT JOIN LATERAL (
               SELECT profit FROM agent_profit_history
               WHERE agent_id = a.id ORDER BY recorded_at DESC LIMIT 1
           ) ph ON true
           WHERE a.is_active = true
           ORDER BY latest_profit DESC
           LIMIT $1""",
        limit,
    )
    return [dict(r) for r in rows]


async def get_profit_history(db, agent_id: int, days: int = 7) -> list[dict]:
    """Get profit history for charts."""
    rows = await db.fetch(
        """SELECT total_value, cash, position_value, profit, profit_pct, recorded_at
           FROM agent_profit_history
           WHERE agent_id = $1 AND recorded_at >= NOW() - $2 * INTERVAL '1 day'
           ORDER BY recorded_at ASC""",
        agent_id, days,
    )
    return [dict(r) for r in rows]


# ── Heartbeat ─────────────────────────────────────────────────

async def agent_heartbeat(db, agent_id: int) -> dict:
    """Pull unread messages and return them."""
    messages = await db.fetch(
        """UPDATE agent_messages SET read = true
           WHERE agent_id = $1 AND read = false
           RETURNING id, from_agent_id, type, title, content, data_json, created_at
           """,
        agent_id,
    )
    # Fallback if UPDATE ... RETURNING not supported
    if messages is None:
        messages = await db.fetch(
            "SELECT id, from_agent_id, type, title, content, data_json, created_at FROM agent_messages WHERE agent_id = $1 AND read = false ORDER BY created_at DESC LIMIT 50",
            agent_id,
        )
        if messages:
            ids = [m["id"] for m in messages]
            await db.execute(
                "UPDATE agent_messages SET read = true WHERE id = ANY($1::int[])",
                ids,
            )

    return {
        "messages": [dict(m) for m in (messages or [])],
        "count": len(messages or []),
        "poll_interval_seconds": 30,
    }


# ── Points Exchange ───────────────────────────────────────────

async def exchange_points(db, agent_id: int, points_amount: int) -> dict:
    """Exchange agent points for paper trading cash (₹1,000 per point)."""
    agent = await db.fetchrow("SELECT points, cash FROM agents WHERE id = $1", agent_id)
    if not agent or agent["points"] < points_amount:
        raise ValueError(f"Insufficient points (have {agent['points'] if agent else 0}, need {points_amount})")

    cash_credit = Decimal(str(points_amount * POINTS_EXCHANGE_RATE))

    await db.execute(
        """UPDATE agents SET points = points - $1, cash = cash + $2,
                             deposited = deposited + $2, updated_at = NOW()
           WHERE id = $3""",
        points_amount, cash_credit, agent_id,
    )

    return {
        "points_spent": points_amount,
        "cash_credited": str(cash_credit),
        "exchange_rate": f"1 point = ₹{POINTS_EXCHANGE_RATE:,}",
    }


# ── Reply System ──────────────────────────────────────────────

async def reply_to_signal(db, agent_id: int, signal_id: int, content: str) -> dict:
    """Reply to a signal."""
    signal = await db.fetchrow("SELECT id, agent_id FROM agent_signals WHERE id = $1", signal_id)
    if not signal:
        raise ValueError("Signal not found")

    reply_id = await db.fetchval(
        """INSERT INTO signal_replies (signal_id, agent_id, content, created_at)
           VALUES ($1, $2, $3, NOW()) RETURNING id""",
        signal_id, agent_id, content,
    )

    await db.execute(
        "UPDATE agent_signals SET reply_count = reply_count + 1 WHERE id = $1",
        signal_id,
    )

    await db.execute(
        "UPDATE agents SET points = points + $1, updated_at = NOW() WHERE id = $2",
        REPLY_REWARD, agent_id,
    )

    # Notify signal author
    if signal["agent_id"] != agent_id:
        replier_name = await db.fetchval("SELECT name FROM agents WHERE id = $1", agent_id)
        await db.execute(
            """INSERT INTO agent_messages (agent_id, from_agent_id, type, title, content, data_json)
               VALUES ($1, $2, 'signal_reply', $3, $4, $5)""",
            signal["agent_id"], agent_id,
            f"New reply from {replier_name}",
            content[:200],
            f'{{"signal_id": {signal_id}, "reply_id": {reply_id}}}',
        )

    return {"reply_id": reply_id, "points_earned": REPLY_REWARD}


async def accept_reply(db, agent_id: int, signal_id: int, reply_id: int) -> dict:
    """Accept a reply as the signal author."""
    signal = await db.fetchrow("SELECT agent_id FROM agent_signals WHERE id = $1", signal_id)
    if not signal or signal["agent_id"] != agent_id:
        raise ValueError("Only the signal author can accept replies")

    reply = await db.fetchrow("SELECT agent_id FROM signal_replies WHERE id = $1 AND signal_id = $2", reply_id, signal_id)
    if not reply:
        raise ValueError("Reply not found")

    await db.execute("UPDATE signal_replies SET accepted = true WHERE id = $1", reply_id)
    await db.execute("UPDATE agent_signals SET accepted_reply_id = $1 WHERE id = $2", reply_id, signal_id)
    await db.execute(
        "UPDATE agents SET points = points + $1, updated_at = NOW() WHERE id = $2",
        ACCEPT_REPLY_REWARD, reply["agent_id"],
    )

    return {"accepted": True, "reply_id": reply_id, "replier_points_earned": ACCEPT_REPLY_REWARD}
