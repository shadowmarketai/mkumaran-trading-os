"""Add human_decision column to signals table

Revision ID: c2d3e4f5a6b7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-12

Records whether the owner pressed TAKE or SKIP on a Telegram signal card.
NULL means no button was pressed (pre-button signals or missed).
Used to compare human-filtered win rate vs mechanical baseline.
"""

from alembic import op
import sqlalchemy as sa

revision = "c2d3e4f5a6b7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "signals",
        sa.Column("human_decision", sa.String(10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("signals", "human_decision")
