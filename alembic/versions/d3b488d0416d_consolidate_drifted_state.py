"""consolidate_drifted_state

Reconciles the schema drift accumulated outside Alembic. Captures every
table and column previously created by runtime escape hatches (create_all,
_add_missing_columns, auth_providers._ensure_app_users_table, tier_guard
inline CREATE TABLE) into formal migration history.

Generated against a simulated prod DB on 2026-04-22 by comparing:
  - prod-sim:     schema.sql + init_db() + _ensure_app_users_table + usage_logs
  - alembic-only: `alembic upgrade head` on a fresh DB

See scripts/simulate_prod_schema.sh for the simulation.

Every DDL statement uses IF NOT EXISTS semantics so this migration is:
  - a no-op when run against a prod DB that already has these objects
  - a full create when run against a fresh dev DB

Downgrade: NotImplementedError. Rolling back a consolidation is effectively
a restore-from-backup operation, not an Alembic operation.

Phase 2 of docs/SCHEMA_CONSOLIDATION_PLAN.md.

Revision ID: d3b488d0416d
Revises: c3d4e5f6a7b8
Create Date: 2026-04-22
"""
from typing import Sequence, Union

from alembic import op


revision: str = "d3b488d0416d"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── Column specs for drifted tables ─────────────────────────────────────
# SQL-string form (not sa.Column) so we can use ADD COLUMN IF NOT EXISTS,
# which Alembic's op.add_column doesn't expose natively.

SIGNALS_DRIFT_COLUMNS: list[tuple[str, str]] = [
    ("entry_rsi", "NUMERIC(6,2)"),
    ("entry_adx", "NUMERIC(6,2)"),
    ("entry_atr_pct", "NUMERIC(6,3)"),
    ("entry_volume_ratio", "NUMERIC(7,3)"),
    ("entry_vwap_dev", "NUMERIC(7,3)"),
    ("entry_momentum", "NUMERIC(7,3)"),
    ("entry_macd_hist", "NUMERIC(10,4)"),
    ("entry_bb_width", "NUMERIC(7,3)"),
    ("entry_regime", "VARCHAR(20)"),
    ("entry_mwa_bull_pct", "NUMERIC(5,1)"),
    ("entry_mwa_bear_pct", "NUMERIC(5,1)"),
    ("scanner_list", "JSONB"),
    ("feature_vector", "JSONB"),
    ("loss_probability", "NUMERIC(5,3)"),
    ("predictor_version", "VARCHAR(20)"),
    ("suppressed", "BOOLEAN DEFAULT FALSE"),
    ("suppression_reason", "TEXT"),
    ("rca_json", "JSONB"),
    ("option_strategy", "VARCHAR(30)"),
    ("option_tradingsymbol", "VARCHAR(50)"),
    ("option_strike", "NUMERIC(12,2)"),
    ("option_expiry", "DATE"),
    ("option_type", "VARCHAR(2)"),
    ("option_premium", "NUMERIC(10,2)"),
    ("option_premium_sl", "NUMERIC(10,2)"),
    ("option_premium_target", "NUMERIC(10,2)"),
    ("option_lot_size", "INTEGER"),
    ("option_contracts", "INTEGER DEFAULT 1"),
    ("option_iv_rank", "NUMERIC(5,1)"),
    ("option_delta", "NUMERIC(6,4)"),
    ("option_gamma", "NUMERIC(8,6)"),
    ("option_theta", "NUMERIC(8,2)"),
    ("option_vega", "NUMERIC(8,2)"),
    ("option_iv", "NUMERIC(6,4)"),
    ("option_is_spread", "BOOLEAN DEFAULT FALSE"),
    ("option_net_premium", "NUMERIC(10,2)"),
    ("option_legs", "JSONB"),
]

OUTCOMES_DRIFT_COLUMNS: list[tuple[str, str]] = [
    ("exit_reason_detail", "TEXT"),
    ("pattern_invalidated", "BOOLEAN"),
    ("invalidation_reason", "VARCHAR(100)"),
    ("max_adverse_excursion", "NUMERIC(7,3)"),
    ("max_favorable_excursion", "NUMERIC(7,3)"),
    ("option_exit_premium", "NUMERIC(10,2)"),
    ("option_pnl_per_lot", "NUMERIC(12,2)"),
    ("option_pnl_pct", "NUMERIC(7,2)"),
]

APP_USERS_DRIFT_COLUMNS: list[tuple[str, str]] = [
    # Exist in auth_providers._ensure_app_users_table but not in the
    # alembic migration c3d4e5f6a7b8_users_registration.
    ("telegram_chat_id", "VARCHAR(20)"),
    ("alert_enabled", "BOOLEAN DEFAULT TRUE"),
    ("subscription_tier", "VARCHAR(20) DEFAULT 'free'"),
    ("daily_signal_count", "INTEGER DEFAULT 0"),
    ("last_signal_date", "DATE"),
]


def _add_columns(table: str, cols: list[tuple[str, str]]) -> None:
    """ADD COLUMN IF NOT EXISTS for each spec. Postgres 9.6+."""
    for col_name, col_type in cols:
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
        )


def upgrade() -> None:
    # ── 1. Tables previously created only by create_all() ─────────────────

    op.execute("""
        CREATE TABLE IF NOT EXISTS postmortems (
            id SERIAL PRIMARY KEY,
            signal_id INTEGER REFERENCES signals(id),
            created_at TIMESTAMP DEFAULT NOW(),
            outcome VARCHAR(10),
            root_cause TEXT,
            contributing_factors JSONB,
            rule_checks JSONB,
            suggested_filter TEXT,
            similar_signals JSONB,
            claude_narrative TEXT,
            confidence_score NUMERIC(5,2)
        )
    """)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_postmortems_signal_id "
        "ON postmortems (signal_id)"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS adaptive_rules (
            id SERIAL PRIMARY KEY,
            rule_key VARCHAR(100),
            description TEXT,
            condition_json JSONB,
            action VARCHAR(30),
            action_params JSONB,
            sample_size INTEGER DEFAULT 0,
            historical_hit_rate_before NUMERIC(5,2),
            historical_hit_rate_after NUMERIC(5,2),
            estimated_losses_prevented INTEGER DEFAULT 0,
            estimated_wins_lost INTEGER DEFAULT 0,
            active BOOLEAN DEFAULT FALSE,
            auto_generated BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW(),
            activated_at TIMESTAMP,
            last_fired_at TIMESTAMP,
            fire_count INTEGER DEFAULT 0
        )
    """)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_adaptive_rules_rule_key "
        "ON adaptive_rules (rule_key)"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS scanner_reviews (
            id SERIAL PRIMARY KEY,
            review_date DATE NOT NULL,
            market_direction VARCHAR(15),
            overall_hit_rate NUMERIC(5,1),
            scanner_hit_rates JSONB,
            missed_opportunities JSONB,
            false_positives JSONB,
            segment_performance JSONB,
            chain_accuracy JSONB,
            promoted_performance JSONB,
            best_scanners JSONB,
            worst_scanners JSONB,
            review_payload JSONB,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_scanner_reviews_review_date "
        "ON scanner_reviews (review_date)"
    )

    # ── 2. Tables previously created only by raw SQL in app code ──────────

    # From tier_guard.py:151 — tier-gated feature usage tracking.
    op.execute("""
        CREATE TABLE IF NOT EXISTS usage_logs (
            id SERIAL PRIMARY KEY,
            feature VARCHAR(100) NOT NULL,
            count INTEGER DEFAULT 1,
            period_date DATE NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    # ── 3. Drifted columns on existing tables ─────────────────────────────

    _add_columns("signals", SIGNALS_DRIFT_COLUMNS)
    _add_columns("outcomes", OUTCOMES_DRIFT_COLUMNS)
    _add_columns("app_users", APP_USERS_DRIFT_COLUMNS)

    # `active_trades` and `watchlist` drift columns (exchange, asset_class,
    # timeframe, alert_sent) are already captured by 44cb7fb01bfb_initial_schema,
    # so the diff shows no gap for those.

    # ── 4. Drifted indexes ────────────────────────────────────────────────

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_app_users_telegram "
        "ON app_users (telegram_chat_id)"
    )


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrading this consolidating migration is not supported. "
        "If you need to roll back, restore the database from backup."
    )
