-- P10 数据层：SQLite 建表脚本（参考/手工初始化用）
--
-- 说明：应用启动时 database.init_db() 会通过 SQLAlchemy 自动建表，
-- 本脚本用于手动初始化或 dbatools 查看结构时参考。

-- 用户表
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        VARCHAR(64)  NOT NULL DEFAULT '匿名用户',
    phone       VARCHAR(20)  UNIQUE,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 项目表（一次诊断 = 一个项目）
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER      REFERENCES users(id) ON DELETE SET NULL,
    title       VARCHAR(128) NOT NULL DEFAULT '未命名项目',
    raw_idea    TEXT,                        -- 用户原始业务想法
    status      VARCHAR(20)  NOT NULL DEFAULT 'diagnosing',  -- diagnosing/plan_generated/confirmed/delivering/done
    plan        TEXT,                        -- 方案 JSON
    budget_min  REAL,                        -- 预算区间下限（元）
    budget_max  REAL,                        -- 预算区间上限（元）
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);

-- 对话消息表
CREATE TABLE IF NOT EXISTS conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER      NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    role        VARCHAR(16)  NOT NULL,       -- user/assistant/system
    content     TEXT         NOT NULL,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_conversations_project ON conversations(project_id);

-- 案例表（脱敏入库，关联 Chroma 向量）
CREATE TABLE IF NOT EXISTS cases (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       VARCHAR(128) NOT NULL,
    industry    VARCHAR(64),                 -- 行业标签
    file_path   VARCHAR(256),                -- 原始文档路径
    summary     TEXT,                        -- 脱敏摘要
    vector_id   VARCHAR(64),                 -- Chroma 向量 id
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_cases_industry ON cases(industry);
