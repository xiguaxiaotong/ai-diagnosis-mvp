"""alembic 环境配置：把项目 ORM 元数据 + SQLite URL 注入。

W7 Day1 引入 alembic：所有改模型都必出迁移，alembic upgrade head 是启动入口。
"""
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# 让 alembic 跑在 backend/ 目录里也能 import app.*
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import SQLITE_PATH  # noqa: E402
from app.db.database import Base  # noqa: E402
import app.db.models  # noqa: F401,E402  # 确保所有模型 import 进 Base.metadata

config = context.config

# 用代码覆盖 ini 里的 sqlalchemy.url，避免 ini 文件里出现本地绝对路径
config.set_main_option(
    "sqlalchemy.url",
    f"sqlite:///{SQLITE_PATH}",
)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite ALTER 走 batch 模式
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite 必加
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()