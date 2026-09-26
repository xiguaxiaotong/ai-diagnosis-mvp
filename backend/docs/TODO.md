# TODO（存量问题记录，待人工拍板后处理）

---

## T-1 budget_constraint 场景4 断言失败 —— ✅ 已关闭（W9，trace 定位 + 修复 + 回归收编）

- **记录日期**：2026-09-26（W7 Day7 回归时发现）→ **关闭日期**：2026-09-26（W9）
- **结论**：两层问题——断言过期是表因，budget 节点 corpus 构建缺陷是真 bug（一并修复）。

### 定位过程（scripts/t1_budget_trace.py，真实 DeepSeek 全链路）

场景「预算3万做个进销存」真跑 + trace 回放，逐环节验证预算保真：

| 环节 | 结论 |
|---|---|
| understand 抽取 | ✓ 保真：两轮均 `mentioned_budget='3万'`（原话保留，无换算） |
| P8 预算锁定 | ✓ 保真：`tier='pro', amount=30000`，全程不改 |
| budget 节点 | ✗ **成本侧被虚增**：用户明确答「不用，独立用」，仍命中 3 类集成加价（+9k~18k） |

### 根因（budget.py estimate_budget 的 corpus 构建）

corpus = 模块描述 + `requirements.values()` **全量**拼接，四类脏数据被当成计价信号：

1. **question_details 的未选示例选项**——「对接收银机」是 LLM 生成的候选选项，
   用户没选，却被 `收银` 关键词命中；
2. **question_details / missing_info 的问题原文**——「需要和现有系统打通吗？」
   命中 `现有系统`/`对接`；
3. **summary 的否定句**——「不用对接收银机或财务软件，独立使用」，关键词引擎
   无否定语义，拒绝被当成需求；
4. **产品域词**——`project_title='进销存管理系统'` 命中 ERP 类的 `进销存` 关键词：
   用户要做的系统本身就是进销存，不是要对接现有进销存。

（信息齐全后 question_details 仍残留在 requirements 里——understand 的
missing_info 会清空，question_details 不清，所以 budget 执行时脏数据仍在。）

### 修复（backend/app/agent/nodes/budget.py）

- corpus 只扫语义字段白名单 `REQ_TEXT_FIELDS`（title/type/features/users/
  budget/deadline/pain_points），脚手架字段与 summary 不进 corpus；
  取舍：漏检（后续人工补报价）危害远小于虚增（直接把报价抬高吓跑用户）。
- `ERP/进销存对接` 关键词组删掉 `进销存`/`库存系统` 产品域词（保留 `erp`）；
  真实对接表述必含「对接」语义，由「现有系统对接」类兜住。
- 场景4 断言按当前正确行为重写（保现实成本 26000-40000 + 低于最低可行成本/
  协商缩减话术），xfail 移除；另补 4 条回归：脚手架/否定句/产品域字不虚增、
  真实对接照常计价。

### 验证

- 修复前：真跑 trace 显示「需要对接 3 类第三方系统」+ 3 条系统集成 line_items；
- 修复后：同场景真跑 line_items 无集成项、assumptions 干净、预算区间收敛
  逻辑不变（18000-30000「在预算内」），「3万」全程保真零变形；
- pytest 快速档全绿无 xfail，黄金集对比 BASELINE.md 零退化（见提交记录）。

---

## T-2 generate 节点 LLM 漏字段 → 整链 error 兜底 —— ✅ 已关闭（W9，T-1 定位时顺带发现，趁热修）

- **记录日期**：2026-09-26（W9，t1_budget_trace.py 第二次真跑时触发）→ **关闭日期**：2026-09-26（W9）
- **结论**：按字段性质分级处理（选项 3 变体：可选容错 + 必填点名重试一次），不一刀切全兜底。

### 复现（scripts/t2_generate_repro.py，stub LLM 零真钱）

三种坏输出各跑完整图，确认修复前行为：

| 模式 | 修复前 |
|---|---|
| optional（缺 one_liner/glossary/example） | pydantic 默认值静默补齐，主流程继续（无留痕） |
| required（模块漏 priority，即真实触发场景） | generate 无重试直接 error → budget/feasibility 连锁失败 → output 兜底话术，**整链无方案** |
| invalid（非 JSON） | 同上整链 error |

### 根因

- generate 节点解析失败（JSON 解析 / pydantic 校验）**无任何重试**，
  LLM 输出不确定性（temperature=0.3，同 prompt 一次过一次挂）下单次
  格式偏差直接把整条方案链打进 error 兜底；
- 错误粒度不分级的连带问题：可选字段（one_liner/glossary/example 有
  默认值）本可安全补齐继续。

### 修复（backend/app/agent/nodes/generate.py）

- `_plan_problems()`：LLM 原始输出 → (data, 问题清单)。必填缺失的
  ValidationError 逐条提取，序列下标归一
  （`core_business_modules.0.priority` → `core_business_modules[].priority`）
  去重，避免 5 个模块漏同一字段刷 5 条；
- **分级策略**：
  - 可选字段缺失 → pydantic 默认值补齐（本来就是安全默认），
    `logger.warning` 留痕，主流程继续；
  - 必填缺失 / 非法 JSON / 字段类型不合法 → **点名重试一次**：重试
    prompt 追加「上次输出的问题（本次必须修正）」清单，LLM 不用猜
    哪里错；仍失败才走 error 兜底，文案记明「重试后仍缺 X」。

### 回归（tests/test_generate_fallback.py，stub LLM 零真钱，6 用例）

- 可选缺失：不报错 + 默认值补齐 + warning 留痕 + 不触发重试；
- 必填缺失：恰好重试 1 次 + 重试 prompt 点名 `core_business_modules[].priority`；
- 必填两次都缺：error 兜底 + 文案含「重试后仍缺」与字段名 + 不无限重试；
- 非法 JSON：重试 1 次恢复 / 重试仍失败兜底；
- 合格输出不重试（正常路径保护）。

### 顺带修复（排障时发现的隐藏坑）

alembic `env.py` 的 `fileConfig(config.config_file_name)` 默认
`disable_existing_loggers=True`——pytest 收集阶段 import 的 app.* logger
全在 `init_db→alembic` 之前注册，被整体 disabled，**测试内所有 app 日志
（logger.warning / caplog）静默失效**，极难察觉。已改
`disable_existing_loggers=False`。

### 验证

- 复现脚本修复后对照：optional 一次过；required/invalid 恰好 2 次调用
  （重试生效），stub 恒坏时正确走 error 兜底；
- 快速档 pytest 98 passed（+6 回归）0 warnings 0 xfail；
- 黄金集 类型30/30 预算30/30 工期28/30 功能30/30 对比基线零退化；
- ruff 全绿；mypy 基线 146→145（generate.py 重写自带类型并清零该文件，
  基线明细见 docs/mypy_baseline.md）。
