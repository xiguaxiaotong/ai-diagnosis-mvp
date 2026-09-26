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

## T-2 generate 节点 LLM 漏字段 → 整链 error 兜底（T-1 定位时顺带发现，未修）

- **记录日期**：2026-09-26（W9，t1_budget_trace.py 第二次真跑时触发）
- **状态**：未修（等拍板）

### 现象

generate 的 LLM 输出 `core_business_modules` 各模块**漏了 `priority` 字段**
（pydantic SolutionPlan 校验失败 ×5）→ plan 缺失 → budget/feasibility 连锁
error → output 只能给「方案生成遇到问题」兜底话术。当次真跑整链无方案。

```
方案生成输出解析失败: 5 validation errors for SolutionPlan
core_business_modules.0.priority  Field required [type=missing, ...]
```

### 判断

- LLM 输出不确定性问题（temperature=0.3，同 prompt 一次过一次挂），
  非本次预算改动引入（修复前后都可能触发）；
- generate 节点**没有**校验失败重试（`_error.safe_call_llm_json` 有
  max_retries=2 机制但 generate 未用），单次格式偏差直接判死。

### 处理选项（等拍板）

1. generate 校验失败时重试（复用 `safe_call_llm_json`，附「上次输出缺 priority」提示）；
2. 模块 `priority` 缺省容错（默认 P0/P1）——校验放宽，风险是定价口径被 LLM 摆布；
3. 两者都做（先容错解析、再重试兜底）。

### 影响

- 触发概率：低（多轮真跑偶发一次）；触发后该会话无方案，用户需重新发起；
- 不影响 budget 主链路（budget 只在 plan 校验通过后执行）。
