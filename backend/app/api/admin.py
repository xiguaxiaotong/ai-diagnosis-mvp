"""W7 Day5 起：最小运营后台（雏形，算 m6 提前起步）。

Day5：列表 + 改状态
Day6 新增：
- GET  /api/admin/leads/{id}              lead 详情（含项目摘要 + 跟进时间线）
- POST /api/admin/leads/{id}/notes        添加手动跟进（manual note）
- GET  /api/admin/projects/{id}           admin 看任意项目（含对话回放 messages）
- GET  /api/admin/leads/export.csv        CSV 导出（运营日报用）

设计要点：
- PATCH /api/admin/leads/{id} 改 status 时自动写一条 status_change 类型的 LeadNote，
  时间线里能看到「admin X 把状态从 pending 改为 contacted」——审计与回溯
- 状态变更 system note 是 admin_id 标记自己（谁改的）——Day8 m6 扩展审计时直接用
- admin 看任意项目：复用 diagnosis.py 的 detail 逻辑但绕过 user_id 校验
- 日志手机号脱敏在 app.infra.callbacks.PhoneMaskingFilter 统一处理（源头脱敏）

不做的（先聚焦，留待 m6/m7）：
- 用户列表 / 案例审核（Day6 用户明示「按 8-9 周节奏」）
- 操作审计日志（合并到第 8 周 m6 后台统一做，admin_id 已记入 lead_notes）
- 留资推送通知（后置等邮件/短信触达）
"""
import csv
import io
import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import require_admin
from app.db.database import get_db
from app.db.models import Conversation, Lead, LeadNote, Project, User
from app.services import project_service

logger = logging.getLogger("app.api.admin")

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


def _note_to_dict(note: LeadNote, admin: User | None) -> dict[str, Any]:
    """跟进记录 → JSON（admin 视角：包含谁写的 admin username）。"""
    return {
        "id": note.id,
        "lead_id": note.lead_id,
        "admin_id": note.admin_id,
        "admin_username": admin.username if admin else None,
        "note_type": note.note_type,
        "content": note.content,
        "created_at": note.created_at.isoformat() if note.created_at else None,
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
    valid_statuses = [s for s in statuses if s in Lead.ALL_STATUSES]

    query = db.query(Lead).join(Project, isouter=True).join(User, isouter=True)

    if q:
        like = f"%{q.strip()}%"
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


@router.get("/leads/export.csv")
def export_leads_csv(
    status: str | None = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> StreamingResponse:
    """导出 leads 为 CSV（Excel 友好 UTF-8 BOM + 逗号分隔）。

    列：ID, 姓名, 手机号, 公司, 备注, 用户名, 用户邮箱, 项目标题,
        项目状态, lead 状态, 创建时间, 更新时间, 跟进数

    - 范围：与 list 同源（q 暂不导出——CSV 报表是全量/按状态走）
    - 流式返回（StreamingResponse）：leads 量级小（MBP 一天几条到几十条）但别一次性 dict 占内存
    - CSV 注入防御：字段含逗号 / 引号 / 换行时 csv 库自动加双引号转义；
      我们额外禁用 = / + / - / @ 公式前缀防 Excel 公式注入（CSV 注入是 OWASP Top 10 之一）

    ⚠️ 路由必须放在 /leads/{lead_id} 之前注册，否则 FastAPI 会把 "export.csv"
    当作 lead_id 解析为 int 失败 → 422。这里用字面路由优先级保证。
    """
    statuses = [s.strip() for s in (status.split(",") if status else []) if s.strip()]
    valid_statuses = [s for s in statuses if s in Lead.ALL_STATUSES]

    query = db.query(Lead).join(Project, isouter=True).join(User, isouter=True)
    if valid_statuses:
        query = query.filter(Lead.status.in_(valid_statuses))
    leads = query.order_by(Lead.updated_at.desc(), Lead.id.desc()).all()

    # 关联 project / user
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

    # 跟进数（一次查询）
    from sqlalchemy import func as sa_func
    note_counts: dict[int, int] = {}
    if leads:
        rows = db.execute(
            select(LeadNote.lead_id, sa_func.count(LeadNote.id))
            .where(LeadNote.lead_id.in_({l.id for l in leads}))
            .group_by(LeadNote.lead_id)
        ).all()
        for lead_id, n in rows:
            note_counts[lead_id] = n

    def csv_safe(v: str | None) -> str:
        """CSV 注入防御：把 = + - @ 开头的字段前缀 tab 字符，禁用 Excel/CMD 公式注入。
        OWASP CSV Injection。
        """
        if v is None:
            return ""
        s = str(v)
        # OWASP 推荐前缀处理
        if s and s[0] in ("=", "+", "-", "@"):
            s = "\t" + s
        return s

    def gen():
        # UTF-8 BOM：Excel 打开 CSV 不乱码（国内报表场景重要）
        buf = io.StringIO()
        buf.write("\ufeff")
        w = csv.writer(buf)
        w.writerow([
            "ID", "姓名", "手机号", "公司", "备注",
            "用户名", "用户邮箱",
            "项目标题", "项目状态",
            "Lead 状态", "创建时间", "更新时间", "跟进数",
        ])
        yield buf.getvalue()
        buf.seek(0); buf.truncate()

        for l in leads:
            project = projects_map.get(l.project_id) if l.project_id else None
            user = users_map.get(l.user_id) if l.user_id else None
            row = [
                l.id,
                csv_safe(l.name),
                csv_safe(l.phone),
                csv_safe(l.company),
                csv_safe(l.note),
                csv_safe(user.username if user else None),
                csv_safe(user.email if user else None),
                csv_safe(project.title if project else None),
                csv_safe(project.status if project else None),
                csv_safe(l.status),
                l.created_at.isoformat() if l.created_at else "",
                l.updated_at.isoformat() if l.updated_at else "",
                note_counts.get(l.id, 0),
            ]
            w.writerow(row)
            yield buf.getvalue()
            buf.seek(0); buf.truncate()

    # 文件名：leads_YYYYMMDD_HHMMSS.csv
    fname = f"leads_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        gen(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/leads/{lead_id}")
def get_lead_detail(
    lead_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Day6：lead 详情 = 客户信息 + 项目摘要 + 跟进时间线。

    返回：
    - lead：完整 lead 数据（同 _lead_admin_view）
    - project_summary：项目基础字段 + 方案 generated_at + req_profile 摘要
      （不返 plan 全文——大；点「查看完整诊断」走 /api/admin/projects/{id}）
    - notes：跟进时间线（按 created_at DESC）
    - stats：对话消息数（conversations count）——给运营一眼看到活跃度
    """
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="lead 不存在")

    project = db.get(Project, lead.project_id) if lead.project_id else None
    user = db.get(User, lead.user_id) if lead.user_id else None

    # 跟进时间线（按时间倒序）
    notes_db = (
        db.query(LeadNote)
        .filter(LeadNote.lead_id == lead_id)
        .order_by(LeadNote.created_at.desc(), LeadNote.id.desc())
        .all()
    )
    admin_ids = {n.admin_id for n in notes_db if n.admin_id is not None}
    admins_map: dict[int, User] = {}
    if admin_ids:
        for a in db.scalars(select(User).where(User.id.in_(admin_ids))).all():
            admins_map[a.id] = a

    # 项目摘要
    project_summary: dict[str, Any] | None = None
    if project:
        # 取方案 generated_at 和 req_profile 摘要（前 200 字）
        solution_gen_at = None
        req_profile_snippet = None
        if project.plan:
            try:
                plan_obj = json.loads(project.plan)
                solution_gen_at = plan_obj.get("generated_at")
            except json.JSONDecodeError:
                logger.warning("项目 %s 的 plan 字段不是合法 JSON", project.id)
        if project.req_profile:
            req_profile_snippet = project.req_profile[:200]
        project_summary = {
            "id": project.id,
            "title": project.title,
            "status": project.status,
            "raw_idea": project.raw_idea,
            "budget_min": project.budget_min,
            "budget_max": project.budget_max,
            "created_at": project.created_at.isoformat() if project.created_at else None,
            "updated_at": project.updated_at.isoformat() if project.updated_at else None,
            "solution_generated_at": solution_gen_at,
            "req_profile_snippet": req_profile_snippet,
            "thread_id": project.thread_id,
        }

    # 对话活跃度
    msg_count = 0
    if project:
        msg_count = (
            db.query(Conversation)
            .filter(Conversation.project_id == project.id)
            .count()
        )

    return {
        "lead": _lead_admin_view(lead, project, user),
        "project_summary": project_summary,
        "notes": [_note_to_dict(n, admins_map.get(n.admin_id)) for n in notes_db],
        "stats": {"messages_count": msg_count},
    }


class LeadNoteBody(BaseModel):
    """手动添加跟进的请求体。"""
    content: str = Field(min_length=1, max_length=2000)
    note_type: str = Field(default=LeadNote.NOTE_MANUAL, max_length=16)

    @field_validator("note_type")
    @classmethod
    def _v_type(cls, v: str) -> str:
        if v not in LeadNote.ALL_NOTE_TYPES:
            raise ValueError(f"note_type 必须是 {list(LeadNote.ALL_NOTE_TYPES)} 之一")
        return v


@router.post("/leads/{lead_id}/notes")
def add_lead_note(
    lead_id: int,
    body: LeadNoteBody,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Day6：手动添加跟进记录。

    自动追加 admin_id = 当前 admin（后续 m6 审计时直接用）。
    """
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="lead 不存在")

    note = LeadNote(
        lead_id=lead_id,
        admin_id=admin.id,
        note_type=body.note_type,
        content=body.content,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return {"note": _note_to_dict(note, admin)}


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
    """Day6 增强：改跟单状态时自动写一条 status_change note（时间线追溯）。

    同 status（同状态再次 PATCH）也允许且落 note——便于记录「复访沟通」之类的同状态操作。
    若业务要求 idempotent（重复 PATCH 不落 note），可在 admin UI 端控制按钮 disabled；
    后端兜底简单粗暴：每次都写。
    """
    new_status = body.status
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="lead 不存在")

    old_status = lead.status
    lead.status = new_status
    lead.updated_at = datetime.utcnow()

    # 自动写 status_change note（内容：「admin X 把状态从 A 改为 B」）
    note = LeadNote(
        lead_id=lead_id,
        admin_id=admin.id,
        note_type=LeadNote.NOTE_STATUS_CHANGE,
        content=f"状态：{old_status} → {new_status}",
    )
    db.add(note)
    db.commit()
    db.refresh(lead)
    db.refresh(note)

    project = db.get(Project, lead.project_id) if lead.project_id else None
    user = db.get(User, lead.user_id) if lead.user_id else None
    return {"lead": _lead_admin_view(lead, project, user), "note": _note_to_dict(note, admin)}


# ---------- Day6：admin 跨用户项目查看 + 诊断回放 ----------

@router.get("/projects/{project_id}")
def get_admin_project_detail(
    project_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Day6：admin 看任意项目完整 detail + 对话回放。

    与 diagnosis.get_project_detail 的差异：
    - 不做 user_id 校验：admin 看全量
    - 多返 username / user_email：admin 要知道这个项目是谁留的
    - 多返 thread_id：调试诊断会话时方便关联 LangGraph 状态
    - messages 全量返（用户侧也是），但 admin 视图可显示用户没看到的 system 类消息
    """
    project = project_service.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")

    solution: dict | None = None
    if project.plan:
        try:
            solution = json.loads(project.plan)
        except json.JSONDecodeError:
            logger.warning("项目 %s 的 plan 字段不是合法 JSON", project_id)

    req_profile: dict | None = None
    if project.req_profile:
        try:
            parsed = json.loads(project.req_profile)
            if isinstance(parsed, dict) and "requirements" in parsed:
                req_profile = parsed
            elif isinstance(parsed, dict):
                req_profile = {"requirements": parsed}
        except json.JSONDecodeError:
            logger.warning("项目 %s 的 req_profile 字段不是合法 JSON", project_id)

    user = db.get(User, project.user_id) if project.user_id else None

    return {
        "id": project.id,
        "title": project.title,
        "raw_idea": project.raw_idea,
        "status": project.status,
        "budget_min": project.budget_min,
        "budget_max": project.budget_max,
        "thread_id": project.thread_id,
        "user_id": project.user_id,
        "username": user.username if user else None,
        "user_email": user.email if user else None,
        "user_name": user.name if user else None,
        "solution": solution,
        "req_profile": req_profile,
        "messages": [
            {"id": m.id, "role": m.role, "content": m.content,
             "created_at": m.created_at.isoformat()}
            for m in project_service.get_messages(db, project_id)
        ],
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
    }


# ---------- Day6：CSV 导出（运营日报用） ----------

@router.get("/leads/export.csv")
def export_leads_csv(
    status: str | None = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> StreamingResponse:
    """导出 leads 为 CSV（Excel 友好 UTF-8 BOM + 逗号分隔）。

    列：ID, 姓名, 手机号, 公司, 备注, 用户名, 用户邮箱, 项目标题,
        项目状态, lead 状态, 创建时间, 更新时间, 跟进数

    - 范围：与 list 同源（q 暂不导出——CSV 报表是全量/按状态走）
    - 流式返回（StreamingResponse）：leads 量级小（MBP 一天几条到几十条）但别一次性 dict 占内存
    - CSV 注入防御：字段含逗号 / 引号 / 换行时 csv 库自动加双引号转义；
      我们额外禁用 = / + / - / @ 公式前缀防 Excel 公式注入（CSV 注入是 OWASP Top 10 之一）
    """
    statuses = [s.strip() for s in (status.split(",") if status else []) if s.strip()]
    valid_statuses = [s for s in statuses if s in Lead.ALL_STATUSES]

    query = db.query(Lead).join(Project, isouter=True).join(User, isouter=True)
    if valid_statuses:
        query = query.filter(Lead.status.in_(valid_statuses))
    leads = query.order_by(Lead.updated_at.desc(), Lead.id.desc()).all()

    # 关联 project / user
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

    # 跟进数（一次查询）
    from sqlalchemy import func as sa_func
    note_counts: dict[int, int] = {}
    if leads:
        rows = db.execute(
            select(LeadNote.lead_id, sa_func.count(LeadNote.id))
            .where(LeadNote.lead_id.in_({l.id for l in leads}))
            .group_by(LeadNote.lead_id)
        ).all()
        for lead_id, n in rows:
            note_counts[lead_id] = n

    def csv_safe(v: str | None) -> str:
        """CSV 注入防御：把 = + - @ 开头的字段前缀 tab 字符，禁用 Excel/CMD 公式注入。
        OWASP CSV Injection。
        """
        if v is None:
            return ""
        s = str(v)
        # OWASP 推荐前缀处理
        if s and s[0] in ("=", "+", "-", "@"):
            s = "\t" + s
        return s

    def gen():
        # UTF-8 BOM：Excel 打开 CSV 不乱码（国内报表场景重要）
        buf = io.StringIO()
        buf.write("\ufeff")
        w = csv.writer(buf)
        w.writerow([
            "ID", "姓名", "手机号", "公司", "备注",
            "用户名", "用户邮箱",
            "项目标题", "项目状态",
            "Lead 状态", "创建时间", "更新时间", "跟进数",
        ])
        yield buf.getvalue()
        buf.seek(0); buf.truncate()

        for l in leads:
            project = projects_map.get(l.project_id) if l.project_id else None
            user = users_map.get(l.user_id) if l.user_id else None
            row = [
                l.id,
                csv_safe(l.name),
                csv_safe(l.phone),
                csv_safe(l.company),
                csv_safe(l.note),
                csv_safe(user.username if user else None),
                csv_safe(user.email if user else None),
                csv_safe(project.title if project else None),
                csv_safe(project.status if project else None),
                csv_safe(l.status),
                l.created_at.isoformat() if l.created_at else "",
                l.updated_at.isoformat() if l.updated_at else "",
                note_counts.get(l.id, 0),
            ]
            w.writerow(row)
            yield buf.getvalue()
            buf.seek(0); buf.truncate()

    # 文件名：leads_YYYYMMDD_HHMMSS.csv
    fname = f"leads_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        gen(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )