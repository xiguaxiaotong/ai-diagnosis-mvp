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

    # ---------- 案例检索（retrieve 节点写入，后续阶段） ----------
    retrieved_cases: list[dict[str, Any]]  # 相关案例 [{title, summary, score}]

    # ---------- 方案生成（generate/budget/feasibility 写入，后续阶段） ----------
    plan: dict[str, Any]           # 技术方案
    budget: dict[str, Any]         # 预算测算（区间）
    feasibility: dict[str, Any]    # 可行性评估
    full_solution: dict[str, Any]  # 完整方案对象（requirements+plan+budget+feasibility）
    final_output: str              # 面向用户的最终输出文本

    # ---------- 方案确认（wait_confirmation/revise 节点写入） ----------
    decision: str                  # 用户决定：confirmed / revised / rejected / pending
    revision_round: int            # 已修改轮次（上限 MAX_REVISION_ROUNDS）
    revision_feedback: str         # 用户最新一轮的修改要求（revise 时传给 generate）

    # ---------- 运行控制 ----------
    error: str | None              # 任一节点出错时写入
