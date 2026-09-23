"""P1 诊断智能体：DiagnosisState 定义（LangGraph 状态）。

LangGraph 以「共享状态 + 节点返回增量更新」的方式工作：
每个节点接收 state，返回一个 dict，LangGraph 会把返回的键合并进 state。
"""

from typing import Any, TypedDict


class DiagnosisState(TypedDict, total=False):
    """一次诊断会话的完整状态。

    total=False：所有键可选，节点按需读取/写入。
    """

    # ---------- 输入 ----------
    project_id: int              # 关联的数据库项目 id
    raw_idea: str                # 用户原始业务想法（可能口语化、不完整）
    messages: list[dict]         # 对话历史 [{"role": ..., "content": ...}]

    # ---------- 需求理解（understand 节点写入） ----------
    requirements: dict[str, Any]   # ProjectRequirements 解析结果（结构化 JSON）
    needs_clarify: bool            # 信息是否不足，需要追问
    clarify_questions: list[str]   # 追问问题列表
    clarify_round: int             # 当前追问轮次（understand 每执行一次 +1）
    clarify_exhausted: bool        # 达到最大追问轮数，强制结束追问循环

    # ---------- 预算档位（understand 每轮刷新；全局约束，所有节点共享） ----------
    # demo ≤5千/成本敏感 · mid 5千~1万 · pro >1万；改口覆盖，checkpointer 持久
    budget_tier: dict[str, Any]    # {tier, label, mentioned, amount, guidance, recap}

    # ---------- A 组交互升级：问题示例 + 痛点 ----------
    question_details: list[dict[str, Any]]
    # [{question, examples[]}]，understand 每轮刷新，随 meta 下发给前端渲染点选 chip
    pain_points: list[str]         # LLM 每轮识别的痛点候选（前端渲染勾选卡）
    confirmed_pain_points: list[str]  # 用户勾选确认过的痛点（generate 注入，全程引用）

    # ---------- 案例检索（retrieve 节点写入，后续阶段） ----------
    retrieved_cases: list[dict[str, Any]]  # 相关案例 [{title, summary, score}]

    # ---------- 方案生成（generate/budget/feasibility 写入，后续阶段） ----------
    plan: dict[str, Any]           # 技术方案
    budget: dict[str, Any] | None  # 预算测算（区间）；免费思路版为 None（不报价）
    feasibility: dict[str, Any]    # 可行性评估
    full_solution: dict[str, Any]  # 完整方案对象（requirements+plan+budget+feasibility）
    final_output: str              # 面向用户的最终输出文本

    # ---------- 方案确认（wait_confirmation/revise 节点写入） ----------
    decision: str                  # 用户决定：confirmed / revised / rejected / consult / pending
    revision_round: int            # 已修改轮次（上限 MAX_REVISION_ROUNDS）
    revision_feedback: str         # 用户最新一轮的修改要求（revise 时传给 generate）
    finalized: bool                # 满轮强制收尾标记（与用户主动确认区分，缺失会导致误发「已确认」话术）

    # ---------- 意图分流（route_intent 节点写入） ----------
    intent: str                    # 最近一条用户消息意图：consult（咨询） / requirement（需求）

    # ---------- 运行控制 ----------
    error: str | None              # 任一节点出错时写入
