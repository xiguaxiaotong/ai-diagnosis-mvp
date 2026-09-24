"""baseline

W7 Day1：引入 alembic，把项目当前 5 张表快照成 baseline。
- 既有的 `backend/data/sqlite.db` 已用 `alembic stamp head` 标记为该版本，迁移不再实际跑。
- 新克隆 / 全新数据库跑 `alembic upgrade head` 即可建出全套表。
- 之后改模型必出迁移（alembic revision --autogenerate -m "..."），不再裸 ALTER。

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users（Day4 账户系统：username/password_hash 可能为 NULL = 匿名期旧用户）
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(64), nullable=True, unique=True),
        sa.Column("password_hash", sa.String(256), nullable=True),
        sa.Column("name", sa.String(64), nullable=False, server_default="匿名用户"),
        sa.Column("phone", sa.String(20), nullable=True, unique=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # auth_sessions（Day4 会话：token PK；user_id 外键 CASCADE）
    op.create_table(
        "auth_sessions",
        sa.Column("token", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])

    # projects（核心业务表）
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(128), nullable=False, server_default="未命名项目"),
        sa.Column("raw_idea", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="diagnosing"),
        sa.Column("thread_id", sa.String(36), nullable=True, unique=True),
        sa.Column("plan", sa.Text(), nullable=True),
        sa.Column("budget_min", sa.Float(), nullable=True),
        sa.Column("budget_max", sa.Float(), nullable=True),
        sa.Column("req_profile", sa.Text(), nullable=True),
        sa.Column("share_token", sa.String(64), nullable=True, unique=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_projects_status", "projects", ["status"])

    # conversations（对话消息：cascade 删项目时一起删）
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_conversations_project_id", "conversations", ["project_id"])

    # cases（案例库）
    op.create_table(
        "cases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("industry", sa.String(64), nullable=True),
        sa.Column("file_path", sa.String(256), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("vector_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_cases_industry", "cases", ["industry"])


def downgrade() -> None:
    op.drop_index("ix_cases_industry", table_name="cases")
    op.drop_table("cases")
    op.drop_index("ix_conversations_project_id", table_name="conversations")
    op.drop_table("conversations")
    op.drop_index("ix_projects_status", table_name="projects")
    op.drop_table("projects")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("users")