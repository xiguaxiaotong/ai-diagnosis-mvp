"""方案确认循环：等确认 / 意图分类 / 修改 / 满轮收尾 / 拒绝。

对应用户画像「AI 方案偏差 → 人工确认」策略：
方案生成后必须经用户确认才交付；用户可确认 / 修改（最多 3 轮）/ 拒绝。

wait_confirmation 与 wait_input 同款拆分原则：interrupt 返回后才能拿到
用户回复，所以意图分类、消息追加都放在 interrupt 之后的同一个节点里，
结果一次性落盘。
"""

import logging

from langgraph.types import interrupt

from app.agent.state import DiagnosisState

logger = logging.getLogger(__name__)

# 路由目标
ROUTE_CONFIRMED = "confirmed"  # 用户确认 → 结束
ROUTE_REVISED = "revised"      # 用户要改 → 回 generate 重出方案
ROUTE_MAXED = "maxed"          # 修改轮数用尽 → 按当前方案收尾
ROUTE_REJECTED = "rejected"    # 用户拒绝 → 礼貌收尾

# 修改轮数上限（商业计划书：修改最多 3 轮）
MAX_REVISION_ROUNDS = 3

# 意图分类关键词（确定性规则，不调 LLM：快、稳、零成本）
_REJECT_KEYWORDS = ("不要了", "算了", "不做", "不用了", "拒绝", "取消吧", "重新再来")
_CONFIRM_KEYWORDS = ("确认", "没问题", "可以了", "就这样", "就这个", "同意", "通过", "ok", "行，")


def classify_decision(text: str) -> str:
    """用户回复 → 意图：confirmed / revised / rejected。

    拒绝优先级最高（避免「不要会员模块了」误判为确认）；
    其次确认；其余一律视为修改意见。
    """
    t = text.strip().lower()
    if any(k in t for k in _REJECT_KEYWORDS):
        return "rejected"
    if any(k in t for k in _CONFIRM_KEYWORDS):
        return "confirmed"
    return "revised"


def wait_confirmation_node(state: DiagnosisState) -> dict:
    """interrupt 暂停等待用户对方案的决定；恢复后分类意图并落盘。"""
    user_reply = str(interrupt({"final_output": state.get("final_output", "")}))
    messages = list(state.get("messages", []))
    messages.append({"role": "user", "content": user_reply})

    decision = classify_decision(user_reply)
    logger.info("[wait_confirmation] decision=%s round=%s",
                decision, state.get("revision_round", 0))
    return {
        "messages": messages,
        "decision": decision,
        # 修改意见要透传给 generate 重新出方案
        "revision_feedback": user_reply if decision == "revised" else "",
    }


def review_router(state: DiagnosisState) -> str:
    """条件边：确认结束 / 修改（未满轮）→ revise / 满轮 → finalize / 拒绝 → reject。"""
    decision = state.get("decision")
    if decision == "confirmed":
        return ROUTE_CONFIRMED
    if decision == "rejected":
        return ROUTE_REJECTED
    if state.get("revision_round", 0) >= MAX_REVISION_ROUNDS:
        return ROUTE_MAXED
    return ROUTE_REVISED


def revise_node(state: DiagnosisState) -> dict:
    """修改节点：告知用户开始调整，轮次 +1；方案由后续 generate 重出。"""
    round_no = state.get("revision_round", 0) + 1
    content = (
        f"收到，我按您的要求调整方案（第 {round_no}/{MAX_REVISION_ROUNDS} 次修改），"
        "方案、预算和可行性评估会一并更新，稍等。"
    )
    messages = list(state.get("messages", []))
    messages.append({"role": "assistant", "content": content})
    logger.info("[revise] round=%s feedback=%s", round_no, state.get("revision_feedback", "")[:50])
    return {"messages": messages, "revision_round": round_no}


def finalize_node(state: DiagnosisState) -> dict:
    """修改轮数用尽：按当前方案收尾，告知可线下继续沟通。"""
    content = (
        f"已经按您的意见修改了 {MAX_REVISION_ROUNDS} 轮，"
        "为了不再来回折腾，当前版本作为最终方案交付。"
        "如果还有想调整的地方，我们可以线下沟通后统一修改。"
    )
    messages = list(state.get("messages", []))
    messages.append({"role": "assistant", "content": content})
    # finalized 标记：与「直接确认」区分（chat_turn 据此决定是否补确认话术）
    return {"messages": messages, "decision": "confirmed", "finalized": True}


def reject_node(state: DiagnosisState) -> dict:
    """拒绝节点：礼貌收尾，不删数据（方案留在项目里供回看）。"""
    content = (
        "好的，方案先保留在项目里，您随时可以回来看。"
        "如果后续想法有变化，欢迎随时回来重新诊断，我可以基于这次的记录更快出方案。"
    )
    messages = list(state.get("messages", []))
    messages.append({"role": "assistant", "content": content})
    return {"messages": messages}
