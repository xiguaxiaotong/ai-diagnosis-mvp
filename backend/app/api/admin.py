"""W7 Day5：最小运营后台（雏形，算 m6 提前起步）。

范围（严格最小）：
- GET  /api/admin/leads                跨用户 leads 列表（含项目 / 用户信息）
- PATCH /api/admin/leads/{lead_id}     改跟单状态（5 态白名单）

不做的：
- 通知中心（Day5 原计划；用户改方向，后置等邮件/短信触达再做）
- 站内消息 / 推送
- 角色管理 UI（admin 白名单走 env + SQL）
- 操作审计日志（合并到第 8 周 m6 后台统一做）
- 项目列表 / 案例列表 / 用户列表（先聚焦 leads，其他后置）

设计：
- 鉴权：复用 auth.require_admin；403（非 401）让 admin 知道是被拒而非过期
- 不分页（leads 量级小：MVP 一天几条到几十条；列表给 limit=200 兜底，前端懒拉）
- 不按用户隔离：admin 看全量
- 不脱敏：admin 拿到完整姓名 + 手机号（他要打电话/加微信）
- 排序：updated_at DESC（跟单视角：最近动过的最该关注）
"""
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import require_admin
from app.db.database import get_db
from app.db.models import Lead, Project, User

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _lead_admin_view(lead: Lead, project: Project | None, user: User | None) -> dict[str, Any]:
    """运营视角的 lead 完整数据（含所属项目 + 用户）。

    与用户侧 _lead_to_dict 的差异：
    - 完整姓名 / 手机号 / 公司 / 备注（admin 不脱敏）
    - 多了 project_title / project_status / username
    """
    return {
        "id": lead.id,
        "project_id": lead.project_id,
        "project_title": project.title if project else None,
        "project_status": project.status if project else None,
        "user_id": lead.user_id,
        "username": user.username if user else None,
        "name": lead.name,
        "phone": lead.phone,
        "company": lead.company,
        "note": lead.note,
        "status": lead.status,
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
        "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
    }


@router.get("/leads")
def list_leads(
    q: str | None = None,
    status: str | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """运营视角 leads 列表（跨用户）。

    - q：模糊匹配 name / phone / project.title / username（运营搜「张三」/「138」/「方案标题」都能命中）
    - status：逗号分隔多选（如 'pending,contacted'）；空/缺省 = 不过滤
    - limit：上限 200（防止 admin 一把拉全表拖慢）
    """
    statuses = [s.strip() for s in (status.split(",") if status else []) if s.strip()]
    # 合法 status 过滤（防御脏数据让 IN 命中空）
    valid_statuses = [s for s in statuses if s in Lead.ALL_STATUSES]

    query = db.query(Lead).join(Project, isouter=True).join(User, isouter=True)

    if q:
        like = f"%{q.strip()}%"
        # SQLAlchemy 的 or_: 多字段任一命中即可
        from sqlalchemy import or_
        query = query.filter(
            or_(
                Lead.name.ilike(like),
                Lead.phone.ilike(like),
                Project.title.ilike(like),
                User.username.ilike(like),
            )
        )
    if valid_statuses:
        query = query.filter(Lead.status.in_(valid_statuses))

    # updated_at DESC + id DESC 兜底（同秒更新）
    leads = (
        query.order_by(Lead.updated_at.desc(), Lead.id.desc())
        .limit(min(limit, 200))
        .all()
    )

    # 批量 fetch 关联 project / user 避免 N+1
    project_ids = {l.project_id for l in leads if l.project_id is not None}
    user_ids = {l.user_id for l in leads if l.user_id is not None}
    projects_map: dict[int, Project] = {}
    users_map: dict[int, User] = {}
    if project_ids:
        for p in db.scalars(select(Project).where(Project.id.in_(project_ids))).all():
            projects_map[p.id] = p
    if user_ids:
        for u in db.scalars(select(User).where(User.id.in_(user_ids))).all():
            users_map[u.id] = u

    return {
        "items": [_lead_admin_view(l, projects_map.get(l.project_id) if l.project_id else None,
                                    users_map.get(l.user_id) if l.user_id else None)
                  for l in leads],
    }


class LeadStatusBody(BaseModel):
    """运营改状态：仅 status 一个字段，避免误改联系方式（联系方式由用户自己改）。"""
    status: str = Field(min_length=1, max_length=16)

    @field_validator("status")
    @classmethod
    def _v_status(cls, v: str) -> str:
        if v not in Lead.ALL_STATUSES:
            raise ValueError(f"status 必须是 {list(Lead.ALL_STATUSES)} 之一")
        return v


@router.patch("/leads/{lead_id}")
def update_lead_status(
    lead_id: int,
    body: LeadStatusBody,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """改跟单状态：5 态白名单；联系方式 / 备注不允许 admin 改（用户隐私）。"""
    new_status = body.status  # 已通过 field_validator 校验
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="lead 不存在")
    lead.status = new_status
    lead.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(lead)
    project = db.get(Project, lead.project_id) if lead.project_id else None
    user = db.get(User, lead.user_id) if lead.user_id else None
    return {"lead": _lead_admin_view(lead, project, user)}