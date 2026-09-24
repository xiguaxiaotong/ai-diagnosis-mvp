"""add_user_email

W7 Day2：users.email 列（unique nullable）。
- 老数据都填 NULL（兼容现有 17 个用户）
- 索引：unique=True 自动创建唯一索引

Revision ID: 0003_add_user_email
Revises: 0002_password_reset_tokens
Create Date: 2026-09-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_add_user_email"
down_revision: Union[str, None] = "0002_password_reset_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("email", sa.String(120), nullable=True))
        batch_op.create_unique_constraint("uq_users_email", ["email"])


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("uq_users_email", type_="unique")
        batch_op.drop_column("email")