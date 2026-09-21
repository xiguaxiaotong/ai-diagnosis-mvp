"""P10 数据层：表定义（SQLAlchemy 2.0 风格）。

4 张表：
- users          用户（需求方，MVP 阶段匿名也可用）
- projects       项目（一次诊断 = 一个项目，方案/预算挂在这里）
- conversations  对话消息（诊断过程的多轮对话记录）
- cases          案例（脱敏入库的历史项目，关联 Chroma 向量 id）
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), default="匿名用户")
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    projects: Mapped[list["Project"]] = relationship(back_populates="user")


class Project(Base):
    __tablename__ = "projects"

    # 项目状态机：diagnosing 诊断中 → plan_generated 方案已生成
    #            → confirmed 方案确认 → delivering 交付中 → done 已完成
    STATUS_DIAGNOSING = "diagnosing"
    STATUS_PLAN_GENERATED = "plan_generated"
    STATUS_CONFIRMED = "confirmed"
    STATUS_DELIVERING = "delivering"
    STATUS_DONE = "done"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(128), default="未命名项目")
    raw_idea: Mapped[str | None] = mapped_column(Text, nullable=True)  # 用户原始业务想法
    status: Mapped[str] = mapped_column(String(20), default=STATUS_DIAGNOSING, index=True)
    # 图会话线程 id（uuid）：SQLite rowid 删除后会被复用，若用项目 id 当 thread_id，
    # 新项目会继承已删项目残留的 LangGraph 状态（轮次虚高/误确认），必须全局唯一
    thread_id: Mapped[str | None] = mapped_column(String(36), unique=True, nullable=True)

    # 方案与预算（AI 生成后写入；预算按商业计划书要求存区间）
    plan: Mapped[str | None] = mapped_column(Text, nullable=True)  # 方案 JSON
    budget_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    budget_max: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User | None"] = relationship(back_populates="projects")
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Conversation(Base):
    __tablename__ = "conversations"

    # 角色：user 用户 / assistant AI / system 系统
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    project: Mapped["Project"] = relationship(back_populates="conversations")


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(128))
    industry: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    file_path: Mapped[str | None] = mapped_column(String(256), nullable=True)  # 原始文档路径
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # 脱敏摘要
    vector_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # Chroma 中向量 id
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
