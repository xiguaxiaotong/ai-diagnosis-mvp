# AI 诊断 MVP

描述业务需求 → AI 智能体诊断 → 生成方案 / 预算区间 / 可行性评估。

AIAgent 赋能服务平台（商业计划书见「初创团队文档」）M0 阶段产物。

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

## 各阶段验收脚本

M0 基础设施：

    cd backend
    python scripts/test_day2.py embed   # Embedding 转向量（无需 key）
    python scripts/test_day2.py chat    # DeepSeek 流式对话（需 key）
    python scripts/test_day3.py         # 数据层 CRUD
    python scripts/test_day4.py         # 调用日志（耗时 + token）

M1-P1 诊断智能体（均需 key）：

    python scripts/test_w2d1.py   # 需求理解：一句话→结构化 JSON
    python scripts/test_w2d2.py   # 追问闭环：模糊需求→追问→回答→补全
    python scripts/test_w2d3.py   # interrupt 多轮对话 + 5 轮强制结束
    python scripts/test_w2d4.py   # 方案生成：业务/技术方案 JSON 校验
    python scripts/test_w2d5.py   # 端到端：想法→追问→方案

M2 诊断 API（均需 key，接口文档见 docs/api.md）：

    python scripts/test_w3d1.py   # 预算测算节点（规则引擎，离线）
    python scripts/test_w3d2.py   # 可行性评估 + 汇总持久化
    python scripts/test_w3d3.py   # 用户确认循环 + 完整图编译
    python scripts/test_w3d4.py   # P6 API（TestClient 走 FastAPI 全栈）
    python scripts/test_w3d5.py   # 真实联调：uvicorn 子进程 + httpx 流式 SSE

M3-P2 案例检索（离线，无需 key）：

    python scripts/test_w4d1.py   # Chroma 增删查 + bge 向量
    python scripts/test_w4d2.py   # 文档加载切分（PDF/docx/md）→ 入库
    python scripts/test_w4d3.py   # 案例 API：上传 → SQLite+Chroma 双写 → 检索 → 删除
    python scripts/test_w4d4.py   # 检索接入诊断图（方案引用真实案例，需 key）
    python scripts/seed_cases.py  # 冷启动：录入 20 个标准案例（幂等）
    python scripts/test_w4d5.py   # 案例库 Top5 检索相关性 + 方案引用（需 key）
    python scripts/test_w5d1.py   # 首页创建新项目 + 历史列表（需前后端已启动）

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

### 下一步：M3 前端

- [ ] 前端对话页接入 SSE（fetch 流式渲染打字机效果）
- [ ] 确认循环 UI（确认/修改/拒绝）+ 方案详情卡片
