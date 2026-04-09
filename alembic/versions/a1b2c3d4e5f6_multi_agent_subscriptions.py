"""multi_agent_subscriptions

Add multi-agent social trading, subscription billing, and India-only tables.

Revision ID: a1b2c3d4e5f6
Revises: 44cb7fb01bfb
Create Date: 2026-04-09 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "44cb7fb01bfb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. TRADING AGENTS ─────────────────────────────────────
    op.create_table(
        "agents",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(50), nullable=False, unique=True),
        sa.Column("token", sa.String(64), nullable=True, unique=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_hash", sa.String(128), nullable=False),
        sa.Column("salt", sa.String(32), nullable=False),
        sa.Column("agent_type", sa.String(20), server_default="external"),  # system, external, human
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("avatar_url", sa.String(255), nullable=True),
        sa.Column("points", sa.Integer(), server_default="0"),
        sa.Column("cash", sa.Numeric(14, 2), server_default="1000000"),  # ₹10L paper capital
        sa.Column("deposited", sa.Numeric(14, 2), server_default="0"),
        sa.Column("reputation_score", sa.Integer(), server_default="0"),
        sa.Column("win_rate", sa.Numeric(5, 2), server_default="0"),
        sa.Column("total_trades", sa.Integer(), server_default="0"),
        sa.Column("user_id", sa.Integer(), nullable=True),  # FK to users table if human agent
        sa.Column("subscription_tier", sa.String(20), server_default="free"),
        sa.Column("tier_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_agents_name", "agents", ["name"])
    op.create_index("idx_agents_token", "agents", ["token"])
    op.create_index("idx_agents_user_id", "agents", ["user_id"])
    op.create_index("idx_agents_type", "agents", ["agent_type"])

    # ── 2. AGENT SIGNALS (social feed) ────────────────────────
    op.create_table(
        "agent_signals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("signal_type", sa.String(20), nullable=False),  # trade, analysis, discussion
        sa.Column("symbol", sa.String(30), nullable=True),
        sa.Column("exchange", sa.String(10), nullable=True),  # NSE, BSE, MCX, CDS, NFO
        sa.Column("direction", sa.String(10), nullable=True),  # LONG, SHORT, BUY, SELL
        sa.Column("entry_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("stop_loss", sa.Numeric(12, 2), nullable=True),
        sa.Column("target", sa.Numeric(12, 2), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("rrr", sa.Numeric(5, 2), nullable=True),
        sa.Column("ai_confidence", sa.Numeric(5, 2), nullable=True),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("tags", sa.String(200), nullable=True),
        sa.Column("pattern", sa.String(50), nullable=True),
        sa.Column("timeframe", sa.String(10), nullable=True),
        sa.Column("status", sa.String(20), server_default="OPEN"),  # OPEN, WIN, LOSS, EXPIRED, CLOSED
        sa.Column("pnl_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("pnl_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("exit_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("copied_from_id", sa.Integer(), nullable=True),  # FK to agent_signals.id if copied
        sa.Column("internal_signal_id", sa.Integer(), nullable=True),  # FK to signals.id if from MWA
        sa.Column("accepted_reply_id", sa.Integer(), nullable=True),
        sa.Column("follower_count", sa.Integer(), server_default="0"),
        sa.Column("reply_count", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_agent_signals_agent", "agent_signals", ["agent_id"])
    op.create_index("idx_agent_signals_type", "agent_signals", ["signal_type"])
    op.create_index("idx_agent_signals_symbol", "agent_signals", ["symbol"])
    op.create_index("idx_agent_signals_exchange", "agent_signals", ["exchange"])
    op.create_index("idx_agent_signals_created", "agent_signals", ["created_at"])
    op.create_index("idx_agent_signals_agent_type", "agent_signals", ["agent_id", "signal_type"])

    # ── 3. SIGNAL REPLIES ─────────────────────────────────────
    op.create_table(
        "signal_replies",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("signal_id", sa.Integer(), sa.ForeignKey("agent_signals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("accepted", sa.Boolean(), server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_signal_replies_signal", "signal_replies", ["signal_id"])
    op.create_index("idx_signal_replies_agent", "signal_replies", ["agent_id"])

    # ── 4. SUBSCRIPTIONS (follow relationships) ───────────────
    op.create_table(
        "agent_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("leader_id", sa.Integer(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("follower_id", sa.Integer(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("copy_ratio", sa.Numeric(5, 2), server_default="1.0"),  # position sizing ratio
        sa.Column("auto_copy", sa.Boolean(), server_default="true"),
        sa.Column("status", sa.String(20), server_default="active"),  # active, inactive
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("leader_id", "follower_id", name="uq_agent_subscription"),
    )
    op.create_index("idx_agent_subs_leader", "agent_subscriptions", ["leader_id"])
    op.create_index("idx_agent_subs_follower", "agent_subscriptions", ["follower_id"])

    # ── 5. AGENT POSITIONS (paper + copied) ───────────────────
    op.create_table(
        "agent_positions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("leader_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("symbol", sa.String(30), nullable=False),
        sa.Column("exchange", sa.String(10), server_default="NSE"),
        sa.Column("side", sa.String(10), nullable=False),  # long, short
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("entry_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("current_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("stop_loss", sa.Numeric(12, 2), nullable=True),
        sa.Column("target", sa.Numeric(12, 2), nullable=True),
        sa.Column("pnl_amount", sa.Numeric(12, 2), server_default="0"),
        sa.Column("pnl_pct", sa.Numeric(8, 4), server_default="0"),
        sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(10), server_default="open"),  # open, closed
    )
    op.create_index("idx_agent_positions_agent", "agent_positions", ["agent_id"])
    op.create_index("idx_agent_positions_symbol", "agent_positions", ["symbol", "exchange"])
    op.create_index("idx_agent_positions_status", "agent_positions", ["status"])

    # ── 6. AGENT PROFIT HISTORY (time-series, compacted) ──────
    op.create_table(
        "agent_profit_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("total_value", sa.Numeric(14, 2), nullable=False),
        sa.Column("cash", sa.Numeric(14, 2), nullable=False),
        sa.Column("position_value", sa.Numeric(14, 2), nullable=False),
        sa.Column("profit", sa.Numeric(14, 2), nullable=False),
        sa.Column("profit_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_agent_profit_agent", "agent_profit_history", ["agent_id"])
    op.create_index("idx_agent_profit_recorded", "agent_profit_history", ["recorded_at"])
    op.create_index("idx_agent_profit_agent_recorded", "agent_profit_history", ["agent_id", "recorded_at"])

    # ── 7. AGENT MESSAGES (inbox/notifications) ───────────────
    op.create_table(
        "agent_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("type", sa.String(30), nullable=False),  # new_follower, signal_copied, trade_update, etc.
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("data_json", postgresql.JSONB(), nullable=True),
        sa.Column("read", sa.Boolean(), server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_agent_messages_agent", "agent_messages", ["agent_id"])
    op.create_index("idx_agent_messages_unread", "agent_messages", ["agent_id", "read"])

    # ── 8. SUBSCRIPTION PLANS ─────────────────────────────────
    op.create_table(
        "subscription_plans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("slug", sa.String(30), nullable=False, unique=True),
        sa.Column("price_monthly", sa.Integer(), nullable=False),  # INR paise (99900 = ₹999)
        sa.Column("price_yearly", sa.Integer(), nullable=False),
        sa.Column("gst_pct", sa.Numeric(4, 2), server_default="18.00"),
        sa.Column("features", postgresql.JSONB(), nullable=True),
        sa.Column("limits", postgresql.JSONB(), nullable=True),
        sa.Column("razorpay_plan_id_monthly", sa.String(50), nullable=True),
        sa.Column("razorpay_plan_id_yearly", sa.String(50), nullable=True),
        sa.Column("display_order", sa.Integer(), server_default="0"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    # ── 9. USER SUBSCRIPTIONS ─────────────────────────────────
    op.create_table(
        "user_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=True),  # FK to users if exists
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("subscription_plans.id"), nullable=False),
        sa.Column("razorpay_subscription_id", sa.String(50), nullable=True),
        sa.Column("razorpay_customer_id", sa.String(50), nullable=True),
        sa.Column("billing_cycle", sa.String(10), server_default="monthly"),  # monthly, yearly
        sa.Column("status", sa.String(20), server_default="trialing"),
        # active, past_due, cancelled, trialing, expired
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trial_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_user_subs_user", "user_subscriptions", ["user_id"])
    op.create_index("idx_user_subs_agent", "user_subscriptions", ["agent_id"])
    op.create_index("idx_user_subs_status", "user_subscriptions", ["status"])
    op.create_index("idx_user_subs_razorpay", "user_subscriptions", ["razorpay_subscription_id"])

    # ── 10. USAGE LOGS (metering) ─────────────────────────────
    op.create_table(
        "usage_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("feature", sa.String(50), nullable=False),
        # signal_view, scanner_run, backtest_run, api_call, etc.
        sa.Column("count", sa.Integer(), server_default="1"),
        sa.Column("period_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_usage_user_feature", "usage_logs", ["user_id", "feature", "period_date"])
    op.create_index("idx_usage_agent_feature", "usage_logs", ["agent_id", "feature", "period_date"])

    # ── 11. INVOICES ──────────────────────────────────────────
    op.create_table(
        "invoices",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("subscription_id", sa.Integer(), sa.ForeignKey("user_subscriptions.id"), nullable=True),
        sa.Column("amount", sa.Integer(), nullable=False),  # paise
        sa.Column("gst_amount", sa.Integer(), server_default="0"),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), server_default="INR"),
        sa.Column("razorpay_invoice_id", sa.String(50), nullable=True),
        sa.Column("razorpay_payment_id", sa.String(50), nullable=True),
        sa.Column("status", sa.String(20), server_default="pending"),  # pending, paid, failed
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_invoices_user", "invoices", ["user_id"])
    op.create_index("idx_invoices_razorpay", "invoices", ["razorpay_payment_id"])

    # ── 12. NSE HOLIDAYS ──────────────────────────────────────
    op.create_table(
        "market_holidays",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("date", sa.Date(), nullable=False, unique=True),
        sa.Column("exchange", sa.String(10), server_default="NSE"),
        sa.Column("description", sa.String(100), nullable=True),
        sa.Column("year", sa.Integer(), nullable=False),
    )
    op.create_index("idx_holidays_date", "market_holidays", ["date"])
    op.create_index("idx_holidays_year", "market_holidays", ["year"])

    # ── 13. SEED: Subscription Plans ──────────────────────────
    op.execute("""
        INSERT INTO subscription_plans (name, slug, price_monthly, price_yearly, features, limits, display_order) VALUES
        ('Free', 'free', 0, 0,
         '{"dashboard": "basic", "signals_view": true, "scanner": "direction_only", "paper_trading": true}'::jsonb,
         '{"daily_signals": 3, "agent_slots": 1, "follow_leaders": 1, "backtest_strategies": 1, "backtest_days": 30, "api_calls": 0, "paper_capital": 100000}'::jsonb,
         1),
        ('Pro', 'pro', 99900, 999900,
         '{"dashboard": "full", "signals_view": true, "scanner": "full_heatmap", "paper_trading": true, "live_trading": true, "options_full": true, "signal_monitor": true, "telegram_alerts": true}'::jsonb,
         '{"daily_signals": -1, "agent_slots": 5, "follow_leaders": 5, "backtest_strategies": -1, "backtest_days": 365, "api_calls": 100, "paper_capital": 500000}'::jsonb,
         2),
        ('Elite', 'elite', 299900, 2999900,
         '{"dashboard": "full", "signals_view": true, "scanner": "full_auto_execute", "paper_trading": true, "live_trading": true, "options_full": true, "signal_monitor": true, "telegram_alerts": true, "api_unlimited": true, "priority_support": true}'::jsonb,
         '{"daily_signals": -1, "agent_slots": -1, "follow_leaders": -1, "backtest_strategies": -1, "backtest_days": -1, "api_calls": -1, "paper_capital": 2500000}'::jsonb,
         3);
    """)


def downgrade() -> None:
    op.drop_table("market_holidays")
    op.drop_table("invoices")
    op.drop_table("usage_logs")
    op.drop_table("user_subscriptions")
    op.drop_table("subscription_plans")
    op.drop_table("agent_messages")
    op.drop_table("agent_profit_history")
    op.drop_table("agent_positions")
    op.drop_table("agent_subscriptions")
    op.drop_table("signal_replies")
    op.drop_table("agent_signals")
    op.drop_table("agents")
