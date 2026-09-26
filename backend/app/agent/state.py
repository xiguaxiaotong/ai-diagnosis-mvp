"""诊断智能体状态：pydantic 子状态分层（W9 Day1）。

DiagnosisState 曾是 20+ 字段的大字典，任何节点都能读写任何字段——这是
拆三个子图（需求理解 / 方案生成 / 交互确认）前必须先收的地基。本文件做
两件事：

1. 用 pydantic 模型把字段划分成三个子状态（字段归属 = 施工图）；
2. 提供 validate_update()：节点输出增量在写回 state 前过校验，
   失败只记 trace + 日志不 raise（先观察一周再收紧）——挂在
   trace.py 的 traced() 包装器里，12 个节点函数零改动。

兼容约束（最重要）：DiagnosisState 本体仍是 TypedDict（langgraph +
state.get("xxx") 的 dict 访问全部继续工作）。pydantic 模型是「校验镜像」，
不是替代品——真正切换到 pydantic 状态是拆子图那天的事。

==================== 施工图：字段归属 / 读写节点 ====================

【顶层容器】（跨子状态共享，不属于任何子图）
  project_id      写：service 入口                    读：output(_persist)
  raw_idea        写：service 入口                    读：understand
  messages        写：ask/wait_input/revise/finalize/
                       reject/confirm(wait_confirmation)
                                                   读：understand/consult/route_intent
  error           写：_error 兜底（generate/feasibility/
                       budget/output）             读：output/check

【RequirementState 需求子状态】→ 拆图后「需求理解子图」的输出
  requirements          写：understand             读：generate/budget/output(汇总)
  budget_tier           写：understand(classify_budget)
                                                   读：generate/budget/output
  confirmed_pain_points 写：understand(用户勾选累加) 读：generate/output

【PlanState 方案子状态】→ 拆图后「方案生成子图」的输出
  retrieved_cases 写：retrieve                      读：generate
  plan           写：generate                       读：budget/output
  budget         写：budget（free 档写 None）        读：output
  feasibility    写：feasibility                    读：output
  full_solution  写：output                          读：wait_confirmation(consult_router)
  final_output   写：output                          读：wait_confirmation/consult/前端 SSE

【InteractionState 交互子状态】→ 拆图后「交互/确认子图」的状态
  needs_clarify     写：understand/_error           读：check
  clarify_questions 写：understand/_error            读：ask/meta
  clarify_round     写：understand                   读：check/understand
  clarify_exhausted 写：force_finish                 读：check
  question_details  写：understand                   读：meta 下发前端
  pain_points       写：understand                   读：meta 下发前端
  decision          写：wait_confirmation/consult    读：review_router
  revision_round    写：revise                       读：review_router
  revision_feedback 写：wait_confirmation            读：revise/generate
  finalized         写：finalize                     读：confirm 话术
  intent            写：route_intent                 读：图条件边

====================================================================
"""

from collections.abc import Mapping
from typing import Any, TypedDict

from pydantic import BaseModel, ValidationError

from app.agent.schemas import (
    BudgetEstimate,
    FeasibilityReport,
    ProjectRequirements,
    SolutionPlan,
)


class BudgetTierInfo(BaseModel):
    """预算档位（budget_tier.py classify_budget 的产出，understand 写入）。

    tier: free/demo/mid/pro；amount 是解析出的预算上限（元），无数字为 None。
    """

    tier: str
    label: str
    mentioned: str | None = None
    amount: int | None = None
    guidance: str = ""
    recap: str = ""


class RequirementState(BaseModel):
    """需求子状态：类型/预算/周期/功能/联系方式等已答字段。

    requirements 即 ProjectRequirements 的落盘形态（model_dump），
    含 project_title/business_type/core_features/target_users/
    mentioned_budget/mentioned_deadline/missing_info/pain_points/summary。
    """

    requirements: ProjectRequirements | None = None
    budget_tier: BudgetTierInfo | None = None
    confirmed_pain_points: list[str] = []


class PlanState(BaseModel):
    """方案子状态：方案生成链（retrieve→generate→budget→feasibility→output）产出。

    budget 为 None 是合法状态（free 档不报价）；full_solution 是多份
    子状态 + 时间戳的汇总快照，结构随前端方案页演进，先宽松 dict
    （观察一周后再收紧）；feasibility 评估失败不阻塞汇总，可为 None。
    """

    retrieved_cases: list[dict[str, Any]] = []
    plan: SolutionPlan | None = None
    budget: BudgetEstimate | None = None
    feasibility: FeasibilityReport | None = None
    full_solution: dict[str, Any] | None = None
    final_output: str = ""


class InteractionState(BaseModel):
    """交互子状态：追问/意图/确认的轮次与状态机。

    decision 取值：confirmed / revised / rejected / consult / pending；
    intent 取值：consult / requirement。两者先不设 Literal（刻意留宽，
    校验只观察不拦截；收紧前先确认线上没有边界值）。
    """

    needs_clarify: bool = False
    clarify_questions: list[str] = []
    clarify_round: int = 0
    clarify_exhausted: bool = False
    question_details: list[dict[str, Any]] = []
    pain_points: list[str] = []
    decision: str | None = None
    revision_round: int = 0
    revision_feedback: str | None = None
    finalized: bool = False
    intent: str | None = None


class TopLevelState(BaseModel):
    """顶层容器字段（不属于任何子状态）。

    校验对象是「节点增量」而非全量 state——写入方只带自己改的键，
    所以所有字段都要有默认值（缺席不报错，在场才验类型）。
    """

    project_id: int | None = None
    raw_idea: str = ""
    messages: list[dict[str, Any]] = []
    error: str | None = None


# 子状态注册表：校验按「更新里的键 → 归属模型」分组进行
_SUBSTATES: dict[str, type[BaseModel]] = {
    "requirement": RequirementState,
    "plan": PlanState,
    "interaction": InteractionState,
    "top": TopLevelState,
}


def validate_update(update: Mapping[str, Any]) -> list[str]:
    """节点输出增量写回 state 前的 pydantic 校验（W9 Day1）。

    - 只校验各子状态模型已声明的键（未声明的键放行——观察期不加新门）；
    - 同一子状态的键合并成一次 model_validate（嵌套模型连带重验：
      requirements→ProjectRequirements、plan→SolutionPlan 等，
      复用 schemas.py 的字段定义，不另写一套）；
    - 返回错误描述列表（空 = 通过）。刻意不 raise：失败记 trace +
      日志先观察一周，再决定是否收紧。

    挂载点：trace.py traced() 包装器（所有图节点都过这里，
    12 个节点函数零改动）。
    """
    errors: list[str] = []
    for name, model in _SUBSTATES.items():
        fields = model.model_fields
        payload = {k: v for k, v in update.items() if k in fields}
        if not payload:
            continue
        try:
            model.model_validate(payload)
        except ValidationError as e:
            msgs = "; ".join(
                f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}"
                for err in e.errors()
            )
            errors.append(f"[{name}] {msgs}"[:200])
    return errors


class DiagnosisState(TypedDict, total=False):
    """一次诊断会话的完整状态（langgraph 兼容的顶层容器）。

    total=False：所有键可选，节点按需读取/写入；字段按三个子状态分组
    （分组即施工图，详见表头注释）。字段名/类型与旧版完全一致——
    12 个节点的 state.get("xxx") 读写零改动。
    """

    # ---------- 顶层容器（跨子状态共享） ----------
    project_id: int              # 关联的数据库项目 id
    raw_idea: str                # 用户原始业务想法（可能口语化、不完整）
    messages: list[dict[str, Any]]  # 对话历史 [{"role": ..., "content": ...}]
    error: str | None              # 任一节点出错时写入

    # ---------- RequirementState：需求子状态（understand 写） ----------
    requirements: dict[str, Any]   # ProjectRequirements 解析结果（结构化 JSON）
    budget_tier: dict[str, Any]    # {tier, label, mentioned, amount, guidance, recap}
    confirmed_pain_points: list[str]  # 用户勾选确认过的痛点（generate 注入，全程引用）

    # ---------- PlanState：方案子状态（retrieve/generate/budget/feasibility/output 写） ----------
    retrieved_cases: list[dict[str, Any]]  # 相关案例 [{title, summary, score}]
    plan: dict[str, Any]           # 技术方案（SolutionPlan）
    budget: dict[str, Any] | None  # 预算测算（区间）；免费思路版为 None（不报价）
    feasibility: dict[str, Any]    # 可行性评估
    full_solution: dict[str, Any]  # 完整方案对象（requirements+plan+budget+feasibility）
    final_output: str              # 面向用户的最终输出文本

    # ---------- InteractionState：交互子状态 ----------
    needs_clarify: bool            # 信息是否不足，需要追问
    clarify_questions: list[str]   # 追问问题列表
    clarify_round: int             # 当前追问轮次（understand 每执行一次 +1）
    clarify_exhausted: bool        # 达到最大追问轮数，强制结束追问循环
    question_details: list[dict[str, Any]]
    # [{question, examples[]}]，understand 每轮刷新，随 meta 下发给前端渲染点选 chip
    pain_points: list[str]         # LLM 每轮识别的痛点候选（前端渲染勾选卡）
    decision: str                  # 用户决定：confirmed / revised / rejected / consult / pending
    revision_round: int            # 已修改轮次（上限 MAX_REVISION_ROUNDS）
    revision_feedback: str         # 用户最新一轮的修改要求（revise 时传给 generate）
    finalized: bool                # 满轮强制收尾标记（与用户主动确认区分，缺失会导致误发「已确认」话术）
    intent: str                    # 最近一条用户消息意图：consult（咨询） / requirement（需求）
