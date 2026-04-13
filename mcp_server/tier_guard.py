"""
MKUMARAN Trading OS — Tier Enforcement Guard

Enforces subscription-based access control on API endpoints.
Each endpoint declares its required tier and daily usage limit.

Tiers: free < pro < elite < admin

Usage:
    from mcp_server.tier_guard import check_tier, TierError

    # In an API route:
    check_tier(user_email, feature="scanner_heatmap", tier_required="pro")
"""

import logging
from datetime import date

from mcp_server.db import SessionLocal

logger = logging.getLogger(__name__)

TIER_RANK = {"free": 0, "pro": 1, "elite": 2, "admin": 99}

# ── Feature definitions ──────────────────────────────────────
# feature_key → { min_tier, daily_limit_free, daily_limit_pro, daily_limit_elite }
# daily_limit = -1 means unlimited

FEATURE_LIMITS = {
    # Dashboard pages
    "overview":             {"min_tier": "free",  "free": -1, "pro": -1, "elite": -1},
    "market_movers":        {"min_tier": "free",  "free": 5,  "pro": -1, "elite": -1},
    "signal_view":          {"min_tier": "free",  "free": 3,  "pro": -1, "elite": -1},
    "signal_monitor":       {"min_tier": "pro",   "free": 0,  "pro": -1, "elite": -1},
    "active_trades":        {"min_tier": "free",  "free": 3,  "pro": -1, "elite": -1},
    "scanner_heatmap":      {"min_tier": "pro",   "free": 0,  "pro": -1, "elite": -1},

    # Trading
    "paper_trading":        {"min_tier": "free",  "free": 5,  "pro": -1, "elite": -1},
    "live_trading":         {"min_tier": "pro",   "free": 0,  "pro": -1, "elite": -1},
    "accuracy":             {"min_tier": "free",  "free": 3,  "pro": -1, "elite": -1},
    "watchlist_view":       {"min_tier": "free",  "free": 5,  "pro": 50, "elite": -1},
    "watchlist_add":        {"min_tier": "free",  "free": 5,  "pro": 50, "elite": -1},

    # Analysis
    "backtesting":          {"min_tier": "free",  "free": 1,  "pro": -1, "elite": -1},
    "pattern_engines":      {"min_tier": "pro",   "free": 0,  "pro": -1, "elite": -1},
    "wallstreet_ai":        {"min_tier": "pro",   "free": 0,  "pro": -1, "elite": -1},

    # Intelligence
    "news_macro":           {"min_tier": "free",  "free": 5,  "pro": -1, "elite": -1},
    "momentum":             {"min_tier": "pro",   "free": 0,  "pro": -1, "elite": -1},

    # Options
    "options_greeks":       {"min_tier": "free",  "free": 3,  "pro": -1, "elite": -1},
    "payoff_calc":          {"min_tier": "pro",   "free": 0,  "pro": -1, "elite": -1},

    # Settings
    "settings":             {"min_tier": "pro",   "free": 0,  "pro": -1, "elite": -1},
    "byok_keys":            {"min_tier": "pro",   "free": 0,  "pro": -1, "elite": -1},

    # API
    "api_access":           {"min_tier": "pro",   "free": 0,  "pro": 100,"elite": -1},

    # Telegram
    "telegram_signals":     {"min_tier": "free",  "free": 3,  "pro": -1, "elite": -1},
    "telegram_signal_cmd":  {"min_tier": "free",  "free": 2,  "pro": -1, "elite": -1},
}

# Paper trading capital per tier
PAPER_CAPITAL = {"free": 100_000, "pro": 500_000, "elite": 2_500_000}

# Watchlist max per tier
WATCHLIST_MAX = {"free": 5, "pro": 50, "elite": -1}


class TierError(Exception):
    """Raised when user doesn't have access to a feature."""
    def __init__(self, message: str, required_tier: str, current_tier: str, feature: str):
        self.message = message
        self.required_tier = required_tier
        self.current_tier = current_tier
        self.feature = feature
        super().__init__(message)


def _get_user_tier(user_email: str) -> str:
    """Get user's subscription tier from DB."""
    if not user_email:
        return "free"

    # Admin email bypass
    from mcp_server.config import settings
    if user_email == settings.ADMIN_EMAIL:
        return "admin"

    try:
        db = SessionLocal()
        try:
            from sqlalchemy import text
            row = db.execute(
                text("SELECT subscription_tier FROM app_users WHERE email = :e AND is_active = true"),
                {"e": user_email}
            ).first()
            if row:
                return row[0] or "free"
        except Exception:
            pass
        finally:
            db.close()
    except Exception:
        pass

    return "free"


def _get_daily_usage(user_email: str, feature: str) -> int:
    """Get today's usage count for a feature. Returns 0 on any error."""
    try:
        db = SessionLocal()
        try:
            from sqlalchemy import text
            today = date.today()
            # Simple approach — no dependency on usage_logs table existing
            row = db.execute(
                text("SELECT 1 FROM information_schema.tables WHERE table_name = 'usage_logs'")
            ).first()
            if not row:
                return 0
            result = db.execute(
                text("""SELECT COALESCE(SUM(count), 0) FROM usage_logs
                        WHERE feature = :f AND period_date = :d"""),
                {"f": f"{user_email}:{feature}", "d": today}
            ).first()
            return int(result[0]) if result else 0
        finally:
            db.close()
    except Exception:
        return 0


def _record_usage(user_email: str, feature: str):
    """Record a feature usage event. Silently fails if table missing."""
    try:
        db = SessionLocal()
        try:
            from sqlalchemy import text
            today = date.today()
            # Ensure table exists
            db.execute(text("""
                CREATE TABLE IF NOT EXISTS usage_logs (
                    id SERIAL PRIMARY KEY,
                    feature VARCHAR(100) NOT NULL,
                    count INTEGER DEFAULT 1,
                    period_date DATE NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            # Upsert
            existing = db.execute(
                text("SELECT id FROM usage_logs WHERE feature = :f AND period_date = :d"),
                {"f": f"{user_email}:{feature}", "d": today}
            ).first()
            if existing:
                db.execute(
                    text("UPDATE usage_logs SET count = count + 1 WHERE id = :id"),
                    {"id": existing[0]}
                )
            else:
                db.execute(
                    text("INSERT INTO usage_logs (feature, count, period_date) VALUES (:f, 1, :d)"),
                    {"f": f"{user_email}:{feature}", "d": today}
                )
            db.commit()
        finally:
            db.close()
    except Exception:
        pass


def check_tier(
    user_email: str,
    feature: str,
    record: bool = True,
) -> dict:
    """Check if user has access to a feature. Raises TierError if not.

    Args:
        user_email: User's email
        feature: Feature key from FEATURE_LIMITS
        record: Whether to record this as a usage event

    Returns:
        {"allowed": True, "tier": "pro", "remaining": 45, ...}

    Raises:
        TierError if access denied
    """
    tier = _get_user_tier(user_email)
    tier_rank = TIER_RANK.get(tier, 0)

    feat = FEATURE_LIMITS.get(feature)
    if not feat:
        # Unknown feature — allow by default
        return {"allowed": True, "tier": tier, "feature": feature, "remaining": -1}

    required = feat["min_tier"]
    required_rank = TIER_RANK.get(required, 0)

    # Admin bypasses everything
    if tier == "admin":
        if record:
            _record_usage(user_email, feature)
        return {"allowed": True, "tier": "admin", "feature": feature, "remaining": -1}

    # Tier check
    if tier_rank < required_rank:
        raise TierError(
            message=f"This feature requires {required.upper()} plan. You're on {tier.upper()}.",
            required_tier=required,
            current_tier=tier,
            feature=feature,
        )

    # Daily limit check
    daily_limit = feat.get(tier, 0)
    if daily_limit == -1:
        # Unlimited
        if record:
            _record_usage(user_email, feature)
        return {"allowed": True, "tier": tier, "feature": feature, "remaining": -1}

    if daily_limit == 0:
        raise TierError(
            message=f"This feature requires {required.upper()} plan.",
            required_tier=required,
            current_tier=tier,
            feature=feature,
        )

    # Count today's usage
    used = _get_daily_usage(user_email, feature)
    remaining = daily_limit - used

    if remaining <= 0:
        raise TierError(
            message=f"Daily limit reached ({daily_limit}/{tier.upper()} plan). Upgrade for unlimited access.",
            required_tier="pro",
            current_tier=tier,
            feature=feature,
        )

    if record:
        _record_usage(user_email, feature)

    return {
        "allowed": True,
        "tier": tier,
        "feature": feature,
        "remaining": remaining - 1,
        "daily_limit": daily_limit,
    }


def get_user_tier_info(user_email: str) -> dict:
    """Get comprehensive tier info for frontend."""
    tier = _get_user_tier(user_email)
    tier_rank = TIER_RANK.get(tier, 0)

    features = {}
    for feature, config in FEATURE_LIMITS.items():
        req_rank = TIER_RANK.get(config["min_tier"], 0)
        limit = config.get(tier, 0)
        features[feature] = {
            "accessible": tier == "admin" or tier_rank >= req_rank,
            "daily_limit": -1 if tier == "admin" else limit,
            "min_tier": config["min_tier"],
        }

    return {
        "tier": tier,
        "paper_capital": PAPER_CAPITAL.get(tier, 100_000),
        "watchlist_max": WATCHLIST_MAX.get(tier, 5),
        "features": features,
    }
