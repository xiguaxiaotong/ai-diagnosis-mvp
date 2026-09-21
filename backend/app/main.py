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
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import FRONTEND_ORIGIN
from app.db.database import get_db, init_db
from app.infra.callbacks import setup_logging
from app.services import project_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时初始化日志与数据库建表。"""
    setup_logging()
    init_db()
    yield


app = FastAPI(title="AI Diagnosis MVP", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
def list_projects(limit: int = 50, db: Session = Depends(get_db)):
    projects = project_service.list_projects(db, limit=limit)
    return {"items": [_project_to_dict(p) for p in projects]}


@app.post("/api/projects", status_code=201)
def create_project(body: ProjectCreate, db: Session = Depends(get_db)):
    p = project_service.create_project(db, title=body.title, raw_idea=body.raw_idea)
    return _project_to_dict(p)


@app.get("/api/projects/{project_id}")
def get_project(project_id: int, db: Session = Depends(get_db)):
    p = project_service.get_project(db, project_id)
    if p is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    data = _project_to_dict(p)
    data["messages"] = [
        {"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
        for m in project_service.get_messages(db, project_id)
    ]
    return data


@app.patch("/api/projects/{project_id}")
def update_project(project_id: int, body: ProjectUpdate, db: Session = Depends(get_db)):
    p = project_service.update_project(db, project_id, **body.model_dump(exclude_none=True))
    if p is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return _project_to_dict(p)


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    if not project_service.delete_project(db, project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"deleted": True}
