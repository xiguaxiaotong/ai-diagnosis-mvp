"""P10 数据层：SQLite 连接与会话管理。

W7 Day1 改：建表/改表统一走 alembic upgrade head。
init_db() 只剩「跑迁移 + 提供 engine」两个职责，旧的手写 ALTER 全部废弃。

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
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import SQLITE_PATH

# check_same_thread=False：FastAPI 多线程访问 SQLite 必需
engine = create_engine(
    f"sqlite:///{SQLITE_PATH}",
    connect_args={"check_same_thread": False},
    echo=False,
)


# W7 Day4：业务运行时开启 SQLite 外键约束。
# SQLite 默认 FK 是关闭的（PRAGMA foreign_keys = OFF），这会让 schema 里的
#   ON DELETE SET NULL / ON DELETE CASCADE / ON DELETE RESTRICT 都形同虚设。
# alembic 内部已自带开关，迁移期不需要管；这里只对应用层连接生效。
@event.listens_for(engine, "connect")
def _enable_sqlite_fk(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON")
    cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


def init_db() -> None:
    """W7 Day1：所有表结构变更统一走 alembic，本函数只负责「跑迁移到 head」。

    旧的手写 PRAGMA + ALTER TABLE 已废弃（迁移历史已写入 alembic/versions/0001_baseline）。
    """
    from pathlib import Path

    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)

    # 不管从哪里启动（uvicorn / pytest / 脚本），用绝对路径喂 alembic，避免
    # uvicorn 注入的 sys.path / cwd 把相对路径带偏
    backend_dir = Path(__file__).resolve().parent.parent.parent  # backend/app/db → backend
    if not (backend_dir / "alembic.ini").exists():
        # 兜底：如果 alembic 没起跑（极少见），退回旧行为
        from app.db import models  # noqa: F401
        Base.metadata.create_all(bind=engine)
        return

    from alembic import command
    from alembic.config import Config

    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    command.upgrade(cfg, "head")


def get_db():
    """FastAPI 依赖：每个请求一个会话，用完自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()