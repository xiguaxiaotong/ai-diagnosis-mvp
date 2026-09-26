# AI 诊断 MVP

描述业务需求 → AI 智能体诊断 → 生成方案 / 预算区间 / 可行性评估。

AIAgent 赋能服务平台（商业计划书见「初创团队文档」）M0 阶段产物。

> 面向最终用户的使用文档：[docs/用户使用说明.md](docs/用户使用说明.md)

## 技术栈

- 后端：FastAPI + DeepSeek（OpenAI 兼容协议）+ SQLAlchemy 2.0 + SQLite
- 模型：deepseek-chat（对话流式）+ BAAI/bge-small-zh-v1.5（本地 Embedding，无需 key）
- 前端：Next.js 14 (App Router) + TypeScript
- 运行：本地 Python/Node 即可，无需 Docker

## 新人上手（5 分钟跑起来）

### 0. 前置条件

- Python 3.11+
- Node.js 18+
- 一个 DeepSeek API key（https://platform.deepseek.com 免费注册申请）

### 1. 配置环境变量

    cp .env.example .env

编辑 `.env`，填入你的 key：

    DEEPSEEK_API_KEY=sk-你的key

### 2. 启动后端（终端 1）

    cd backend
    pip install -r requirements.txt
    uvicorn app.main:app --reload --port 8000

- 启动时自动建表（`data/sqlite.db`），首次运行会自动从国内镜像下载
  bge-small 模型（约 100MB，仅一次）
- 验证：浏览器打开 http://localhost:8000/docs 能看到接口文档

### 3. 启动前端（终端 2）

    cd frontend
    npm install
    npm run dev

### 4. 验证联调

1. 打开 http://localhost:3000 → 首页显示「后端状态：● 已连接」
2. 点「历史项目」→「+ 新建演示项目」→ 列表出现新项目
3. 点「删除」→ 项目消失（完整 CRUD 通路）

## 测试（pytest，W8 Day4 起统一入口）

旧验收脚本（test_w2d1 ~ test_w5d6 / test_day2-4 / run_regression.py 等）
已全部收编进 pytest 套件并删除，git 历史可查。run_regression.py 已废弃，
一律用 pytest：

    cd backend
    python -m pytest                          # 全量（含黄金集真 LLM ≈¥0.1 + bge 慢测试，~3 分钟）
    python -m pytest -m "not llm and not slow" # 快速回归（stub LLM + 纯函数，~1 分钟，零 token）
    python -m pytest tests/golden -q           # understand 黄金集评估（改 prompt 前后必跑，基线见 tests/golden/BASELINE.md）

套件结构（backend/tests/）：

    conftest.py          # 公共基建：临时库 env 隔离（限流默认关）/ TestClient / stub LLM / 造项目
    test_budget.py       # 预算规则引擎（T-1 已关闭：corpus 白名单 + 幂等回归）
    test_models.py       # 纯函数：意图分流 / 确认路由 / 文档切分 / embedding / CRUD
    test_diagnosis.py    # 诊断图：追问循环 / 5 轮强制 / 方案结构 / 确认循环话术
    test_generate_fallback.py # generate 输出异常分级容错（T-2：可选补默认/必填重试）
    test_consult.py      # 咨询分流：不烧 token / 不消耗轮次 / 不打断确认
    test_api.py          # HTTP 层：项目 CRUD / SSE 事件序列 / 确认接口 / 404
    test_security.py     # 安全回归（pentest_* 5 脚本收编）：意图对抗 / 坏输出容错 /
                         #   并发锁 busy / 文件注入 / 限流（诊断5/min·注册10/h·登录失败20/h）
    test_retrieval.py    # 向量库增删查 / 文档入库 / 案例检索端到端（slow：本地 bge）
    test_case_vectorize.py # 案例自动向量化：入库即检索 / 幂等 / 失败不阻断 / 上下架联动
    test_admin.py        # 案例管理 API + admin 权限
    golden/              # understand 黄金集（30 条种子 CSV 真实需求，真 LLM 评估）

scripts/pentest_*（W7 破甲系列 5 脚本）已收编进 test_security.py 并删除。
其余 scripts/test_day7/8/9、test_w8d1_trace、test_w8d23_traces 为近期
里程碑验收脚本，独立运行（同样自带临时库隔离），后续按需收编。

marker 说明：`llm` 真实 DeepSeek 调用；`slow` 本地 bge 模型加载等慢测试。

## 数据库备份与恢复（SQLite，W9 起）

自动备份：`backend/scripts/backup_db.py`（sqlite3 backup API 热备，不停服务），
产物在 `backend/backups/sqlite_YYYYMMDD_HHMMSS.db`，保留最近 14 份。

Windows 计划任务（每天凌晨 3 点，自己执行一次即可，之后全自动）：

    schtasks /Create /TN "AIDiagnosis-DBBackup" /SC DAILY /ST 03:00 ^
      /TR "cmd /c cd /d D:/ai-diagnosis-mvp/backend && C:/Users/31905/miniconda3/python.exe scripts/backup_db.py >> backups/backup.log 2>&1"

查看/删除：`schtasks /Query /TN "AIDiagnosis-DBBackup" /V`、
`/TN ... /Delete`。恢复步骤见下。

### 恢复步骤（主库损坏/误删时）

1. 停后端：`docker compose stop backend`（或本地 Ctrl+C uvicorn）
2. 演练验证备份可用（integrity_check + 核心表行数，不碰主库）：

       cd backend
       python scripts/restore_drill.py

3. 用最新备份覆盖主库（先留一份现场以便排查）：

       cd backend
       move data\sqlite.db data\sqlite.db.broken
       copy backups\<最新备份>.db data\sqlite.db

4. 重启后端，跑快速档 pytest 确认全绿：

       python -m pytest -m "not llm and not slow"

5. 冒烟：打开演示站发起一条新诊断，能正常追问/出方案即恢复完成

说明：只备份主库（业务数据），checkpoints.sqlite 不备份——它是进行中
对话的中间态，损坏只影响当前会话，新对话照常。

## 目录结构

    backend/app/
    ├── main.py          # FastAPI 入口（健康检查 + 项目 CRUD）
    ├── config.py        # 统一配置（.env 自动加载）
    ├── infra/           # P5 模型客户端 + 日志回调
    ├── agent/           # P1 诊断智能体（LangGraph 图 + 5 类节点）
    ├── retrieval/       # P2 案例检索（后续阶段）
    ├── services/        # 业务服务（project_service 等）
    └── db/              # P10 数据层（4 张表）

    frontend/
    ├── app/             # 页面（首页/对话/方案/项目列表）
    ├── components/      # 组件（后续阶段）
    └── lib/api.ts       # 后端 API 封装

## 项目状态

### M0 (tag: m0-base)

- [x] Day1 项目骨架 + FastAPI/Next.js 启动
- [x] Day2 模型客户端（DeepSeek 流式 + bge 本地 Embedding）
- [x] Day3 数据层（SQLite + SQLAlchemy，4 张表 + CRUD）
- [x] Day4 回调日志（每次调用耗时 + token）
- [x] Day5 前后端联调 + README + git tag

### M1-P1 诊断智能体

- [x] Week2 D1 需求理解节点（口语化需求 → ProjectRequirements JSON）
- [x] Week2 D2 条件路由 + 追问节点（信息不足自动追问）
- [x] Week2 D3 interrupt 多轮对话 + checkpointer + 5 轮强制结束
- [x] Week2 D4 方案生成节点（业务模块/技术选型/分期/风险，预算区间）
- [x] Week2 D5 端到端测试（想法 → 追问 → 方案）

### M2 诊断 API (tag: m2-api)

- [x] Week3 D1 budget 预算测算节点（规则引擎，区间 + 明细）
- [x] Week3 D2 feasibility 可行性评估 + output 汇总持久化
- [x] Week3 D3 用户确认循环（confirm/revise/reject）+ 完整图编译
- [x] Week3 D4 P6 API（SSE /api/chat + 方案详情 + 确认接口）
- [x] Week3 D5 真实联调（uvicorn + httpx 流式）+ docs/api.md + git tag

### M3-P2 案例检索

- [x] Week4 D1 Chroma 集成（vector_store 增删查 + bge Embedding）
- [x] Week4 D2 文档加载切分（PDF/docx/md → 递归切分 → 入库）
- [x] Week4 D3 案例管理 API（POST /api/cases/upload，SQLite + Chroma 双写）
- [x] Week4 D4 检索接入诊断图（retrieve 节点 → 案例摘要进 Prompt → 方案引用）
- [x] Week4 D5 冷启动数据（20 个标准案例入库，Top5 检索相关性验收，tag `m3-rag`）
- [x] Week5 D1 前端首页 + 历史项目列表页（开始新诊断入口，创建项目后跳对话页）
- [x] Week5 D2 聊天页（SSE 流式气泡、打字指示器、追问快捷填充、方案确认/修改栏）
- [x] Week5 D3 方案展示页（业务/技术方案、预算明细表、可行性评估、确认/修改）+ 确认状态落库修复
- [x] Week5 D4 确认循环前端跑通（确认后「我们会尽快联系您」收尾 + 修改回对话继续）
- [x] Week5 D5 UI 打磨：移动响应式适配（viewport/dvh/safe-area/16px 输入/44px 触控/表格滚动）+ 错误处理（重试/删除二次确认），tag `m4-frontend`
- [x] Week5 D5+ 等待体验：SSE 阶段事件（正在理解需求 → 检索案例 → 生成方案…）+ 等待计时，手机端不再像卡死
