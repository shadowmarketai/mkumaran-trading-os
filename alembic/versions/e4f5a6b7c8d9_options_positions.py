"""options_positions — short strangle / iron condor position tracking

Revision ID: e4f5a6b7c8d9
Revises: d3b488d0416d
Create Date: 2026-04-25

Adds options_seller_positions table for tracking open short
strangle / iron condor positions across all 6 instruments:
  BANKNIFTY / NIFTY / MIDCPNIFTY / FINNIFTY (NSE NFO)
  SENSEX / BANKEX (BSE BFO)

Each position stores:
  - instrument + expiry + structure type
  - four leg strikes + premiums + deltas at entry
  - net credit received + max loss (iron condor only)
  - live Greeks snapshot (updated by position_manager)
  - current P&L + status

Also adds options_seller_adjustments log (one row per rule fired).
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "e4f5a6b7c8d9"
down_revision = "d3b488d0416d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "options_seller_positions",
        sa.Column("id",            sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("instrument",    sa.String(20), nullable=False, index=True),
        sa.Column("expiry_date",   sa.Date, nullable=False),
        sa.Column("structure",     sa.String(20), nullable=False, default="IRON_CONDOR"),
        sa.Column("status",        sa.String(20), nullable=False, default="OPEN"),
        # Short legs
        sa.Column("short_call_strike",  sa.Numeric(10, 2)),
        sa.Column("short_put_strike",   sa.Numeric(10, 2)),
        sa.Column("short_call_premium", sa.Numeric(10, 2)),
        sa.Column("short_put_premium",  sa.Numeric(10, 2)),
        sa.Column("short_call_delta",   sa.Numeric(6, 4)),
        sa.Column("short_put_delta",    sa.Numeric(6, 4)),
        # Long legs (iron condor wings)
        sa.Column("long_call_strike",   sa.Numeric(10, 2)),
        sa.Column("long_put_strike",    sa.Numeric(10, 2)),
        sa.Column("long_call_premium",  sa.Numeric(10, 2)),
        sa.Column("long_put_premium",   sa.Numeric(10, 2)),
        # Position metrics at entry
        sa.Column("net_credit",         sa.Numeric(10, 2)),
        sa.Column("max_loss",           sa.Numeric(10, 2)),
        sa.Column("lot_size",           sa.Integer, default=1),
        sa.Column("lots",               sa.Integer, default=1),
        sa.Column("spot_at_entry",      sa.Numeric(10, 2)),
        sa.Column("dte_at_entry",       sa.Integer),
        # IV regime at entry
        sa.Column("iv_regime",          sa.String(20)),
        sa.Column("vix_at_entry",       sa.Numeric(6, 2)),
        sa.Column("iv_percentile_1y",   sa.Numeric(5, 1)),
        # Live snapshot (updated each Greeks refresh)
        sa.Column("current_pnl",        sa.Numeric(10, 2), default=0),
        sa.Column("current_delta_ce",   sa.Numeric(6, 4)),
        sa.Column("current_delta_pe",   sa.Numeric(6, 4)),
        sa.Column("dte_remaining",      sa.Numeric(5, 1)),
        sa.Column("last_refreshed_at",  sa.DateTime),
        # Lifecycle
        sa.Column("opened_at",          sa.DateTime, server_default=sa.func.now()),
        sa.Column("closed_at",          sa.DateTime),
        sa.Column("close_pnl",          sa.Numeric(10, 2)),
        sa.Column("close_reason",       sa.String(50)),
        sa.Column("paper_mode",         sa.Boolean, default=True),
        sa.Column("notes",              sa.Text),
    )

    op.create_table(
        "options_seller_adjustments",
        sa.Column("id",           sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("position_id",  sa.Integer, sa.ForeignKey("options_seller_positions.id"), nullable=False, index=True),
        sa.Column("fired_at",     sa.DateTime, server_default=sa.func.now()),
        sa.Column("rule",         sa.String(20), nullable=False),
        sa.Column("action",       sa.String(50), nullable=False),
        sa.Column("reason",       sa.Text),
        sa.Column("spot_at_fire", sa.Numeric(10, 2)),
        sa.Column("pnl_at_fire",  sa.Numeric(10, 2)),
        sa.Column("executed",     sa.Boolean, default=False),
        sa.Column("exec_notes",   sa.Text),
    )


def downgrade() -> None:
    op.drop_table("options_seller_adjustments")
    op.drop_table("options_seller_positions")
