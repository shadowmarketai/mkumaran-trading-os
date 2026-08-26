"""widen ohlcv_cache.source from VARCHAR(10) to VARCHAR(30)

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-05-08

Root cause: source value "multi-source" (12 chars) exceeds VARCHAR(10),
causing StringDataRightTruncation when the OHLCV cache tries to persist
data fetched from multiple providers simultaneously.
"""

import sqlalchemy as sa

from alembic import op

revision = "f5a6b7c8d9e0"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "ohlcv_cache",
        "source",
        existing_type=sa.String(10),
        type_=sa.String(30),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "ohlcv_cache",
        "source",
        existing_type=sa.String(30),
        type_=sa.String(10),
        existing_nullable=False,
    )
