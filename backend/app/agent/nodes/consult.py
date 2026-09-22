"""意图分流 + 咨询回复节点：先判断用户是「咨询」还是「给需求/改方案」。

背景（用户反馈）：方案出来后用户问「具体是怎么组成报价的」，旧逻辑按关键词
把它当成修改意见 → 重新生成方案，答非所问；更严重的是 LLM 可能把内部报价
构成（成本单价、利润空间）直接说出去——这是商业机密。

设计：
- is_consult：确定性规则分类（快、稳、零 token）。需求/修改/确认信号优先，
  疑问与闲聊其次，长文本兜底视为需求。
- consult_node：LLM 以售前顾问身份回答咨询。机密保护规则写死在 prompt
  （报价构成明细/成本/利润率绝不透露，引导人工审核环节）。
  不推进任何状态：clarify_round、requirements、decision、revision_round 都不动。
  方案已出的场景覆盖 final_output，让 confirm_wait 分支把咨询回复展示给用户。
"""

import logging

from app.agent.prompt_loader import render
from app.agent.state import DiagnosisState
from app.infra.model_client import chat_client

logger = logging.getLogger(__name__)

# ---------- 意图分类（确定性规则） ----------

# 需求 / 修改 / 确认信号：命中即不是咨询（优先级最高）
_REQUIREMENT_MARKERS = (
    "我要", "我想", "想做", "做一个", "做个", "开发", "加一个", "加个", "加上",
    "去掉", "删掉", "换成", "改成", "预算", "工期", "人用", "规模",
    "万元", "块钱", "我的回答", "确认", "没问题", "同意", "不要了", "算了",
    "便宜", "砍价", "分期", "修改", "调整", "补充", "打折", "优惠",
)

# 疑问信号：出现即倾向咨询
_QUESTION_MARKERS = (
    "？", "?", "怎么", "为什么", "如何", "什么", "哪些", "多少", "多久",
    "吗", "能否", "能不能", "是不是", "你们", "介绍一下", "请问",
)

# 纯寒暄（短且无实质内容）
_GREETINGS = ("你好", "您好", "hi", "hello", "在吗", "谢谢", "辛苦了", "嗯", "哦")


def is_consult(text: str) -> bool:
    """用户消息 → 是否咨询/闲聊（而非提供需求、修改或确认方案）。

    顺序：需求信号 → 非咨询；疑问/寒暄 → 咨询；超过 15 字的实质内容
    兜底视为需求（宁可进需求流程，不可漏接用户真正想说的东西）。
    """
    t = text.strip().lower()
    if not t:
        return False
    if any(k in t for k in _REQUIREMENT_MARKERS):
        return False
    if any(k in t for k in _QUESTION_MARKERS):
        return True
    if len(t) <= 6 and any(g in t for g in _GREETINGS):
        return True
    return len(t) <= 15 and any(g in t for g in _GREETINGS)


def route_intent_node(state: DiagnosisState) -> dict:
    """意图分流节点：最近一条用户消息是咨询还是需求（纯规则，零 LLM 成本）。

    咨询 → consult 节点（售前回复，不推进诊断）；
    需求/修改/确认 → understand（原诊断流程）。
    """
    last_user = next(
        (m.get("content", "") for m in reversed(state.get("messages", []))
         if m.get("role") == "user"),
        "",
    )
    intent = "consult" if is_consult(last_user) else "requirement"
    logger.info("[route_intent] consult=%s text=%s", intent == "consult", last_user[:40])
    return {"intent": intent}


ROUTE_REQUIREMENT = "requirement"  # 路由目标：进入需求理解流程


def consult_router(state: DiagnosisState) -> str:
    """consult 节点后的去向：方案已出 → 回确认环节；否则回追问等待输入。"""
    return "wait_confirmation" if state.get("full_solution") else "wait_input"


def consult_node(state: DiagnosisState) -> dict:
    """咨询回复节点：售前口吻回答，不推进诊断状态。"""
    user_question = state.get("messages", [])[-1].get("content", "")
    history = state.get("messages", [])

    history_text = "\n".join(
        f"{'用户' if m['role'] == 'user' else '顾问'}: {m['content']}"
        for m in history[-6:]
    ) or "（无）"

    # 已收集的需求概要（帮 AI 回答时心里有数，不直接复述给用户）
    req = state.get("requirements") or {}
    req_summary = req.get("project_title", "（尚未收集）")

    # 方案已生成 → 咨询后仍停在确认环节
    has_plan = bool(state.get("full_solution"))
    plan_note = (
        "当前已生成过方案，处于等确认环节。回答完咨询后提醒一句：方案仍可确认或提出修改。"
        if has_plan
        else "当前处于需求诊断阶段。回答完咨询后自然引导用户继续补充需求信息。"
    )

    prompt = render(
        "consult",
        history=history_text,
        project_title=req_summary,
        user_question=user_question,
        plan_note=plan_note,
    )
    answer = chat_client.chat([{"role": "user", "content": prompt}], temperature=0.4)

    # 机密兜底：万一 LLM 仍然输出了敏感内容，直接替换成标准话术
    if _leaks_secrets(answer):
        logger.warning("[consult] 疑似泄露机密内容，已替换为标准话术")
        answer = (
            "您问的报价构成细节涉及公司内部核算，属于商业机密，我不便直接提供明细。"
            "我们的报价是根据您的需求由系统自动测算的，透明合理。"
            "如果您需要详细了解，可以留下联系方式，我们会有专人（人工审核）为您对接解释。"
        )

    messages = list(state.get("messages", []))
    messages.append({"role": "assistant", "content": answer})
    logger.info("[consult] 已回复咨询（不推进状态）：%s", user_question[:40])

    update: dict = {"messages": messages}
    if has_plan:
        # 方案确认环节：覆盖 final_output，让 confirm_wait 分支展示咨询回复
        update["final_output"] = answer
    return update


# 命中即视为泄露（输出侧硬校验，双保险）
_SECRET_MARKERS = ("成本价", "利润率", "毛利", "我们的成本", "内部核算价", "单价是")


def _leaks_secrets(text: str) -> bool:
    return any(k in text for k in _SECRET_MARKERS)
