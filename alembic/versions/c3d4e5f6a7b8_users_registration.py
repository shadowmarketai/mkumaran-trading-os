"""users_registration

Create proper users table for registration + login flow.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-12 10:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(255), nullable=True, unique=True),
        sa.Column("phone", sa.String(15), nullable=True, unique=True),
        sa.Column("password_hash", sa.String(128), nullable=False),
        sa.Column("name", sa.String(100), nullable=True),
        sa.Column("avatar_url", sa.String(500), nullable=True),
        sa.Column("auth_provider", sa.String(20), server_default="email"),
        # email, phone, google
        sa.Column("google_id", sa.String(50), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("trading_experience", sa.String(20), nullable=True),
        sa.Column("trading_segments", sa.String(200), nullable=True),
        sa.Column("is_verified", sa.Boolean(), server_default="false"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("role", sa.String(20), server_default="user"),
        sa.Column("last_login", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_app_users_email", "app_users", ["email"])
    op.create_index("idx_app_users_phone", "app_users", ["phone"])
    op.create_index("idx_app_users_google", "app_users", ["google_id"])


def downgrade() -> None:
    op.drop_table("app_users")
