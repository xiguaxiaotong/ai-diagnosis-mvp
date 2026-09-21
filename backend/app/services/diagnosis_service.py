"""诊断会话服务：桥接 LangGraph 图与 HTTP API。

核心职责：
- 判断当前会话该「新起图」还是「resume 恢复」（读 graph 状态的 next 节点）
- 跑完一轮对话后，把结果归一化成 API 友好的 phase：
    clarify       需求追问中（图停在 wait_input）
    confirm_wait  方案已出，等用户确认（图停在 wait_confirmation）
    done          诊断结束（确认/拒绝/满轮收尾）
- thread_id 与 project_id 一一对应：project-{id}
"""

import logging

from langgraph.types import Command

from app.agent.graph import diagnosis_graph
from app.agent.nodes.confirm import MAX_REVISION_ROUNDS

logger = logging.getLogger(__name__)


def _config(project_id: int) -> dict:
    return {"configurable": {"thread_id": f"project-{project_id}"}}


def _last_assistant_message(state: dict) -> str:
    for msg in reversed(state.get("messages", [])):
        if msg.get("role") == "assistant":
            return msg["content"]
    return ""


def chat_turn(project_id: int, message: str) -> dict:
    """处理一条用户消息：自动判断新会话 / resume，返回归一化结果。

    返回结构：
        phase:      clarify / confirm_wait / done
        reply:      本轮要展示给用户的文本（SSE 流式推送的就是它）
        questions:  追问问题列表（仅 clarify）
        solution:   完整方案对象（confirm_wait 时已有初版）
        revision_round: 已修改轮次
    """
    cfg = _config(project_id)
    snap = diagnosis_graph.get_state(cfg)
    next_nodes = set(snap.next or ())
    values = snap.values or {}

    # 会话已结束（确认/拒绝/满轮收尾后）→ 不再进图
    if not next_nodes and values.get("decision") in ("confirmed", "rejected"):
        return {
            "phase": "done",
            "reply": _last_assistant_message(values) or "本次诊断已完成。",
            "questions": [],
            "solution": values.get("full_solution"),
            "revision_round": values.get("revision_round", 0),
        }

    if "wait_input" in next_nodes or "wait_confirmation" in next_nodes:
        # 图停在 interrupt：用户这条消息就是恢复输入
        state = diagnosis_graph.invoke(Command(resume=message), cfg)
    else:
        # 全新会话：消息即业务想法
        state = diagnosis_graph.invoke(
            {
                "project_id": project_id,
                "raw_idea": message,
                "messages": [{"role": "user", "content": message}],
            },
            cfg,
        )

    next_nodes = set(diagnosis_graph.get_state(cfg).next or ())
    if "wait_input" in next_nodes:
        result = {
            "phase": "clarify",
            "reply": _last_assistant_message(state),
            "questions": state.get("clarify_questions", []),
            "solution": None,
        }
    elif "wait_confirmation" in next_nodes:
        result = {
            "phase": "confirm_wait",
            "reply": state.get("final_output", ""),
            "questions": [],
            "solution": state.get("full_solution"),
        }
    else:
        result = {
            "phase": "done",
            "reply": _last_assistant_message(state),
            "questions": [],
            "solution": state.get("full_solution"),
        }
    result["revision_round"] = state.get("revision_round", 0)
    if result["revision_round"] and result["phase"] == "confirm_wait":
        result["reply"] += (
            f"\n\n（已按您的要求修改，第 {result['revision_round']}/{MAX_REVISION_ROUNDS} 轮）"
        )
    logger.info("[chat_turn] project=%s phase=%s reply=%d 字",
                project_id, result["phase"], len(result["reply"]))
    return result
