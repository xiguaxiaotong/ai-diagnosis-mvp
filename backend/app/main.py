"""FastAPI 入口。

M0 阶段接口：
- GET  /                    欢迎信息
- GET  /api/health          健康检查
- GET  /api/projects        项目列表
- POST /api/projects        创建项目
- GET  /api/projects/{id}   项目详情（含对话记录）
- PATCH /api/projects/{id}  更新项目（标题/状态/方案/预算）
- DELETE /api/projects/{id} 删除项目

后续阶段：
- POST /api/chat          对话诊断（SSE 流式）
- POST /api/cases/upload  案例上传
"""

from contextlib import asynccontextmanager
import json
import secrets
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.cases import router as cases_router
from app.api.diagnosis import router as diagnosis_router
from app.api.leads import router as leads_router
from app.config import FRONTEND_ORIGIN
from app.db.database import get_db, init_db
from app.db.models import Project
from app.infra.callbacks import setup_logging
from app.services import project_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时初始化日志与数据库建表。"""
    setup_logging()
    init_db()
    yield


app = FastAPI(title="AI Diagnosis MVP", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN, "http://localhost:3000"],
    # 局域网真机联调：手机访问 http://192.168.x.x:3000 时放行（生产走 Nginx 同域，不受影响）
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|192\.168(\.\d+){2})(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# P6 诊断 API（SSE 对话 / 方案详情 / 确认循环）
app.include_router(diagnosis_router)
# P2 案例 API（上传/列表/详情/删除）
app.include_router(cases_router)
# W7 Day4：方案确认后的对接申请（lead）
app.include_router(leads_router)
# Day4 账户系统（注册/登录/会话）
from app.api.auth import router as auth_router  # noqa: E402
app.include_router(auth_router)


@app.get("/")
def root():
    return {"message": "AI Diagnosis MVP backend is running"}


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ---------- 项目接口（联调用） ----------


class ProjectCreate(BaseModel):
    title: str
    raw_idea: str | None = None


class ProjectUpdate(BaseModel):
    title: str | None = None
    status: str | None = None
    plan: str | None = None
    budget_min: float | None = None
    budget_max: float | None = None


def _project_to_dict(p) -> dict[str, Any]:
    return {
        "id": p.id,
        "title": p.title,
        "raw_idea": p.raw_idea,
        "status": p.status,
        "budget_min": p.budget_min,
        "budget_max": p.budget_max,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@app.get("/api/projects")
def list_projects(
    q: str | None = None,
    status: str | None = None,  # 逗号分隔多选，如 "diagnosing,confirmed"
    limit: int = 50,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """项目列表：只看自己的（Day4 账户隔离）；Day3 加 q+status 过滤。

    - q: 标题模糊匹配（不分大小写）
    - status: 逗号分隔多状态过滤（空 OR 任一匹配）；空 / 缺省 = 不过滤
    - 仍按 created_at DESC 排序
    """
    statuses = [s.strip() for s in (status.split(",") if status else []) if s.strip()]
    projects = project_service.list_projects(
        db, limit=limit, user_id=user.id, q=q, statuses=statuses or None,
    )
    return {"items": [_project_to_dict(p) for p in projects]}


@app.post("/api/projects", status_code=201)
def create_project(
    body: ProjectCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    p = project_service.create_project(
        db, title=body.title, raw_idea=body.raw_idea, user_id=user.id
    )
    return _project_to_dict(p)


@app.get("/api/projects/{project_id}")
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    p = project_service.get_project(db, project_id)
    if p is None or p.user_id != user.id:
        raise HTTPException(status_code=404, detail="项目不存在")
    data = _project_to_dict(p)
    data["messages"] = [
        {"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
        for m in project_service.get_messages(db, project_id)
    ]
    return data


@app.patch("/api/projects/{project_id}")
def update_project(
    project_id: int,
    body: ProjectUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    p = project_service.get_project(db, project_id)
    if p is None or p.user_id != user.id:
        raise HTTPException(status_code=404, detail="项目不存在")
    p = project_service.update_project(db, project_id, **body.model_dump(exclude_none=True))
    return _project_to_dict(p)


@app.delete("/api/projects/{project_id}")
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    p = project_service.get_project(db, project_id)
    if p is None or p.user_id != user.id:
        raise HTTPException(status_code=404, detail="项目不存在")
    project_service.delete_project(db, project_id)
    return {"deleted": True}


# ---------- 方案分享（转化优化：老板转给合伙人 = 免费传播） ----------


@app.post("/api/projects/{project_id}/share")
def create_share_link(
    project_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """生成（或返回已有的）公开分享令牌。仅项目所有者可操作。"""
    p = project_service.get_project(db, project_id)
    if p is None or p.user_id != user.id:
        raise HTTPException(status_code=404, detail="项目不存在")
    if not p.share_token:
        p.share_token = secrets.token_urlsafe(12)
        db.commit()
    return {"share_token": p.share_token}


@app.get("/api/share/{token}")
def get_shared_plan(token: str, db: Session = Depends(get_db)):
    """公开只读方案页数据（无需登录）：合伙人/朋友打开链接即可看方案。

    刻意不返回 raw_idea / messages（对话隐私），只给方案本体。
    """
    p = db.scalar(select(Project).where(Project.share_token == token))
    if p is None:
        raise HTTPException(status_code=404, detail="分享链接不存在或已失效")
    solution = json.loads(p.plan) if p.plan else None
    return {
        "title": p.title,
        "status": p.status,
        "budget_min": p.budget_min,
        "budget_max": p.budget_max,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "solution": solution,
    }
