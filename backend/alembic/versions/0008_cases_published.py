"""cases_published

W7 Day7：cases 表加上下架字段（admin 案例库管理页）。

- published BOOLEAN NOT NULL DEFAULT 1（SQLite 用 1/0 存 boolean）
- 全部存量案例（20 文档型 + 30 CSV 报价型）默认上架，检索行为不变
- 语义：下架 = retrieve_cases 不召回；DB 行 / 向量 / 正文全保留，可重新上架
- 与 review_status（pending/verified 数据核验口径）正交，互不影响

Revision ID: 0008_cases_published
Revises: 0007_expand_cases
Create Date: 2026-09-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008_cases_published"
down_revision: Union[str, None] = "0007_expand_cases"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cases", sa.Column(
        "published", sa.Boolean(), nullable=False, server_default=sa.text("1"),
    ))


def downgrade() -> None:
    op.drop_column("cases", "published")
