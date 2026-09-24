"""expand_lead_status_to_five

W7 Day5：运营跟单状态机从 3 态扩展为 5 态（用户实际跟单需要）。

变更：
- 把已有 leads.status = 'done' 映射为 'closed'（语义等价：都是终态）
- pending / contacted 保留语义不变
- 新增合法值：quoted（已报价）、won（已成交）；通过 ALL_STATUSES 暴露给应用层
- 不动 schema（SQLite 无 enum constraint，String(16) 已够），仅做数据迁移

Revision ID: 0005_expand_lead_status
Revises: 0004_add_lead
Create Date: 2026-09-24
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0005_expand_lead_status"
down_revision: Union[str, None] = "0004_add_lead"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Day4 时代只有 'done' 一个终态；映射到 'closed'（业务同义）。
    # pending / contacted / 其他（理论上不应有）保留不动。
    op.execute("UPDATE leads SET status = 'closed' WHERE status = 'done'")


def downgrade() -> None:
    # 反向：把 closed 退回 done，quoted/won 退回 contacted（保守映射，回退后
    # 至少不丢失「已跟进」语义；真实回退前应人工 review）
    op.execute("UPDATE leads SET status = 'done' WHERE status = 'closed'")
    op.execute("UPDATE leads SET status = 'contacted' WHERE status IN ('quoted', 'won')")