"""Add server_default='yfinance' to ohlcv_cache.source

Revision ID: a1b2c3d4e5f6
Revises: f5a6b7c8d9e0
Create Date: 2026-05-12

The column was already widened to VARCHAR(30) in f5a6b7c8d9e0, but
databases created from schema.sql (pre-Alembic) may lack a server
DEFAULT. Without a DEFAULT, any INSERT that omits 'source' hits a
NOT NULL violation.

This migration sets the Postgres column DEFAULT to 'yfinance' so
backfills and other callers that omit the column work correctly.
"""

import sqlalchemy as sa

from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "f5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "ohlcv_cache",
        "source",
        existing_type=sa.String(30),
        nullable=False,
        server_default="yfinance",
    )


def downgrade() -> None:
    op.alter_column(
        "ohlcv_cache",
        "source",
        existing_type=sa.String(30),
        nullable=False,
        server_default=None,
    )
