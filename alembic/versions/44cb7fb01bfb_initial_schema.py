"""initial_schema

Revision ID: 44cb7fb01bfb
Revises:
Create Date: 2026-03-31 16:13:10.886979

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '44cb7fb01bfb'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all tables matching mcp_server/models.py."""
    # Watchlist
    op.create_table(
        "watchlist",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(20), nullable=False, index=True),
        sa.Column("name", sa.String(50), nullable=True),
        sa.Column("exchange", sa.String(10), server_default="NSE"),
        sa.Column("asset_class", sa.String(15), server_default="EQUITY"),
        sa.Column("timeframe", sa.String(10), server_default="day"),
        sa.Column("tier", sa.Integer(), server_default="2"),
        sa.Column("ltrp", sa.Numeric(10, 2), nullable=True),
        sa.Column("pivot_high", sa.Numeric(10, 2), nullable=True),
        sa.Column("active", sa.Boolean(), server_default="true"),
        sa.Column("source", sa.String(20), server_default="manual"),
        sa.Column("added_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("added_by", sa.String(20), server_default="user"),
        sa.Column("notes", sa.Text(), nullable=True),
    )

    # Signals
    op.create_table(
        "signals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("signal_date", sa.Date(), nullable=False, index=True),
        sa.Column("signal_time", sa.Time(), nullable=True),
        sa.Column("ticker", sa.String(20), index=True),
        sa.Column("exchange", sa.String(10), server_default="NSE"),
        sa.Column("asset_class", sa.String(15), server_default="EQUITY"),
        sa.Column("direction", sa.String(10)),
        sa.Column("pattern", sa.String(50)),
        sa.Column("entry_price", sa.Numeric(10, 2)),
        sa.Column("stop_loss", sa.Numeric(10, 2)),
        sa.Column("target", sa.Numeric(10, 2)),
        sa.Column("rrr", sa.Numeric(5, 2)),
        sa.Column("qty", sa.Integer()),
        sa.Column("risk_amt", sa.Numeric(10, 2)),
        sa.Column("ai_confidence", sa.Integer()),
        sa.Column("tv_confirmed", sa.Boolean(), server_default="false"),
        sa.Column("mwa_score", sa.String(10)),
        sa.Column("scanner_count", sa.Integer()),
        sa.Column("tier", sa.Integer()),
        sa.Column("source", sa.String(20)),
        sa.Column("timeframe", sa.String(10), server_default="1D"),
        sa.Column("status", sa.String(20), server_default="OPEN"),
    )

    # Outcomes
    op.create_table(
        "outcomes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("signal_id", sa.Integer(), sa.ForeignKey("signals.id")),
        sa.Column("exit_date", sa.Date()),
        sa.Column("exit_price", sa.Numeric(10, 2)),
        sa.Column("outcome", sa.String(10)),
        sa.Column("pnl_amount", sa.Numeric(10, 2)),
        sa.Column("days_held", sa.Integer()),
        sa.Column("exit_reason", sa.String(20)),
    )

    # MWA Scores
    op.create_table(
        "mwa_scores",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("score_date", sa.Date(), unique=True, index=True),
        sa.Column("direction", sa.String(15)),
        sa.Column("bull_score", sa.Numeric(5, 1)),
        sa.Column("bear_score", sa.Numeric(5, 1)),
        sa.Column("bull_pct", sa.Numeric(5, 1)),
        sa.Column("bear_pct", sa.Numeric(5, 1)),
        sa.Column("scanner_results", postgresql.JSONB()),
        sa.Column("promoted_stocks", postgresql.ARRAY(sa.String())),
        sa.Column("fii_net", sa.Numeric(12, 2)),
        sa.Column("dii_net", sa.Numeric(12, 2)),
        sa.Column("sector_strength", sa.JSON()),
    )

    # Active Trades
    op.create_table(
        "active_trades",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("signal_id", sa.Integer(), sa.ForeignKey("signals.id")),
        sa.Column("ticker", sa.String(20), index=True),
        sa.Column("exchange", sa.String(10), server_default="NSE"),
        sa.Column("asset_class", sa.String(15), server_default="EQUITY"),
        sa.Column("entry_price", sa.Numeric(10, 2)),
        sa.Column("target", sa.Numeric(10, 2)),
        sa.Column("stop_loss", sa.Numeric(10, 2)),
        sa.Column("prrr", sa.Numeric(5, 2)),
        sa.Column("current_price", sa.Numeric(10, 2)),
        sa.Column("crrr", sa.Numeric(5, 2)),
        sa.Column("last_updated", sa.DateTime()),
        sa.Column("timeframe", sa.String(10), server_default="1D"),
        sa.Column("alert_sent", sa.Boolean(), server_default="false"),
    )

    # OHLCV Cache
    op.create_table(
        "ohlcv_cache",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(30), nullable=False),
        sa.Column("exchange", sa.String(10), nullable=False, server_default="NSE"),
        sa.Column("interval", sa.String(10), nullable=False),
        sa.Column("bar_date", sa.DateTime(), nullable=False),
        sa.Column("open", sa.Numeric(14, 4), nullable=False),
        sa.Column("high", sa.Numeric(14, 4), nullable=False),
        sa.Column("low", sa.Numeric(14, 4), nullable=False),
        sa.Column("close", sa.Numeric(14, 4), nullable=False),
        sa.Column("volume", sa.Numeric(18, 0), nullable=False),
        sa.Column("source", sa.String(10), nullable=False, server_default="yfinance"),
        sa.Column("fetched_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("tenant_id", sa.String(36), nullable=True, index=True),
        sa.UniqueConstraint("ticker", "interval", "bar_date", name="uq_ohlcv_ticker_interval_bardate"),
    )
    op.create_index("ix_ohlcv_lookup", "ohlcv_cache", ["ticker", "interval", "bar_date"])
    op.create_index("ix_ohlcv_staleness", "ohlcv_cache", ["ticker", "interval", "fetched_at"])
    op.create_index("ix_ohlcv_tenant", "ohlcv_cache", ["tenant_id", "ticker", "interval"])


def downgrade() -> None:
    """Drop all tables."""
    op.drop_table("ohlcv_cache")
    op.drop_table("active_trades")
    op.drop_table("mwa_scores")
    op.drop_table("outcomes")
    op.drop_table("signals")
    op.drop_table("watchlist")
