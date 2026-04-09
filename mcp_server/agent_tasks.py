"""Background tasks for multi-agent system.

Adopted from AI-Trader's task patterns:
- Profit history recording (every 5 min)
- Profit history compaction (every hour)
- Subscription status checks (every hour)
- Agent position price updates (every 60s during market hours)
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from decimal import Decimal

from mcp_server.india_market import IST, is_market_open, now_ist

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────
PROFIT_RECORD_INTERVAL = int(os.getenv("PROFIT_RECORD_INTERVAL", "300"))  # 5 min
PROFIT_PRUNE_INTERVAL = int(os.getenv("PROFIT_PRUNE_INTERVAL", "3600"))  # 1 hour
POSITION_REFRESH_INTERVAL = int(os.getenv("POSITION_REFRESH_INTERVAL", "60"))  # 1 min
SUBSCRIPTION_CHECK_INTERVAL = int(os.getenv("SUBSCRIPTION_CHECK_INTERVAL", "3600"))

# Compaction settings
FULL_RESOLUTION_HOURS = int(os.getenv("PROFIT_FULL_RESOLUTION_HOURS", "24"))
COMPACT_WINDOW_DAYS = int(os.getenv("PROFIT_COMPACT_WINDOW_DAYS", "7"))
COMPACT_BUCKET_MINUTES = 15


async def record_profit_history(db):
    """Record profit snapshot for all agents every PROFIT_RECORD_INTERVAL seconds."""
    while True:
        try:
            agents = await db.fetch(
                "SELECT id, cash, deposited FROM agents WHERE is_active = true"
            )
            for agent in agents:
                # Calculate position value
                positions = await db.fetch(
                    "SELECT quantity, current_price, entry_price, side FROM agent_positions WHERE agent_id = $1 AND status = 'open'",
                    agent["id"],
                )
                position_value = Decimal("0")
                for pos in positions:
                    if pos["current_price"]:
                        qty = Decimal(str(pos["quantity"]))
                        cur = Decimal(str(pos["current_price"]))
                        position_value += qty * cur

                total = agent["cash"] + position_value
                initial = Decimal("1000000") + (agent["deposited"] or Decimal("0"))
                profit = total - initial
                profit_pct = (profit / initial * 100) if initial > 0 else Decimal("0")

                # Clamp absurd values
                if abs(profit) > Decimal("1e12"):
                    continue

                await db.execute(
                    """INSERT INTO agent_profit_history
                       (agent_id, total_value, cash, position_value, profit, profit_pct, recorded_at)
                       VALUES ($1, $2, $3, $4, $5, $6, NOW())""",
                    agent["id"], total, agent["cash"], position_value, profit, profit_pct,
                )

            logger.debug("Recorded profit history for %d agents", len(agents))
        except Exception as e:
            logger.error("Error recording profit history: %s", e)

        await asyncio.sleep(PROFIT_RECORD_INTERVAL)


async def prune_profit_history(db):
    """Compact old profit history records.

    - Keep full resolution for last FULL_RESOLUTION_HOURS hours
    - Compact to 15-min buckets for COMPACT_WINDOW_DAYS
    - Delete anything older than COMPACT_WINDOW_DAYS
    """
    while True:
        try:
            now = now_ist()

            # 1. Delete records older than compact window
            cutoff = now - timedelta(days=COMPACT_WINDOW_DAYS)
            result = await db.execute(
                "DELETE FROM agent_profit_history WHERE recorded_at < $1",
                cutoff,
            )
            logger.debug("Pruned profit history older than %s", cutoff.isoformat())

            # 2. Compact records older than full-resolution window into 15-min buckets
            compact_cutoff = now - timedelta(hours=FULL_RESOLUTION_HOURS)
            # Keep only the latest record per (agent_id, 15-min bucket)
            await db.execute(
                """DELETE FROM agent_profit_history
                   WHERE recorded_at < $1
                     AND recorded_at >= $2
                     AND id NOT IN (
                         SELECT DISTINCT ON (agent_id, date_trunc('hour', recorded_at) +
                                INTERVAL '15 min' * FLOOR(EXTRACT(MINUTE FROM recorded_at) / 15))
                                id
                         FROM agent_profit_history
                         WHERE recorded_at < $1 AND recorded_at >= $2
                         ORDER BY agent_id, date_trunc('hour', recorded_at) +
                                  INTERVAL '15 min' * FLOOR(EXTRACT(MINUTE FROM recorded_at) / 15),
                                  recorded_at DESC
                     )""",
                compact_cutoff, cutoff,
            )
            logger.debug("Compacted profit history into 15-min buckets")
        except Exception as e:
            logger.error("Error pruning profit history: %s", e)

        await asyncio.sleep(PROFIT_PRUNE_INTERVAL)


async def check_subscription_status(db):
    """Check and expire subscriptions that are past their period end."""
    while True:
        try:
            now = now_ist()

            # Expire subscriptions past their period end
            expired = await db.fetch(
                """UPDATE user_subscriptions
                   SET status = 'expired'
                   WHERE status IN ('active', 'trialing')
                     AND current_period_end < $1
                   RETURNING agent_id""",
                now,
            )

            # Downgrade expired agents to free tier
            if expired:
                for row in expired:
                    if row["agent_id"]:
                        await db.execute(
                            "UPDATE agents SET subscription_tier = 'free', tier_expires_at = NULL, updated_at = NOW() WHERE id = $1",
                            row["agent_id"],
                        )
                logger.info("Expired %d subscriptions, downgraded to free tier", len(expired))

            # Expire trials that are past trial_end
            trial_expired = await db.fetch(
                """UPDATE user_subscriptions
                   SET status = 'expired'
                   WHERE status = 'trialing'
                     AND trial_end < $1
                   RETURNING agent_id""",
                now,
            )
            if trial_expired:
                for row in trial_expired:
                    if row["agent_id"]:
                        await db.execute(
                            "UPDATE agents SET subscription_tier = 'free', tier_expires_at = NULL, updated_at = NOW() WHERE id = $1",
                            row["agent_id"],
                        )
                logger.info("Expired %d trial subscriptions", len(trial_expired))

        except Exception as e:
            logger.error("Error checking subscription status: %s", e)

        await asyncio.sleep(SUBSCRIPTION_CHECK_INTERVAL)


async def update_agent_position_prices(db):
    """Update current prices for all open agent positions during market hours."""
    while True:
        try:
            if not is_market_open():
                await asyncio.sleep(POSITION_REFRESH_INTERVAL)
                continue

            # Get unique symbols to fetch
            symbols = await db.fetch(
                "SELECT DISTINCT symbol, exchange FROM agent_positions WHERE status = 'open'"
            )

            for sym in symbols:
                try:
                    # Try to get price from active_trades (already updated by signal monitor)
                    price_row = await db.fetchrow(
                        "SELECT current_price FROM active_trades WHERE ticker = $1 AND exchange = $2 ORDER BY last_updated DESC LIMIT 1",
                        sym["symbol"], sym["exchange"],
                    )
                    if price_row and price_row["current_price"]:
                        current_price = price_row["current_price"]
                    else:
                        continue  # Skip if no price available

                    # Update all positions for this symbol
                    await db.execute(
                        """UPDATE agent_positions
                           SET current_price = $1,
                               pnl_amount = CASE
                                   WHEN side = 'long' THEN ($1 - entry_price) * quantity
                                   ELSE (entry_price - $1) * quantity
                               END,
                               pnl_pct = CASE
                                   WHEN entry_price > 0 THEN
                                       CASE WHEN side = 'long'
                                            THEN (($1 - entry_price) / entry_price) * 100
                                            ELSE ((entry_price - $1) / entry_price) * 100
                                       END
                                   ELSE 0
                               END
                           WHERE symbol = $2 AND exchange = $3 AND status = 'open'""",
                        current_price, sym["symbol"], sym["exchange"],
                    )
                except Exception as e:
                    logger.debug("Error fetching price for %s: %s", sym["symbol"], e)

            logger.debug("Updated prices for %d agent position symbols", len(symbols))
        except Exception as e:
            logger.error("Error in position price update: %s", e)

        await asyncio.sleep(POSITION_REFRESH_INTERVAL)


def start_agent_background_tasks(db):
    """Launch all agent background tasks."""
    asyncio.create_task(record_profit_history(db))
    asyncio.create_task(prune_profit_history(db))
    asyncio.create_task(check_subscription_status(db))
    asyncio.create_task(update_agent_position_prices(db))
    logger.info("Started agent background tasks (profit recording, compaction, subscription checks, position updates)")
