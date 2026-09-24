"""add_lead_notes

W7 Day6：leads 跟进记录 / 时间线表。

新增 lead_notes：
- id PK
- lead_id FK leads.id ON DELETE CASCADE（lead 删了，笔记一起删，不留孤儿）
- admin_id FK users.id ON DELETE SET NULL（运营账号删了，笔记保留为 NULL）
- note_type VARCHAR(16)：manual / status_change / system
- content TEXT：手动写的内容 / 系统自动写的「状态 pending → contacted」
- created_at DATETIME：默认 now()

不进 PRAGMA 兼容性问题（SQLite 无 enum 约束，String 即可）。

Revision ID: 0006_add_lead_notes
Revises: 0005_expand_lead_status
Create Date: 2026-09-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_add_lead_notes"
down_revision: Union[str, None] = "0005_expand_lead_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lead_notes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("lead_id", sa.Integer, nullable=False),
        sa.Column("admin_id", sa.Integer, nullable=True),
        sa.Column("note_type", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["admin_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_lead_notes_lead_id", "lead_notes", ["lead_id"])


def downgrade() -> None:
    op.drop_index("ix_lead_notes_lead_id", table_name="lead_notes")
    op.drop_table("lead_notes")