"""W7 Day5 起：最小运营后台（雏形，算 m6 提前起步）。

Day5：列表 + 改状态
Day6 新增：
- GET  /api/admin/leads/{id}              lead 详情（含项目摘要 + 跟进时间线）
- POST /api/admin/leads/{id}/notes        添加手动跟进（manual note）
- GET  /api/admin/projects/{id}           admin 看任意项目（含对话回放 messages）
- GET  /api/admin/leads/export.csv        CSV 导出（运营日报用）
Day7 新增：
- GET   /api/admin/cases                  案例库列表（含下架的；结构化字段全量）
- GET   /api/admin/cases/retrieve-preview 检索预览（真实用户问题预演线上召回）
- PATCH /api/admin/cases/{id}             上下架（下架 = 检索不召回，数据全保留）
Day9 新增：
- GET   /api/admin/stats                  数据看板（统计卡片 + 转化漏斗 + 近14天趋势）

设计要点：
- PATCH /api/admin/leads/{id} 改 status 时自动写一条 status_change 类型的 LeadNote，
  时间线里能看到「admin X 把状态从 pending 改为 contacted」——审计与回溯
- 状态变更 system note 是 admin_id 标记自己（谁改的）——Day8 m6 扩展审计时直接用
- admin 看任意项目：复用 diagnosis.py 的 detail 逻辑但绕过 user_id 校验
- 日志手机号脱敏在 app.infra.callbacks.PhoneMaskingFilter 统一处理（源头脱敏）
- 案例上下架与 review_status（数据核验）正交：published 管检索可见性，
  review_status 管数据可信度，互不干扰
- 修 Day6 遗留：export.csv 曾重复注册两次（同 path 同 method，第二个是死代码），已删

不做的（先聚焦，留待 m6/m7）：
- 用户列表 / 案例审核（按 8-9 周节奏，Day8 再开）
- 操作审计日志（合并到第 8 周 m6 后台统一做，admin_id 已记入 lead_notes）
- 留资推送通知（后置等邮件/短信触达）
"""
import csv
import io
import json
import logging
from datetime import UTC, datetime, timedelta
from datetime import time as dt_time
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import require_admin
from app.db.database import get_db
from app.db.models import (
    Case,
    Conversation,
    Lead,
    LeadNote,
    Project,
    User,
    Worksheet,
    WorksheetNote,
)
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
    project_ids = {ld.project_id for ld in leads if ld.project_id is not None}
    user_ids = {ld.user_id for ld in leads if ld.user_id is not None}
    projects_map: dict[int, Project] = {}
    users_map: dict[int, User] = {}
    if project_ids:
        for p in db.scalars(select(Project).where(Project.id.in_(project_ids))).all():
            projects_map[p.id] = p
    if user_ids:
        for u in db.scalars(select(User).where(User.id.in_(user_ids))).all():
            users_map[u.id] = u

    return {
        "items": [_lead_admin_view(ld, projects_map.get(ld.project_id) if ld.project_id else None,
                                    users_map.get(ld.user_id) if ld.user_id else None)
                  for ld in leads],
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
    project_ids = {ld.project_id for ld in leads if ld.project_id is not None}
    user_ids = {ld.user_id for ld in leads if ld.user_id is not None}
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
            .where(LeadNote.lead_id.in_({ld.id for ld in leads}))
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
        buf.seek(0)
        buf.truncate()

        for ld in leads:
            project = projects_map.get(ld.project_id) if ld.project_id else None
            user = users_map.get(ld.user_id) if ld.user_id else None
            row = [
                ld.id,
                csv_safe(ld.name),
                csv_safe(ld.phone),
                csv_safe(ld.company),
                csv_safe(ld.note),
                csv_safe(user.username if user else None),
                csv_safe(user.email if user else None),
                csv_safe(project.title if project else None),
                csv_safe(project.status if project else None),
                csv_safe(ld.status),
                ld.created_at.isoformat() if ld.created_at else "",
                ld.updated_at.isoformat() if ld.updated_at else "",
                note_counts.get(ld.id, 0),
            ]
            w.writerow(row)
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate()

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
        # Day8：已转工单的 lead 要在详情页提示/直接跳（unique，最多一张）
        "worksheet_id": (
            db.query(Worksheet.id).filter(Worksheet.lead_id == lead.id).scalar()
        ),
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


# ---------- Day7：案例库管理（列表 / 检索预览 / 上下架） ----------

def _case_admin_view(c: Case) -> dict[str, Any]:
    """运营视角的案例全字段视图。

    与用户侧 case_to_dict 的差异：带 W7 Day6/Day7 的结构化报价字段 + 上下架状态。
    """
    return {
        "id": c.id,
        "title": c.title,
        "industry": c.industry,
        "scenario": c.scenario,
        "features": c.features,
        "tech_stack": c.tech_stack,
        "budget_min": c.budget_min,
        "budget_max": c.budget_max,
        "duration_weeks": c.duration_weeks,
        "source_type": c.source_type,
        "data_quality": c.data_quality,
        "review_status": c.review_status,
        "published": c.published,
        "vector_ok": bool(c.vector_id),
        "summary": c.summary,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


@router.get("/cases/retrieve-preview")
def cases_retrieve_preview(
    query: str,
    top_k: int = 5,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """检索预览：用真实用户问题预演线上检索结果。

    与诊断图 retrieve 节点完全同源（retrieve_cases），含下架过滤——
    运营下架一条案例后，在这里搜，立刻能看到它不再出现。
    ⚠️ 路由必须放在 /cases/{case_id} 类动态路由之前（export.csv 同款教训）。
    """
    from app.retrieval.retriever import retrieve_cases

    hits = retrieve_cases(query.strip(), top_k=min(max(top_k, 1), 10))
    return {"query": query.strip(), "items": hits}


@router.get("/cases")
def list_cases_admin(
    q: str | None = None,
    scenario: str | None = None,
    review_status: str | None = None,
    published: bool | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """运营视角案例列表（含下架的；user 侧检索接口只出上架的）。

    - q：模糊匹配 title / industry / scenario / features
    - scenario / review_status：精确匹配（scenario 前端给下拉）
    - published：true/false 精确筛选；缺省 = 全部（含下架）
    """
    query = db.query(Case)
    if q:
        like = f"%{q.strip()}%"
        from sqlalchemy import or_
        query = query.filter(
            or_(
                Case.title.ilike(like),
                Case.industry.ilike(like),
                Case.scenario.ilike(like),
                Case.features.ilike(like),
            )
        )
    if scenario:
        query = query.filter(Case.scenario == scenario.strip())
    if review_status:
        query = query.filter(Case.review_status == review_status.strip())
    if published is not None:
        query = query.filter(Case.published == published)

    cases = (
        query.order_by(Case.id.desc())
        .limit(min(limit, 500))
        .all()
    )
    return {"items": [_case_admin_view(c) for c in cases]}


class CasePublishBody(BaseModel):
    """上下架请求体。review_status 核验流转不在本期（案例审核是 Day8 议题）。"""
    published: bool


@router.patch("/cases/{case_id}")
def update_case_admin(
    case_id: int,
    body: CasePublishBody,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """案例上下架。

    下架 = published False：检索立即不召回（retrieve_cases 过滤），但
    DB 行 / 向量 / 正文文件全保留，重新上架零成本。
    """
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="案例不存在")
    case.published = body.published
    db.commit()
    db.refresh(case)
    logger.info("admin %s 把案例 %s %s", admin.id, case_id,
                "上架" if body.published else "下架")
    return {"case": _case_admin_view(case)}


# ---------- Day8：工单（worksheet：lead 转入的交付跟单） ----------

WS_STATUS_TEXT = {
    Worksheet.STATUS_TO_CONFIRM: "待确认",
    Worksheet.STATUS_COMMUNICATING: "沟通中",
    Worksheet.STATUS_QUOTED: "已报价",
    Worksheet.STATUS_WON: "已成交",
    Worksheet.STATUS_CLOSED: "已关闭",
}


def _ws_admin_view(ws: Worksheet, lead: Lead | None = None) -> dict[str, Any]:
    """运营视角工单数据（含状态中文文案 + 来源 lead 摘要）。"""
    return {
        "id": ws.id,
        "lead_id": ws.lead_id,
        "lead_name": lead.name if lead else None,
        "project_id": ws.project_id,
        "user_id": ws.user_id,
        "customer_name": ws.customer_name,
        "contact": ws.contact,
        "company": ws.company,
        "requirement_summary": ws.requirement_summary,
        "thread_id": ws.thread_id,
        "status": ws.status,
        "status_text": WS_STATUS_TEXT.get(ws.status, ws.status),
        "created_at": ws.created_at.isoformat() if ws.created_at else None,
        "updated_at": ws.updated_at.isoformat() if ws.updated_at else None,
    }


def _ws_note_to_dict(note: WorksheetNote, admin: User | None) -> dict[str, Any]:
    """工单时间线 → JSON（字段名与 _note_to_dict 对齐，前端复用同一时间线组件）。"""
    return {
        "id": note.id,
        "worksheet_id": note.worksheet_id,
        "admin_id": note.admin_id,
        "admin_username": admin.username if admin else None,
        "note_type": note.note_type,
        "content": note.content,
        "created_at": note.created_at.isoformat() if note.created_at else None,
    }


@router.post("/leads/{lead_id}/worksheet")
def convert_lead_to_worksheet(
    lead_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Day8：lead 转工单（字段映射 + 幂等）。

    映射：name→customer_name、phone→contact、company→company、
          project.raw_idea→requirement_summary、project.thread_id→thread_id。
    幂等：lead 已有工单则直接返回既有工单（created=False），不重复建。
    转入写一条 system 时间线（「从 Lead #x 转入」）。

    防御（人工验收 lead #2 500 的修复）：
    - 悬空 project_id（项目已删但 lead 还挂着）：按「无项目」处理，
      worksheet.project_id 写 None，不把悬空 id 带进 FK
    - closed 的 lead 不允许转工单（409）：已关闭 = 线索归档/客户流失，
      不该再进入交付跟单流程；要转先把 lead 状态改回非 closed
    """
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="lead 不存在")

    if lead.status == Lead.STATUS_CLOSED:
        raise HTTPException(
            status_code=409,
            detail="该 lead 已关闭（客户流失/归档），不能转为工单。如需跟进，请先把 lead 状态改为非「已关闭」再转。",
        )

    existing = db.query(Worksheet).filter(Worksheet.lead_id == lead_id).first()
    if existing is not None:
        lead_ref = db.get(Lead, existing.lead_id) if existing.lead_id else None
        return {"worksheet": _ws_admin_view(existing, lead_ref), "created": False}

    # 悬空引用防御：project_id 挂着的行不存在（历史脏数据 / FK 关闭期删的项目）
    # → 按「无项目」处理，project_id 写 None，不把悬空 id 写进 worksheets
    project = db.get(Project, lead.project_id) if lead.project_id else None
    resolved_project_id = project.id if project else None

    # 需求摘要映射：项目原始需求 → 回退 lead 备注 → 兜底文案（无 project 的 lead）
    requirement_summary = (
        (project.raw_idea if project else None)
        or lead.note
        or "（无原始需求记录）"
    )

    ws = Worksheet(
        lead_id=lead.id,
        project_id=resolved_project_id,
        user_id=lead.user_id,
        customer_name=lead.name,
        contact=lead.phone,
        company=lead.company,
        requirement_summary=requirement_summary,
        thread_id=project.thread_id if project else None,
        status=Worksheet.STATUS_TO_CONFIRM,
    )
    db.add(ws)
    db.flush()  # 拿 ws.id 再写时间线

    note = WorksheetNote(
        worksheet_id=ws.id,
        admin_id=admin.id,
        note_type=WorksheetNote.NOTE_SYSTEM,
        content=f"从 Lead #{lead.id}（{lead.name}）转入工单，状态：待确认",
    )
    db.add(note)
    db.commit()
    db.refresh(ws)
    logger.info("admin %s 把 lead %s 转为工单 %s", admin.id, lead_id, ws.id)
    return {"worksheet": _ws_admin_view(ws, lead), "created": True}


@router.get("/worksheets")
def list_worksheets(
    q: str | None = None,
    status: str | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """工单列表（按更新时间倒序）。

    - q：模糊匹配 customer_name / contact / company / requirement_summary
    - status：逗号分隔多选（与 leads 列表同口径）
    """
    statuses = [s.strip() for s in (status.split(",") if status else []) if s.strip()]
    valid_statuses = [s for s in statuses if s in Worksheet.ALL_STATUSES]

    query = db.query(Worksheet)
    if q:
        like = f"%{q.strip()}%"
        from sqlalchemy import or_
        query = query.filter(or_(
            Worksheet.customer_name.ilike(like),
            Worksheet.contact.ilike(like),
            Worksheet.company.ilike(like),
            Worksheet.requirement_summary.ilike(like),
        ))
    if valid_statuses:
        query = query.filter(Worksheet.status.in_(valid_statuses))

    worksheets = (
        query.order_by(Worksheet.updated_at.desc(), Worksheet.id.desc())
        .limit(min(limit, 200))
        .all()
    )
    lead_ids = {w.lead_id for w in worksheets if w.lead_id is not None}
    leads_map: dict[int, Lead] = {}
    if lead_ids:
        for ld in db.scalars(select(Lead).where(Lead.id.in_(lead_ids))).all():
            leads_map[ld.id] = ld
    return {"items": [_ws_admin_view(w, leads_map.get(w.lead_id) if w.lead_id else None)
                      for w in worksheets]}


@router.get("/worksheets/{ws_id}")
def get_worksheet_detail(
    ws_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """工单详情：工单数据 + 时间线（倒序）。

    时间线结构与 lead 详情一致（_ws_note_to_dict 对齐 _note_to_dict 字段名），
    前端复用同一时间线组件。
    """
    ws = db.get(Worksheet, ws_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="工单不存在")

    lead = db.get(Lead, ws.lead_id) if ws.lead_id else None
    notes_db = (
        db.query(WorksheetNote)
        .filter(WorksheetNote.worksheet_id == ws_id)
        .order_by(WorksheetNote.created_at.desc(), WorksheetNote.id.desc())
        .all()
    )
    admin_ids = {n.admin_id for n in notes_db if n.admin_id is not None}
    admins_map: dict[int, User] = {}
    if admin_ids:
        for a in db.scalars(select(User).where(User.id.in_(admin_ids))).all():
            admins_map[a.id] = a

    return {
        "worksheet": _ws_admin_view(ws, lead),
        # 合法下一步流转（前端据此渲染按钮；终态为空集 → 无按钮）
        "next_statuses": sorted(Worksheet.TRANSITIONS.get(ws.status, frozenset())),
        "notes": [_ws_note_to_dict(n, admins_map.get(n.admin_id)) for n in notes_db],
    }


class WorksheetStatusBody(BaseModel):
    """工单状态流转请求体。只收 status，其它字段不允许 API 改。"""
    status: str = Field(min_length=1, max_length=16)

    @field_validator("status")
    @classmethod
    def _v_status(cls, v: str) -> str:
        if v not in Worksheet.ALL_STATUSES:
            raise ValueError(f"status 必须是 {list(Worksheet.ALL_STATUSES)} 之一")
        return v


@router.patch("/worksheets/{ws_id}")
def transition_worksheet(
    ws_id: int,
    body: WorksheetStatusBody,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Day8：工单状态流转（状态机校验，非法流转 400）。

    - 合法流转：落状态 + 强制写一条 status_change 时间线
    - 非法流转（跳级 / 终态再动 / 倒流）：400 + 明确提示
    """
    ws = db.get(Worksheet, ws_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="工单不存在")

    new_status = body.status
    allowed = Worksheet.TRANSITIONS.get(ws.status, frozenset())
    if new_status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=(f"非法流转：{WS_STATUS_TEXT.get(ws.status, ws.status)} → "
                    f"{WS_STATUS_TEXT.get(new_status, new_status)}。"
                    f"当前状态仅允许流转到 "
                    f"{[WS_STATUS_TEXT.get(s) for s in allowed] or '（终态，不可再流转）'}"),
        )

    old_status = ws.status
    ws.status = new_status
    ws.updated_at = datetime.utcnow()

    note = WorksheetNote(
        worksheet_id=ws_id,
        admin_id=admin.id,
        note_type=WorksheetNote.NOTE_STATUS_CHANGE,
        content=(f"状态：{WS_STATUS_TEXT.get(old_status, old_status)} → "
                 f"{WS_STATUS_TEXT.get(new_status, new_status)}"),
    )
    db.add(note)
    db.commit()
    db.refresh(ws)
    db.refresh(note)
    lead = db.get(Lead, ws.lead_id) if ws.lead_id else None
    logger.info("admin %s 工单 %s 流转 %s → %s", admin.id, ws_id, old_status, new_status)
    return {
        "worksheet": _ws_admin_view(ws, lead),
        "note": _ws_note_to_dict(note, admin),
        "next_statuses": sorted(Worksheet.TRANSITIONS.get(new_status, frozenset())),
    }


# ---------- Day9：数据看板（admin 首页 /admin 的数据源） ----------

TREND_DAYS = 14

# W8 热身：看板统计时区口径改北京时间（Asia/Shanghai）。
# 旧口径 UTC 的 bug：北京 0~8 点产生的数据会被算进「前一天」（UTC 日期
# 还停在前一天），今日新增偏低、趋势错位一天。DB 里 created_at 仍存
# UTC（func.now()，不动库），只在「分桶/过滤」时换算：北京零点 → UTC
# 再比较。trend 的 date 键也是北京日期。
BJ_TZ = ZoneInfo("Asia/Shanghai")


def _bj_now() -> datetime:
    return datetime.now(BJ_TZ)


def _bj_date_key(dt_utc: datetime | None) -> str | None:
    """UTC naive datetime → 北京日期键（trend 分桶用）。"""
    if dt_utc is None:
        return None
    return dt_utc.replace(tzinfo=UTC).astimezone(BJ_TZ).date().isoformat()


def _bj_midnight_utc(bj_days_ago: int = 0) -> datetime:
    """北京「今天往前 bj_days_ago 天」的零点，换算成 UTC naive datetime。

    DB 存 UTC，与 created_at 比较必须同口径（naive UTC）。
    """
    bj_today = _bj_now().date() - timedelta(days=bj_days_ago)
    bj_midnight = datetime.combine(bj_today, dt_time.min, tzinfo=BJ_TZ)
    return bj_midnight.astimezone(UTC).replace(tzinfo=None)


def _count_today(db: Session, model, col) -> int:
    """按 北京时间今日零点 计数（换算成 UTC 与库同口径后比较）。"""
    today_start = _bj_midnight_utc()
    return (
        db.query(model)
        .filter(col >= today_start)
        .count()
    )


@router.get("/stats")
def get_admin_stats(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Day9：数据看板（全部实时查库，禁止写死）。

    返回：
    - cards：用户数/项目数/leads/工单（累计 + 今日新增）
    - funnel：转化漏斗 项目 → leads → 工单 → 已成交（各环节数字 + 环比转化率%）
    - trend：近 14 天每日新增 projects / leads（给前端画 SVG 柱状趋势）

    空表安全：count 天然返回 0；trend 用日期字典补齐缺日（没数据的日期 = 0，
    不缺格），除零保护：分母 0 时转化率返回 None（前端显示 —）。
    """
    # ---- 统计卡片 ----
    total_users = db.query(User).count()
    total_projects = db.query(Project).count()
    total_leads = db.query(Lead).count()
    total_worksheets = db.query(Worksheet).count()

    cards = {
        "users":       {"total": total_users,
                        "today": _count_today(db, User, User.created_at)},
        "projects":    {"total": total_projects,
                        "today": _count_today(db, Project, Project.created_at)},
        "leads":       {"total": total_leads,
                        "today": _count_today(db, Lead, Lead.created_at)},
        "worksheets":  {"total": total_worksheets,
                        "today": _count_today(db, Worksheet, Worksheet.created_at)},
    }

    # ---- 转化漏斗：项目 → leads → 工单 → 已成交 ----
    # 口径：leads 数取「有 project 归属的」才有可比性？——不，运营漏斗看的是
    # 整体盘子：诊断项目产生了多少留资、留资转化出多少工单、工单成交多少。
    # 各环节数字直接全量 count，转化率 = 下游/上游。
    won_worksheets = db.query(Worksheet).filter(
        Worksheet.status == Worksheet.STATUS_WON).count()

    def rate(down: int, up: int) -> float | None:
        """环比转化率（%），分母 0 → None（前端显示 —，不出 NaN/除零）。"""
        return round(down / up * 100, 1) if up > 0 else None

    funnel = {
        "projects": total_projects,
        "leads": total_leads,
        "worksheets": total_worksheets,
        "won": won_worksheets,
        # 各环节相对上一环的转化率
        "rates": {
            "project_to_lead": rate(total_leads, total_projects),
            "lead_to_worksheet": rate(total_worksheets, total_leads),
            "worksheet_to_won": rate(won_worksheets, total_worksheets),
        },
    }

    # ---- 近 14 天趋势：每日新增 projects / leads（北京时区分桶） ----
    # since = 北京「13 天前零点」换算成的 UTC（库口径），保证窗口恰好 14 个北京日
    since = _bj_midnight_utc(TREND_DAYS - 1)
    since_date = (_bj_now() - timedelta(days=TREND_DAYS - 1)).date()

    proj_rows = (
        db.query(Project.created_at)
        .filter(Project.created_at >= since)
        .all()
    )
    lead_rows = (
        db.query(Lead.created_at)
        .filter(Lead.created_at >= since)
        .all()
    )

    def _day_key(dt: datetime | None) -> str | None:
        # created_at 是 UTC（func.now()），换算到北京时区后按北京日期分桶
        return _bj_date_key(dt)

    proj_counts: dict[str, int] = {}
    for (dt,) in proj_rows:
        k = _day_key(dt)
        if k:
            proj_counts[k] = proj_counts.get(k, 0) + 1
    lead_counts: dict[str, int] = {}
    for (dt,) in lead_rows:
        k = _day_key(dt)
        if k:
            lead_counts[k] = lead_counts.get(k, 0) + 1

    # 补齐 14 天（含今天），缺日 = 0
    trend = []
    for i in range(TREND_DAYS):
        day = since_date + timedelta(days=i)
        key = day.isoformat()
        trend.append({
            "date": key,
            "projects": proj_counts.get(key, 0),
            "leads": lead_counts.get(key, 0),
        })

    return {"cards": cards, "funnel": funnel, "trend": trend, "trend_days": TREND_DAYS}


# ---------- W8 Day2/3：诊断回放 · 会话成本汇总 ----------

@router.get("/traces")
def list_traces(
    limit: int = 50,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """会话级 trace 聚合（按最后活动倒序），每行附估算成本（元，4 位小数）。

    - limit：默认 50，硬上限 200（防 trace.jsonl 增大后接口变慢）
    - 成本 = prompt/1M × DEEPSEEK_PRICE_PROMPT + completion/1M ×
      DEEPSEEK_PRICE_COMPLETION（config/env 可调，估算非结算）
    - totals 是「全部会话」合计（不受 limit 影响），前端渲染合计行
    - 文件不存在/空 → items 空列表 + 全 0 totals，不报错
    """
    from app.agent.trace import aggregate_traces
    from app.config import DEEPSEEK_PRICE_COMPLETION, DEEPSEEK_PRICE_PROMPT

    def cost(prompt: int, completion: int) -> float:
        return round(
            prompt / 1_000_000 * DEEPSEEK_PRICE_PROMPT
            + completion / 1_000_000 * DEEPSEEK_PRICE_COMPLETION,
            4,
        )

    sessions = list(aggregate_traces().values())
    # 全量合计（先算再截断）
    total_prompt = sum(s["prompt_tokens"] for s in sessions)
    total_completion = sum(s["completion_tokens"] for s in sessions)
    totals = {
        "sessions": len(sessions),
        "node_count": sum(s["node_count"] for s in sessions),
        "llm_count": sum(s["llm_count"] for s in sessions),
        "prompt_tokens": total_prompt,
        "completion_tokens": total_completion,
        "cost_cny": cost(total_prompt, total_completion),
        "price": {  # 回显单价，前端展示口径透明
            "prompt_per_m": DEEPSEEK_PRICE_PROMPT,
            "completion_per_m": DEEPSEEK_PRICE_COMPLETION,
        },
    }

    sessions.sort(key=lambda s: s["last_active_at"] or "", reverse=True)
    safe_limit = max(1, min(limit, 200))
    items = []
    for s in sessions[:safe_limit]:
        row = dict(s)
        row["cost_cny"] = cost(s["prompt_tokens"], s["completion_tokens"])
        items.append(row)

    logger.info("admin %s 查 trace 汇总：%d 会话，返回 %d 行",
                admin.id, len(sessions), len(items))
    return {"items": items, "totals": totals, "limit": safe_limit}


@router.get("/trace/{thread_id}")
def get_trace(
    thread_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """查某诊断会话的完整调用链（节点 + LLM 两层，时间序）。

    thread_id 支持图内完整键（project-<uuid>）或裸 uuid（admin 页面常用）。
    数据源 logs/trace.jsonl（追加写），只读不动；仅 admin 可见。
    """
    from app.agent.trace import read_trace

    items = read_trace(thread_id)
    logger.info("admin %s 查询 trace thread=%s 共 %d 条",
                admin.id, thread_id, len(items))
    return {
        "thread_id": thread_id,
        "count": len(items),
        "node_count": sum(1 for r in items if r.get("type") == "node"),
        "llm_count": sum(1 for r in items if r.get("type") == "llm"),
        "items": items,
    }
