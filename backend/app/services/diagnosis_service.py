"""诊断会话服务：桥接 LangGraph 图与 HTTP API。

核心职责：
- 判断当前会话该「新起图」还是「resume 恢复」（读 graph 状态的 next 节点）
- 跑完一轮对话后，把结果归一化成 API 友好的 phase：
    clarify       需求追问中（图停在 wait_input）
    confirm_wait  方案已出，等用户确认（图停在 wait_confirmation）
    done          诊断结束（确认/拒绝/满轮收尾）
- thread_id 用 Project.thread_id（uuid）隔离，防止 rowid 复用串会话
"""

import logging

from uuid import uuid4

from langgraph.types import Command

from app.agent.graph import diagnosis_graph
from app.agent.nodes.confirm import MAX_REVISION_ROUNDS

logger = logging.getLogger(__name__)


def _config(project_id: int) -> dict:
    """图会话线程配置。

    thread_id 必须用项目级唯一 id（Project.thread_id uuid），不能用自增主键：
    SQLite rowid 删除后会被复用，新项目可能拿到已删项目的 id，
    继承 MemorySaver 里残留的图状态（曾导致修改轮次虚高、满轮误判为已确认）。
    旧数据无 thread_id 时懒初始化补写。
    """
    from app.db.database import SessionLocal
    from app.db.models import Project

    db = SessionLocal()
    try:
        project = db.get(Project, project_id)
        if project is not None:
            if not project.thread_id:
                project.thread_id = uuid4().hex
                db.commit()
            thread_key = f"project-{project.thread_id}"
        else:
            thread_key = f"project-{project_id}"
    finally:
        db.close()
    return {"configurable": {"thread_id": thread_key}}


def _last_assistant_message(state: dict) -> str:
    for msg in reversed(state.get("messages", [])):
        if msg.get("role") == "assistant":
            return msg["content"]
    return ""


def _result_from_state(project_id: int, state: dict, next_nodes: set) -> dict:
    """把图执行后的状态归一化成 API 结果（chat_turn / chat_turn_stream 共用）。"""
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
        # 用户确认方案 → 项目状态推进（方案页据此展示「已确认」锁定态）
        if state.get("decision") == "confirmed":
            if not state.get("finalized"):
                # 直接确认：final_output 上轮已展示过，本轮换确认收尾话术
                result["reply"] = (
                    "好的，方案已确认 ✓ 我们会尽快联系您，对接后续交付安排。"
                    "完整方案与预算明细可在方案页随时查看。"
                )
            _mark_confirmed(project_id)
    result["revision_round"] = state.get("revision_round", 0)
    if result["revision_round"] and result["phase"] == "confirm_wait":
        result["reply"] += (
            f"\n\n（已按您的要求修改，第 {result['revision_round']}/{MAX_REVISION_ROUNDS} 轮）"
        )
    logger.info("[chat_turn] project=%s phase=%s reply=%d 字",
                project_id, result["phase"], len(result["reply"]))
    return result


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
    return _result_from_state(project_id, state, next_nodes)


# 图节点 → 用户可读的阶段提示（等待体验：让用户知道后端真的在做事）
NODE_STAGE_LABELS = {
    "understand": "正在理解你的需求…",
    "consult": "正在回答你的咨询…",
    "ask": "正在整理追问…",
    "force_finish": "信息收集完成，开始准备方案…",
    "retrieve": "正在检索相似案例…",
    "generate": "正在生成方案（最耗时的一步）…",
    "budget": "正在测算预算…",
    "feasibility": "正在评估可行性…",
    "output": "正在汇总方案…",
    "revise": "正在按你的意见调整方案…",
    "finalize": "正在生成交付版本…",
    "reject": "正在收尾…",
}


def chat_turn_stream(project_id: int, message: str):
    """chat_turn 的生成器版：执行图的过程中逐节点 yield 阶段事件，最后 yield 结果。

    yield ("stage", (节点名, 用户可读提示))   —— 图每执行到一个关键节点
    yield ("result", 归一化结果 dict)          —— 图执行完毕（与 chat_turn 返回一致）
    """
    cfg = _config(project_id)
    snap = diagnosis_graph.get_state(cfg)
    next_nodes = set(snap.next or ())
    values = snap.values or {}

    # 会话已结束 → 不进图，直接返回结果
    if not next_nodes and values.get("decision") in ("confirmed", "rejected"):
        yield "stage", ("done", "本次诊断已完成")
        yield "result", {
            "phase": "done",
            "reply": _last_assistant_message(values) or "本次诊断已完成。",
            "questions": [],
            "solution": values.get("full_solution"),
            "revision_round": values.get("revision_round", 0),
        }
        return

    if "wait_input" in next_nodes or "wait_confirmation" in next_nodes:
        payload: object = Command(resume=message)
    else:
        payload = {
            "project_id": project_id,
            "raw_idea": message,
            "messages": [{"role": "user", "content": message}],
        }

    # stream_mode="updates"：每步产出 {节点名: 更新}，借它发阶段事件
    for chunk in diagnosis_graph.stream(payload, cfg, stream_mode="updates"):
        for node in chunk:
            label = NODE_STAGE_LABELS.get(node)
            if label:
                yield "stage", (node, label)

    snap = diagnosis_graph.get_state(cfg)
    yield "result", _result_from_state(project_id, snap.values or {}, set(snap.next or ()))


def _mark_confirmed(project_id: int) -> None:
    """确认收尾后把项目状态推进到 confirmed（失败只告警，不阻塞回复）。"""
    from app.db.database import SessionLocal
    from app.db.models import Project
    from app.services import project_service as _project_service

    db = SessionLocal()
    try:
        _project_service.update_project(db, project_id, status=Project.STATUS_CONFIRMED)
        logger.info("[chat_turn] project=%s status → confirmed", project_id)
    except Exception:
        db.rollback()
        logger.exception("[chat_turn] project=%s 状态推进 confirmed 失败", project_id)
    finally:
        db.close()
