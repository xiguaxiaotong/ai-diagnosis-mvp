"""add_lead

W7 Day4：方案确认后的对接申请（lead = 销售线索）。
- 一个项目一条 lead（UNIQUE(project_id)）：重复提交 = 覆盖更新
- user_id 冗余存一份：项目被删时 lead 仍可人工跟进
- status 默认 pending：运营手动改（pending → contacted → done）

Revision ID: 0004_add_lead
Revises: 0003_add_user_email
Create Date: 2026-09-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_add_lead"
down_revision: Union[str, None] = "0003_add_user_email"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "leads",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer,
                  sa.ForeignKey("projects.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("user_id", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("company", sa.String(128), nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime,
                  server_default=sa.func.now(),
                  server_onupdate=sa.func.now()),
        sa.UniqueConstraint("project_id", name="uq_leads_project"),
    )
    op.create_index("ix_leads_user_id", "leads", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_leads_user_id", table_name="leads")
    op.drop_table("leads")