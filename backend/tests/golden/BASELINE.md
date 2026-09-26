# understand 黄金集评估基线（W8 Day5）

## 是什么

30 条种子案例库 CSV 真实需求（主库 `cases` 表 id 23–52，W7 Day6 导入的
报价数据行），按行内结构化字段渲染成口语化需求文本（3 种固定模板轮换，
见 `golden_cases.json` 的 `input`），逐条**真实跑** `understand_node`
（DeepSeek，非 stub；prompt → LLM 抽取 → JSON 校验 → 预算档位全链路），
对照 CSV 结构化真值算字段级命中率。

## 为什么这样做

- CSV 原始需求文本未随库保存（当时只导入结构化字段），输入文本是从
  行内真值渲染的——因此本基线衡量的是「**抽取管线**把结构化信息用
  口语说出来后能否无损抽回」，不衡量「乱糟糟真实口语的抽取能力」
  （那需要真实对话语料，待后续积累）。
- 检验目标是 **prompt 改动的回归防护**：改 understand prompt / schema /
  解析逻辑前后各跑一遍，命中率退化立即可见。

## 命中口径

| 字段 | 判定 |
|---|---|
| 类型 | business_type + project_title + core_features 合并文本包含场景关键词（智能客服→「客服」等） |
| 预算 | `parse_budget(mentioned_budget)` 落在 CSV `[budget_min, budget_max]` |
| 上线周期 | `mentioned_deadline` 解析出的周数落在 CSV `[weeks_lo, weeks_hi]` |
| 核心功能 | 真值功能命中（子串或相似度≥0.4）占比 ≥ 50% |
| 联系方式 | **未评估**：CSV 行内无联系方式真值，无从判定（有真实语料后再纳入） |

## 基线（2026-09-26 首跑，DeepSeek deepseek-chat，temperature 0.2）

| 字段 | 观察命中 | 退化门槛（baseline.json） | 说明 |
|---|---|---|---|
| 类型 | 30/30 | 29 | 抽取稳定，留 1 例噪声余量 |
| 预算 | 30/30 | 29 | 金额多为原文回显，稳定 |
| 上线周期 | 28/30 | 26 | LLM 偶有把「3-6周」归一成「2周内」的改写，留 2 例余量 |
| 核心功能 | 30/30 | 29 | 措辞重组容忍（相似度≥0.4） |

首跑的两例工期 miss：#26（3-6 周 → LLM 抽成「2周内上线」）、
#28（LLM 抽成「4周内」，不在真值区间）——属 LLM 归一化改写，非解析错误。

## 用法

```bash
# backend/ 下（约 1-2 分钟，30 次真实调用 ≈ ¥0.1）
python -m pytest tests/golden -q

# 快速回归（跳过黄金集与 bge 慢测试）
python -m pytest -m "not llm and not slow"
```

低于门槛 → 测试失败并提示复核。**改进 prompt 使命中率上升后**：
更新 `baseline.json` 门槛与本文件的观察值，commit 里注明跑分对比。

## 已知局限

- 输入由真值渲染（见上），非真实客户原文
- 30 条样本全部来自「智能客服 / 知识库 / 文档问答」三个场景族，
  行业覆盖窄（CSV 第一批数据所限），后续批次导入后应扩充
