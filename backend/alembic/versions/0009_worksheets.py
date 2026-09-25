"""worksheets_and_notes

W7 Day8：工单模块（lead 转入的交付跟单）。

- worksheets：5 态线性状态机（to_confirm → communicating → quoted → won，
  非终态可 → closed；合法流转白名单在模型层 TRANSITIONS，API 层 400 拦截）
- worksheet_notes：工单时间线，结构对齐 lead_notes（复用前端时间线组件）
- 字段映射自 lead / project：customer_name ← lead.name，contact ← lead.phone，
  requirement_summary ← project.raw_idea，thread_id ← project.thread_id
- 全新表，不动存量数据

Revision ID: 0009_worksheets
Revises: 0008_cases_published
Create Date: 2026-09-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009_worksheets"
down_revision: Union[str, None] = "0008_cases_published"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "worksheets",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("lead_id", sa.Integer(),
                  sa.ForeignKey("leads.id", ondelete="SET NULL"), nullable=True),
        sa.Column("project_id", sa.Integer(),
                  sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("customer_name", sa.String(64), nullable=False),
        sa.Column("contact", sa.String(64), nullable=False),
        sa.Column("company", sa.String(128), nullable=True),
        sa.Column("requirement_summary", sa.Text(), nullable=True),
        sa.Column("thread_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(16), nullable=False,
                  server_default="to_confirm"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_worksheets_lead_id", "worksheets", ["lead_id"], unique=True)
    op.create_index("ix_worksheets_project_id", "worksheets", ["project_id"])
    op.create_index("ix_worksheets_user_id", "worksheets", ["user_id"])
    op.create_index("ix_worksheets_status", "worksheets", ["status"])

    op.create_table(
        "worksheet_notes",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("worksheet_id", sa.Integer(),
                  sa.ForeignKey("worksheets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("admin_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("note_type", sa.String(16), nullable=False, server_default="status_change"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_worksheet_notes_worksheet_id", "worksheet_notes", ["worksheet_id"])


def downgrade() -> None:
    op.drop_index("ix_worksheet_notes_worksheet_id", table_name="worksheet_notes")
    op.drop_table("worksheet_notes")
    op.drop_index("ix_worksheets_status", table_name="worksheets")
    op.drop_index("ix_worksheets_user_id", table_name="worksheets")
    op.drop_index("ix_worksheets_project_id", table_name="worksheets")
    op.drop_index("ix_worksheets_lead_id", table_name="worksheets")
    op.drop_table("worksheets")
