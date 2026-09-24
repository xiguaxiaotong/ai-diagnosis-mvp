"""expand_cases_structured_fields

W7 Day6：cases 表补 CSV 种子案例结构化字段（第一批 30 条报价数据）。

新增列（全部 nullable，旧行不破坏，review_status 例外——NOT NULL + 默认 pending）：
- scenario       VARCHAR(64)  场景（加索引，检索/筛选用）
- features       TEXT         功能清单
- tech_stack     TEXT         技术栈
- budget_min     INTEGER      预算下限（元）
- budget_max     INTEGER      预算上限（元）
- duration_weeks VARCHAR(16)  工期（"1-2" 这类区间串）
- source_url     VARCHAR(512) 来源链接
- source_type    VARCHAR(64)   来源类型
- collected_at   DATE         采集时间
- data_quality   VARCHAR(128) 数据口径说明
- review_status  VARCHAR(16)  审核状态（数据核验口径：pending/verified，
                              NOT NULL DEFAULT 'pending'，旧数据自动回填 pending；
                              与未来案例上下架状态无关，勿混用）

Revision ID: 0007_expand_cases
Revises: 0006_add_lead_notes
Create Date: 2026-09-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007_expand_cases"
down_revision: Union[str, None] = "0006_add_lead_notes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cases", sa.Column("scenario", sa.String(64), nullable=True))
    op.add_column("cases", sa.Column("features", sa.Text(), nullable=True))
    op.add_column("cases", sa.Column("tech_stack", sa.Text(), nullable=True))
    op.add_column("cases", sa.Column("budget_min", sa.Integer(), nullable=True))
    op.add_column("cases", sa.Column("budget_max", sa.Integer(), nullable=True))
    op.add_column("cases", sa.Column("duration_weeks", sa.String(16), nullable=True))
    op.add_column("cases", sa.Column("source_url", sa.String(512), nullable=True))
    op.add_column("cases", sa.Column("source_type", sa.String(64), nullable=True))
    op.add_column("cases", sa.Column("collected_at", sa.Date(), nullable=True))
    op.add_column("cases", sa.Column("data_quality", sa.String(128), nullable=True))
    op.add_column("cases", sa.Column(
        "review_status", sa.String(16), nullable=False, server_default="pending",
    ))
    op.create_index("ix_cases_scenario", "cases", ["scenario"])


def downgrade() -> None:
    op.drop_index("ix_cases_scenario", table_name="cases")
    for col in ("review_status", "data_quality", "collected_at", "source_type",
                "source_url", "duration_weeks", "budget_max", "budget_min",
                "tech_stack", "features", "scenario"):
        op.drop_column("cases", col)
