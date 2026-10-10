"""user roles (user, admin, demo)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-11 03:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("role", sa.String(length=10), server_default="user", nullable=False))
    op.create_check_constraint("ck_users_role", "users", "role IN ('user', 'admin', 'demo')")


def downgrade() -> None:
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.drop_column("users", "role")
