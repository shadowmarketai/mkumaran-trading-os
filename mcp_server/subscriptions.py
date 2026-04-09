"""Subscription tier management and Razorpay billing for MKUMARAN Trading OS.

Tiers: Free / Pro (₹999/mo) / Elite (₹2,999/mo)
Payment: Razorpay (UPI, cards, net banking)
GST: 18% included in displayed price
"""

import hmac
import hashlib
import logging
import os
from datetime import timedelta

from mcp_server.india_market import now_ist

logger = logging.getLogger(__name__)

# ── Razorpay Config ───────────────────────────────────────────
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")

# ── Tier Limits ───────────────────────────────────────────────
TIER_LIMITS = {
    "free": {
        "daily_signals": 3,
        "agent_slots": 1,
        "follow_leaders": 1,
        "backtest_strategies": 1,
        "backtest_days": 30,
        "api_calls": 0,
        "paper_capital": 100_000,
        "live_trading": False,
        "scanner_full": False,
        "options_full": False,
        "telegram_alerts": False,
    },
    "pro": {
        "daily_signals": -1,  # unlimited
        "agent_slots": 5,
        "follow_leaders": 5,
        "backtest_strategies": -1,
        "backtest_days": 365,
        "api_calls": 100,
        "paper_capital": 500_000,
        "live_trading": True,
        "scanner_full": True,
        "options_full": True,
        "telegram_alerts": True,
    },
    "elite": {
        "daily_signals": -1,
        "agent_slots": -1,
        "follow_leaders": -1,
        "backtest_strategies": -1,
        "backtest_days": -1,
        "api_calls": -1,
        "paper_capital": 2_500_000,
        "live_trading": True,
        "scanner_full": True,
        "options_full": True,
        "telegram_alerts": True,
    },
}

TRIAL_DAYS = 7


# ── Tier Check Functions ─────────────────────────────────────

def get_tier_limits(tier: str) -> dict:
    """Get limits for a subscription tier."""
    return TIER_LIMITS.get(tier, TIER_LIMITS["free"])


def check_feature_access(tier: str, feature: str) -> bool:
    """Check if a tier has access to a specific feature."""
    limits = get_tier_limits(tier)
    value = limits.get(feature)
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0  # 0 = no access, -1 = unlimited, >0 = limited
    return False


def check_usage_limit(tier: str, feature: str, current_usage: int) -> tuple[bool, int]:
    """Check if usage is within tier limits. Returns (allowed, remaining)."""
    limits = get_tier_limits(tier)
    limit = limits.get(feature, 0)

    if limit == -1:  # unlimited
        return True, -1
    if limit == 0:  # no access
        return False, 0

    remaining = limit - current_usage
    return remaining > 0, max(0, remaining)


# ── Subscription Management ──────────────────────────────────

async def get_user_subscription(db, user_id: int = None, agent_id: int = None) -> dict:
    """Get active subscription for a user or agent."""
    if agent_id:
        row = await db.fetchrow(
            """SELECT us.*, sp.name AS plan_name, sp.slug AS plan_slug
               FROM user_subscriptions us
               JOIN subscription_plans sp ON sp.id = us.plan_id
               WHERE us.agent_id = $1 AND us.status IN ('active', 'trialing')
               ORDER BY us.created_at DESC LIMIT 1""",
            agent_id,
        )
    elif user_id:
        row = await db.fetchrow(
            """SELECT us.*, sp.name AS plan_name, sp.slug AS plan_slug
               FROM user_subscriptions us
               JOIN subscription_plans sp ON sp.id = us.plan_id
               WHERE us.user_id = $1 AND us.status IN ('active', 'trialing')
               ORDER BY us.created_at DESC LIMIT 1""",
            user_id,
        )
    else:
        return {"tier": "free", "status": "none"}

    if not row:
        return {"tier": "free", "status": "none"}

    return {
        "subscription_id": row["id"],
        "tier": row["plan_slug"],
        "plan_name": row["plan_name"],
        "status": row["status"],
        "billing_cycle": row["billing_cycle"],
        "current_period_start": row["current_period_start"].isoformat() if row["current_period_start"] else None,
        "current_period_end": row["current_period_end"].isoformat() if row["current_period_end"] else None,
        "trial_end": row["trial_end"].isoformat() if row["trial_end"] else None,
    }


async def get_plans(db) -> list[dict]:
    """Get all active subscription plans."""
    rows = await db.fetch(
        "SELECT * FROM subscription_plans WHERE is_active = true ORDER BY display_order ASC"
    )
    result = []
    for row in rows:
        d = dict(row)
        # Convert paise to rupees for display
        d["price_monthly_inr"] = d["price_monthly"] / 100
        d["price_yearly_inr"] = d["price_yearly"] / 100
        d["gst_included"] = True
        result.append(d)
    return result


async def create_subscription(
    db,
    user_id: int | None,
    agent_id: int | None,
    plan_slug: str,
    billing_cycle: str = "monthly",
    razorpay_subscription_id: str | None = None,
    razorpay_customer_id: str | None = None,
) -> dict:
    """Create a new subscription."""
    plan = await db.fetchrow(
        "SELECT id, slug FROM subscription_plans WHERE slug = $1 AND is_active = true",
        plan_slug,
    )
    if not plan:
        raise ValueError(f"Plan '{plan_slug}' not found")

    now = now_ist()
    period_end = now + timedelta(days=30 if billing_cycle == "monthly" else 365)
    trial_end = now + timedelta(days=TRIAL_DAYS) if plan_slug != "free" else None
    status = "trialing" if trial_end else "active"

    sub_id = await db.fetchval(
        """INSERT INTO user_subscriptions
           (user_id, agent_id, plan_id, razorpay_subscription_id, razorpay_customer_id,
            billing_cycle, status, current_period_start, current_period_end, trial_end, created_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW())
           RETURNING id""",
        user_id, agent_id, plan["id"], razorpay_subscription_id, razorpay_customer_id,
        billing_cycle, status, now, period_end, trial_end,
    )

    # Update agent tier
    if agent_id:
        await db.execute(
            "UPDATE agents SET subscription_tier = $1, tier_expires_at = $2, updated_at = NOW() WHERE id = $3",
            plan_slug, period_end, agent_id,
        )

    logger.info("Subscription created: %s plan=%s cycle=%s", user_id or agent_id, plan_slug, billing_cycle)
    return {
        "subscription_id": sub_id,
        "plan": plan_slug,
        "status": status,
        "trial_end": trial_end.isoformat() if trial_end else None,
        "period_end": period_end.isoformat(),
    }


async def cancel_subscription(db, subscription_id: int) -> dict:
    """Cancel a subscription (effective at period end)."""
    await db.execute(
        "UPDATE user_subscriptions SET status = 'cancelled', cancelled_at = NOW() WHERE id = $1",
        subscription_id,
    )
    return {"status": "cancelled", "effective": "end_of_period"}


# ── Razorpay Webhook Handling ─────────────────────────────────

def verify_razorpay_signature(body: bytes, signature: str) -> bool:
    """Verify Razorpay webhook signature."""
    if not RAZORPAY_WEBHOOK_SECRET:
        logger.warning("RAZORPAY_WEBHOOK_SECRET not set — skipping signature verification")
        return True

    expected = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


async def handle_razorpay_webhook(db, event: str, payload: dict) -> dict:
    """Handle Razorpay webhook events."""
    if event == "subscription.activated":
        sub_id = payload.get("subscription", {}).get("id")
        if sub_id:
            await db.execute(
                "UPDATE user_subscriptions SET status = 'active' WHERE razorpay_subscription_id = $1",
                sub_id,
            )
        return {"handled": True}

    elif event == "subscription.charged":
        sub_id = payload.get("subscription", {}).get("id")
        payment_id = payload.get("payment", {}).get("entity", {}).get("id")
        amount = payload.get("payment", {}).get("entity", {}).get("amount", 0)

        if sub_id:
            # Extend period
            sub = await db.fetchrow(
                "SELECT id, user_id, agent_id FROM user_subscriptions WHERE razorpay_subscription_id = $1",
                sub_id,
            )
            if sub:
                now = now_ist()
                new_end = now + timedelta(days=30)
                await db.execute(
                    """UPDATE user_subscriptions
                       SET status = 'active', current_period_start = $1, current_period_end = $2
                       WHERE id = $3""",
                    now, new_end, sub["id"],
                )

                # Create invoice
                gst = int(amount * 18 / 118)  # Extract GST from inclusive price
                base = amount - gst
                await db.execute(
                    """INSERT INTO invoices (user_id, subscription_id, amount, gst_amount, total,
                                             razorpay_payment_id, status, paid_at, created_at)
                       VALUES ($1, $2, $3, $4, $5, $6, 'paid', NOW(), NOW())""",
                    sub["user_id"], sub["id"], base, gst, amount, payment_id,
                )

        return {"handled": True}

    elif event == "subscription.cancelled":
        sub_id = payload.get("subscription", {}).get("id")
        if sub_id:
            await db.execute(
                "UPDATE user_subscriptions SET status = 'cancelled', cancelled_at = NOW() WHERE razorpay_subscription_id = $1",
                sub_id,
            )
        return {"handled": True}

    elif event == "payment.failed":
        sub_id = payload.get("payment", {}).get("entity", {}).get("subscription_id")
        if sub_id:
            await db.execute(
                "UPDATE user_subscriptions SET status = 'past_due' WHERE razorpay_subscription_id = $1",
                sub_id,
            )
        return {"handled": True}

    return {"handled": False, "event": event}


# ── Usage Metering ────────────────────────────────────────────

async def record_usage(db, feature: str, user_id: int = None, agent_id: int = None) -> None:
    """Record a feature usage event."""
    today = now_ist().date()
    await db.execute(
        """INSERT INTO usage_logs (user_id, agent_id, feature, count, period_date, created_at)
           VALUES ($1, $2, $3, 1, $4, NOW())
           ON CONFLICT DO NOTHING""",
        user_id, agent_id, feature, today,
    )
    # Try upsert (Postgres-specific)
    await db.execute(
        """UPDATE usage_logs SET count = count + 1
           WHERE user_id IS NOT DISTINCT FROM $1
             AND agent_id IS NOT DISTINCT FROM $2
             AND feature = $3
             AND period_date = $4""",
        user_id, agent_id, feature, today,
    )


async def get_usage(db, feature: str, user_id: int = None, agent_id: int = None) -> int:
    """Get today's usage count for a feature."""
    today = now_ist().date()
    count = await db.fetchval(
        """SELECT COALESCE(SUM(count), 0) FROM usage_logs
           WHERE user_id IS NOT DISTINCT FROM $1
             AND agent_id IS NOT DISTINCT FROM $2
             AND feature = $3
             AND period_date = $4""",
        user_id, agent_id, feature, today,
    )
    return count or 0


async def check_and_record_usage(
    db, tier: str, feature: str, user_id: int = None, agent_id: int = None,
) -> tuple[bool, str]:
    """Check tier limit, record usage if allowed. Returns (allowed, message)."""
    current = await get_usage(db, feature, user_id, agent_id)
    allowed, remaining = check_usage_limit(tier, feature, current)

    if not allowed:
        if remaining == 0 and get_tier_limits(tier).get(feature, 0) == 0:
            return False, f"Feature '{feature}' requires Pro or Elite subscription"
        return False, f"Daily limit reached for '{feature}'. Upgrade to increase limits."

    await record_usage(db, feature, user_id, agent_id)
    return True, f"OK (remaining: {'unlimited' if remaining == -1 else remaining - 1})"
