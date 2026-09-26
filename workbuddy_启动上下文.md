# WorkBuddy 启动上下文（每次开新会话直接把本文件内容发给它）

## 项目一句话
AI 需求诊断 + 定制撮合平台：中小企业用大白话描述想法 → AI 诊断智能体（大模型+案例RAG）梳理需求、出方案与预算 → 确认后留资对接（撮合/自营中后期）。

## 仓库与环境
- 代码仓库：`D:\ai-diagnosis-mvp`（自己读代码，不要让我贴代码）
- 后端：Python + FastAPI + LangGraph（诊断状态机）
- 前端：Next.js（客户端 + /admin 最小后台）
- 部署：docker-compose 三容器（backend + frontend + nginx），SSE 流式
- 数据库：SQLite；向量库用 numpy+JSON（**不用 Chroma**）；Embedding bge-small 512 维
- 工作方式：本地开发、不上云；改动本地 build 验证后再部署；每周末打可运行 tag

## 当前进度（截至 2026-09-26，W9 收尾）
- 里程碑 tag 全链：m0-base → m1-p1-core → m2-api → m3-rag → m4-frontend → m5-account ✅
- 已上线演示：http://134.175.137.41 （腾讯云，ICP 备案审核中）
- W7 已完成：账号系统/个人中心、项目列表工作台、留资闭环（leads）、最小运营后台、CSV 导出、日志脱敏、CSV 种子案例导入（30条）、案例库管理（上下架+检索预览）、对接工单（五档跟进状态）、数据看板（统计卡片+转化漏斗+趋势）
- W8 已完成（tag w8d1-trace / w8d23-traces / w8-observe）：可观测性三件套——trace 全链路诊断轨迹（jsonl）、state 增量校验（state_errors 留痕不 raise）、节点耗时统计；测试 85→93 条收编
- W9 已完成（tag w9-warmup-eng / w9d1-state / w9d2-split / w9d3-t1-closed / w9d4-t2-closed / w9d5-auto-vector）：
  - mypy 基线化（146→125，strict 白名单：trace/config/generate/case_service）+ ruff 全绿 + pytest warnings 清零
  - 黄金集基线（30 条 CSV 真值 × 真实 DeepSeek 抽取，BASELINE.md + baseline.json 门槛防退化）
  - 诊断图拆三子图（understand/diagnose/confirm 同构拆法，存量 checkpoint 兼容用例锁住）
  - T-1 关闭：budget 节点 corpus 白名单修复（交互脚手架/否定句/产品域词不再虚增集成加价）
  - T-2 关闭：generate 输出异常分级容错（可选补默认/必填点名重试一次）
  - P2 案例自动向量化：入库即检索可用（vectorize_case 统一入口），幂等按 case_id 覆盖，向量失败不阻断入库（--backfill 兜底），下架案例检索不召回已测试锁住
- 测试基线：快速档 103 passed / 0 warnings / 0 xfail；黄金集 预算30/30、工期28/30、功能30/30

## 下一步待办
1. 等 ICP 备案 → v2.0 收尾（配域名 + HTTPS，按《生产上线冒烟清单》冒烟）
2. bad case 回归库：等真实语料积累后建立（黄金集当前只覆盖抽取管线，非真实口语）
3. 之后：撮合/开发者端/支付（第12-13周可选，触发条件未到）

## 硬约束与注意事项
- 不做：撮合/开发者端/支付（第12-13周可选，触发条件未到）；短信验证码（用邮箱重置密码）
- 游客免登录模式必须保留（先体验后注册，注册自动过户项目）
- 文案面向非技术用户（个体户/小店老板），避免 RAG/向量库/token 等术语出现在界面
- 商业口径：撮合佣金 12%，方案报价为预估区间，不承诺确定收益；案例全部脱敏
- ⚠️ 不要把服务器密码等敏感信息写入任何文档或代码提交

## 相关文档位置（需要时让我去读）
- 桌面 `初创团队文档/`：项目落地3_第7周后规划、开发清单_账号收口与后台系统、项目架构、生产上线冒烟清单、商业计划书、前期推广
- WorkBuddy 项目网盘「aiagent赋能平台」文件夹：同套文档（云端版）
