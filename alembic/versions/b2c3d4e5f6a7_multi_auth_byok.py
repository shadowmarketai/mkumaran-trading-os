"""multi_auth_byok

Add auth_provider, phone, name, avatar to users table.
Add user_settings table for BYOK API keys.

Revision ID: b2c3d4e5f6a7
Revises: 44cb7fb01bfb
Create Date: 2026-04-10 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "44cb7fb01bfb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add columns to users table (if it exists — some deployments use auth differently)
    try:
        op.add_column("users", sa.Column("phone", sa.String(15), nullable=True))
        op.add_column("users", sa.Column("name", sa.String(100), nullable=True))
        op.add_column("users", sa.Column("avatar_url", sa.String(500), nullable=True))
        op.add_column("users", sa.Column("auth_provider", sa.String(20), server_default="password"))
        op.create_index("idx_users_phone", "users", ["phone"], unique=True)
    except Exception:
        pass  # Table may not exist or columns already added

    # User settings table (for BYOK API keys and preferences)
    op.create_table(
        "user_settings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("setting_key", sa.String(50), nullable=False),
        sa.Column("setting_value", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("user_id", "setting_key", name="uq_user_setting"),
    )
    op.create_index("idx_user_settings_user", "user_settings", ["user_id"])


def downgrade() -> None:
    op.drop_table("user_settings")
    try:
        op.drop_index("idx_users_phone", "users")
        op.drop_column("users", "auth_provider")
        op.drop_column("users", "avatar_url")
        op.drop_column("users", "name")
        op.drop_column("users", "phone")
    except Exception:
        pass
