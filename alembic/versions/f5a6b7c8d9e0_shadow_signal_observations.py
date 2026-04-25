"""shadow_signal_observations — POS 5 EMA shadow tracking table

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-04-25

Stores every shadow signal observation (strategy fired in shadow mode,
weight=0) alongside its outcome — whether the shadow signal's SL or
target was hit after the fact. Queryable for 30-day evaluation.

Columns:
  - engine          which shadow strategy fired (e.g. "pos_5ema")
  - ticker / direction / timeframe
  - shadow_entry / shadow_sl / shadow_target  — the levels that would
                                                have been traded
  - shadow_confidence                          — engine confidence 0-1
  - primary_direction                          — what the primary engine said
  - agreed                                     — did shadow agree with primary?
  - observed_at                               — when the shadow fired
  - resolved_at / outcome / exit_price / pnl_pct
                                               — filled by outcome resolver
"""

from alembic import op
import sqlalchemy as sa


revision = "f5a6b7c8d9e0"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shadow_signal_observations",
        sa.Column("id",                 sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("engine",             sa.String(30), nullable=False, index=True),
        sa.Column("ticker",             sa.String(30), nullable=False, index=True),
        sa.Column("exchange",           sa.String(10), default="NSE"),
        sa.Column("direction",          sa.String(10), nullable=False),
        sa.Column("timeframe",          sa.String(10), default="1D"),

        # Levels the shadow strategy would have used
        sa.Column("shadow_entry",       sa.Numeric(12, 2)),
        sa.Column("shadow_sl",          sa.Numeric(12, 2)),
        sa.Column("shadow_target",      sa.Numeric(12, 2)),
        sa.Column("shadow_confidence",  sa.Numeric(5, 3)),

        # Primary signal context (for agreement analysis)
        sa.Column("primary_direction",  sa.String(10)),
        sa.Column("primary_entry",      sa.Numeric(12, 2)),
        sa.Column("agreed",             sa.Boolean),

        # Source signal linkage (if the MWA scan produced a primary signal)
        sa.Column("primary_signal_id",  sa.Integer, sa.ForeignKey("signals.id", ondelete="SET NULL"), nullable=True, index=True),

        # Lifecycle
        sa.Column("observed_at",        sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at",        sa.DateTime),
        sa.Column("outcome",            sa.String(10)),    # WIN / LOSS / EXPIRED
        sa.Column("exit_price",         sa.Numeric(12, 2)),
        sa.Column("pnl_pct",            sa.Numeric(7, 3)),
        sa.Column("resolution_reason",  sa.String(20)),    # TARGET / STOPLOSS / TIMEOUT

        sa.Index("ix_shadow_engine_ticker", "engine", "ticker"),
        sa.Index("ix_shadow_unresolved", "resolved_at"),  # null = unresolved
    )


def downgrade() -> None:
    op.drop_table("shadow_signal_observations")
