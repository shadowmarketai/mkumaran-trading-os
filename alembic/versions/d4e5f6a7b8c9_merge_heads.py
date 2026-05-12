"""Merge seed_watchlist branch with main migration head

Revision ID: d4e5f6a7b8c9
Revises: c2d3e4f5a6b7, a5200d85c7ca
Create Date: 2026-05-12

a5200d85c7ca (seed_watchlist) branched off d3b488d0416d without
being merged back into the main chain, causing 'multiple heads'.
This merge migration resolves the fork so 'alembic upgrade head'
works again.
"""

from alembic import op  # noqa: F401

revision = "d4e5f6a7b8c9"
down_revision = ("c2d3e4f5a6b7", "a5200d85c7ca")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
