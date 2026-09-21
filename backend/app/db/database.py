"""P10 数据层：SQLite 连接与会话管理。

用法（FastAPI 依赖注入）：
    from app.db.database import get_db

    @router.get("/projects")
    def list_projects(db: Session = Depends(get_db)):
        ...

用法（脚本/服务层）：
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        ...
    finally:
        db.close()
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import SQLITE_PATH

# check_same_thread=False：FastAPI 多线程访问 SQLite 必需
engine = create_engine(
    f"sqlite:///{SQLITE_PATH}",
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


def init_db() -> None:
    """建表（已存在则跳过）。导入 models 以确保表定义已注册。"""
    from app.db import models  # noqa: F401

    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI 依赖：每个请求一个会话，用完自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
