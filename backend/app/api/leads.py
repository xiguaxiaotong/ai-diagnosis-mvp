"""W7 Day4：方案确认后的对接申请（lead）。

设计：
- POST /api/projects/{id}/lead：提交 / 更新联系方式（重复提交 = 覆盖）
  副作用：项目 status → confirmed（若还不是 confirmed）
- GET /api/projects/{id}/lead：取最新申请（不存在 → 404）

限制：
- 项目所有者才能写；读同样鉴权
- 必须在「方案已生成」之后才能留资（diagnosing 期拒：方案都没确认）
  —— 这保证 lead 不是「聊到一半就要求联系方式」（破坏体验），而是「方案确认后申请人工对接」
"""
import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.database import get_db
from app.db.models import Lead, Project, User
from app.services import project_service

router = APIRouter(prefix="/api/projects", tags=["leads"])

# 简化校验：标准库 re 足够（MVP 不引 phonenumbers 库）
_PHONE_RE = re.compile(r"^\d{11}$")  # 中国大陆 11 位手机号
_NAME_MAX = 64


def _lead_to_dict(lead: Lead) -> dict[str, Any]:
    return {
        "id": lead.id,
        "project_id": lead.project_id,
        "name": lead.name,
        "phone": lead.phone,
        "company": lead.company,
        "note": lead.note,
        "status": lead.status,
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
        "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
    }


def _validate_project_for_lead(project: Project | None, user: User) -> Project:
    """共有闸：项目存在 + 属于当前用户 + 方案已生成。"""
    if project is None or project.user_id != user.id:
        raise HTTPException(status_code=404, detail="项目不存在")
    if project.status == Project.STATUS_DIAGNOSING:
        raise HTTPException(
            status_code=400,
            detail="方案还没生成，先确认方案才能申请人工对接",
        )
    return project


class LeadBody(BaseModel):
    """留资表单：name / phone 必填，note / company 选填。

    字段约束：
    - name：1-64 字（不能空字符串，不能全是空格）
    - phone：必须 11 位数字（中国大陆手机号）
    - company：≤128 字（选填）
    - note：≤500 字（选填）—— 选填但实际很常填（用户想说清楚自己的需求场景）
    """

    name: str = Field(min_length=1, max_length=_NAME_MAX)
    phone: str = Field(min_length=11, max_length=11)
    company: str | None = Field(default=None, max_length=128)
    note: str | None = Field(default=None, max_length=500)

    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v2 = v.strip()
        return v2 if v2 else None


def _validate_body(body: "LeadBody") -> tuple[str, str, str | None, str | None]:
    """校验 + 清洗，返回干净四元组。失败抛 HTTPException。"""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="姓名不能为空")
    if len(name) > _NAME_MAX:
        raise HTTPException(status_code=400, detail=f"姓名不能超过 {_NAME_MAX} 字")
    phone = body.phone.strip()
    if not _PHONE_RE.match(phone):
        raise HTTPException(status_code=400, detail="手机号必须 11 位数字")
    return name, phone, LeadBody._strip(body.company), LeadBody._strip(body.note)


@router.post("/{project_id}/lead")
def submit_lead(
    project_id: int,
    body: LeadBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """提交 / 覆盖对接申请；副作用：项目 status → confirmed。"""
    project = project_service.get_project(db, project_id)
    project = _validate_project_for_lead(project, user)
    name, phone, company, note = _validate_body(body)

    # 副作用 1：项目状态 → confirmed
    if project.status != Project.STATUS_CONFIRMED:
        project.status = Project.STATUS_CONFIRMED

    # 副作用 2：upsert lead（一项目一条，重复提交 = 覆盖）
    existing = db.scalar(select(Lead).where(Lead.project_id == project_id))
    if existing is not None:
        existing.name = name
        existing.phone = phone
        existing.company = company
        existing.note = note
        # 状态重置：用户主动重新提交 = 还想被联系，避免运营误标 done 后
        # 用户改主意却没人理
        existing.status = Lead.STATUS_PENDING
        existing.updated_at = datetime.utcnow()
        lead = existing
    else:
        lead = Lead(
            project_id=project_id, user_id=user.id,
            name=name, phone=phone, company=company, note=note,
            status=Lead.STATUS_PENDING,
        )
        db.add(lead)
    db.commit()
    db.refresh(lead)
    return {
        "lead": _lead_to_dict(lead),
        "project_status": project.status,
        "is_new": existing is None,
    }


@router.get("/{project_id}/lead")
def get_lead(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """取对接申请；不存在 = 404（前端据此显示留资表单而非已留资卡）。"""
    project = project_service.get_project(db, project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(status_code=404, detail="项目不存在")
    lead = db.scalar(select(Lead).where(Lead.project_id == project_id))
    if lead is None:
        raise HTTPException(status_code=404, detail="尚未提交对接申请")
    return {"lead": _lead_to_dict(lead)}
