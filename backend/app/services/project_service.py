"""项目服务：Project CRUD + 会话消息存取。

业务代码统一通过本服务访问数据库，不直接操作 ORM 模型。
"""

from uuid import uuid4

from sqlalchemy.orm import Session

from app.db.models import Conversation, Project


def create_project(db: Session, title: str, raw_idea: str | None = None,
                   user_id: int | None = None) -> Project:
    """新建项目（状态默认 diagnosing）。thread_id 供 LangGraph 会话隔离。"""
    project = Project(
        title=title, raw_idea=raw_idea, user_id=user_id,
        thread_id=uuid4().hex,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def get_project(db: Session, project_id: int) -> Project | None:
    return db.get(Project, project_id)


def list_projects(db: Session, limit: int = 50, offset: int = 0,
                  user_id: int | None = None,
                  q: str | None = None,
                  statuses: list[str] | None = None) -> list[Project]:
    """按创建时间倒序列出项目（Day4：传 user_id 则只看该用户的）。

    Day3 列表增强：
    - q: 标题模糊匹配（LIKE，不分大小写）；空 / None = 不过滤
    - statuses: 状态白名单（IN）；空 / None = 不过滤
    """
    query = db.query(Project)
    if user_id is not None:
        query = query.filter(Project.user_id == user_id)
    if q:
        # SQLAlchemy 不分大小写：func.lower(col).like(func.lower(:v))
        # 标题前端无大小写要求，Python 侧先 lower 更省力
        query = query.filter(Project.title.ilike(f"%{q.strip()}%"))
    if statuses:
        # 空串 / 未知状态过滤掉，避免脏数据导致 IN 空集
        valid = [s for s in statuses if s]
        if valid:
            query = query.filter(Project.status.in_(valid))
    # created_at DESC + id DESC：同秒创建的项目用 id（自增）兜底稳定排序
    return query.order_by(Project.created_at.desc(), Project.id.desc()).offset(offset).limit(limit).all()


def update_project(db: Session, project_id: int, **fields) -> Project | None:
    """更新项目字段（只允许白名单字段）。"""
    allowed = {"title", "raw_idea", "status", "plan", "budget_min", "budget_max", "user_id"}
    project = db.get(Project, project_id)
    if project is None:
        return None
    for key, value in fields.items():
        if key in allowed:
            setattr(project, key, value)
    db.commit()
    db.refresh(project)
    return project


def delete_project(db: Session, project_id: int) -> bool:
    """删除项目（级联删除对话记录）。"""
    project = db.get(Project, project_id)
    if project is None:
        return False
    db.delete(project)
    db.commit()
    return True


def add_message(db: Session, project_id: int, role: str, content: str) -> Conversation:
    """向项目追加一条对话消息。"""
    msg = Conversation(project_id=project_id, role=role, content=content)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def get_messages(db: Session, project_id: int) -> list[Conversation]:
    """按时间正序获取项目的全部对话消息。"""
    return (
        db.query(Conversation)
        .filter(Conversation.project_id == project_id)
        .order_by(Conversation.created_at.asc(), Conversation.id.asc())
        .all()
    )
