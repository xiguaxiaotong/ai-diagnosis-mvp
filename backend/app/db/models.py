"""P10 数据层：表定义（SQLAlchemy 2.0 风格）。

5 张表：
- users          用户（需求方，MVP 阶段匿名也可用）
- projects       项目（一次诊断 = 一个项目，方案/预算挂在这里）
- conversations  对话消息（诊断过程的多轮对话记录）
- cases          案例（脱敏入库的历史项目，关联 Chroma 向量 id）
- leads          留资（Day4；方案确认后的对接申请，含 5 态跟单状态机 Day5）
- lead_notes     跟进记录（Day6；运营手动记录 + 状态变更自动写 system 类型）
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 登录名（Day4 账户系统）：旧「匿名用户」行此列为 NULL，不参与登录
    username: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    # pbkdf2_sha256$迭代$salt$hash（标准库哈希，无新依赖）
    password_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    name: Mapped[str] = mapped_column(String(64), default="匿名用户")
    # W7 Day2：邮箱（重置密码发到邮箱、个人中心可换绑）。
    #   注册时不收 → nullable；后续补录鼓励但不强求。
    #   唯一性：unique=True 给 DB 兜底，应用层也会先查再写。
    email: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    projects: Mapped[list["Project"]] = relationship(back_populates="user")


class AuthSession(Base):
    """登录会话（Day4）：token → user。存 DB 保证重启不失效（Day3 验收）。

    MVP 不上 JWT 库：随机 token + DB 查表足够，过期 30 天，logout 删行。
    """
    __tablename__ = "auth_sessions"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime)

    user: Mapped["User"] = relationship()


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

    # 结构化实体记忆（每轮 understand 节点后写入的 requirements JSON）：
    # 已确认字段的持久副本，独立于图 checkpoint，供「修改需求」等程序直接读写
    req_profile: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 方案公开分享令牌（用户点「生成分享链接」时生成；NULL = 未开启分享）
    share_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)

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
    """案例（历史项目知识库条目）。

    两类来源共用一张表：
    - 管理端上传文档（Week4）：只填基础字段，正文走 file_path 文档
    - CSV 种子导入（W7 Day6）：补齐结构化报价字段（scenario/budget_*/…），
      供检索召回 + 方案生成时参考报价档位

    review_status 是「待核验 / 已核验」的数据质量口径，别和未来案例上下架状态混用。
    """
    __tablename__ = "cases"

    # W7 Day6：审核状态（数据核验口径，非上下架）
    REVIEW_PENDING = "pending"    # 待核验
    REVIEW_VERIFIED = "verified"  # 已核验

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(128))
    industry: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    file_path: Mapped[str | None] = mapped_column(String(256), nullable=True)  # 原始文档路径
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # 脱敏摘要
    vector_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 向量库 doc_id 前缀
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # ---------- W7 Day6：CSV 种子案例结构化字段 ----------
    scenario: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)  # 场景
    features: Mapped[str | None] = mapped_column(Text, nullable=True)  # 功能清单（顿号/分号分隔）
    tech_stack: Mapped[str | None] = mapped_column(Text, nullable=True)  # 技术栈
    budget_min: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 预算下限（元）
    budget_max: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 预算上限（元）
    duration_weeks: Mapped[str | None] = mapped_column(String(16), nullable=True)  # 工期（"1-2" 区间串）
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)  # 来源链接
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 来源类型
    collected_at: Mapped[date | None] = mapped_column(Date, nullable=True)  # 采集时间
    data_quality: Mapped[str | None] = mapped_column(String(128), nullable=True)  # 数据口径说明
    review_status: Mapped[str] = mapped_column(
        String(16), default=REVIEW_PENDING, server_default=REVIEW_PENDING,
    )  # 审核状态：pending 待核验 / verified 已核验


class PasswordResetToken(Base):
    """W7 Day1：邮箱重置密码令牌。

    设计：
    - token：URL-safe 32 字节随机串（与 AuthSession 同规格）
    - user_id：FK → users（用户被删 → 令牌一起删，避免孤儿）
    - expires_at：30 分钟过期（业内主流，比 1h 更安全；超期 = 失效）
    - used_at：NULL = 未用；改密成功后置位 = 单次性，已用 token 不可再消费
    """
    __tablename__ = "password_reset_tokens"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Lead(Base):
    """W7 Day4：方案确认后的对接申请（lead = 销售线索）。
    Day5 拓展：跟单状态机细化到 5 态（运营真实需要）。

    设计：
    - project_id 一对一（UNIQUE）：一个项目一条 lead，重复提交 = 覆盖更新。
      用户改方案后想重新联系时，运营应该看到的是「最新一次」联系方式，
      而不是把同一项目的多个历史 lead 摊开。
    - user_id 冗余存一份：项目可能被删（用户手误），但 lead 留着仍可人工跟进。
    - status 五态（运营跟单状态机）：
        pending    待联系  ← 用户提交后默认
        contacted  已联系  ← 运营首次电话沟通后
        quoted     已报价  ← 运营发过报价方案后
        won        已成交  ← 客户签合同
        closed     已关闭  ← 客户流失 / 长期无意向 / 归档
      运营手动改；本期只在 admin 后台改；客户端只读。
      Day4 的 done → closed（迁移 0005），其它值不变。
    - 字段必填：name / phone（核心联系方式，靠电话回访不是邮件）。
      company / note 选填，但电话回访会问公司，让 phone + company 同时给齐。
    """
    __tablename__ = "leads"

    STATUS_PENDING = "pending"
    STATUS_CONTACTED = "contacted"
    STATUS_QUOTED = "quoted"
    STATUS_WON = "won"
    STATUS_CLOSED = "closed"
    # 给 admin 接口用：合法白名单
    ALL_STATUSES: tuple[str, ...] = (
        STATUS_PENDING, STATUS_CONTACTED, STATUS_QUOTED, STATUS_WON, STATUS_CLOSED,
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"),
        unique=True, index=True,
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    name: Mapped[str] = mapped_column(String(64))
    phone: Mapped[str] = mapped_column(String(20))
    company: Mapped[str | None] = mapped_column(String(128), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=STATUS_PENDING)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    notes: Mapped[list["LeadNote"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan",
    )


class LeadNote(Base):
    """W7 Day6：leads 跟进记录 / 时间线。

    三种 note_type：
    - manual    运营手动写的跟进（电话沟通要点 / 微信加好友 / 客户反馈等）
    - status_change  系统自动写（运营改 status 时落地，方便回溯「何时改成 won」）
    - system    系统事件（如「用户重新提交联系方式，status 重置 pending」）

    关联：
    - lead_id FK CASCADE：lead 删了 → 笔记一起删（不留孤儿）
    - admin_id FK SET NULL：admin 账号被删 → 笔记保留为 NULL（谁写的可追溯丢失，但内容不丢）
    """
    __tablename__ = "lead_notes"

    NOTE_MANUAL = "manual"
    NOTE_STATUS_CHANGE = "status_change"
    NOTE_SYSTEM = "system"
    ALL_NOTE_TYPES: tuple[str, ...] = (NOTE_MANUAL, NOTE_STATUS_CHANGE, NOTE_SYSTEM)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lead_id: Mapped[int] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), index=True,
    )
    admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    note_type: Mapped[str] = mapped_column(String(16), default=NOTE_MANUAL)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(),
    )

    lead: Mapped["Lead"] = relationship(back_populates="notes")
