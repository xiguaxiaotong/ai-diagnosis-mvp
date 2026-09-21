"""项目服务：Project CRUD + 会话消息存取。

业务代码统一通过本服务访问数据库，不直接操作 ORM 模型。
"""

from sqlalchemy.orm import Session

from app.db.models import Conversation, Project


def create_project(db: Session, title: str, raw_idea: str | None = None,
                   user_id: int | None = None) -> Project:
    """新建项目（状态默认 diagnosing）。"""
    project = Project(title=title, raw_idea=raw_idea, user_id=user_id)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def get_project(db: Session, project_id: int) -> Project | None:
    return db.get(Project, project_id)


def list_projects(db: Session, limit: int = 50, offset: int = 0) -> list[Project]:
    """按创建时间倒序列出项目。"""
    return (
        db.query(Project)
        .order_by(Project.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


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
