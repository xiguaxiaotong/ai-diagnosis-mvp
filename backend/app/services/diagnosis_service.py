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
import queue
import threading
import time
from typing import Any
from uuid import uuid4

from langgraph.types import Command

from app.agent.graph import diagnosis_graph
from app.agent.nodes.confirm import MAX_REVISION_ROUNDS
from app.infra import stream_sink

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
    # P8 约束回顾：预算档位随每轮结果下发（前端顶部横幅）
    tier = state.get("budget_tier")
    constraints = (
        {"recap": tier.get("recap", ""), "label": tier.get("label", ""),
         "tier": tier.get("tier", ""), "mentioned": tier.get("mentioned", "")}
        if tier else None
    )
    if "wait_input" in next_nodes:
        result = {
            "phase": "clarify",
            "reply": _last_assistant_message(state),
            "questions": state.get("clarify_questions", []),
            # A 组：问题示例（前端点选 chip）+ 痛点候选（前端勾选卡）
            "question_details": state.get("question_details", []),
            "pain_points": state.get("pain_points", []),
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
    result["constraints"] = constraints
    # A 组：痛点确认后供前端恢复勾选状态（刷新页面/重进项目不丢）
    if state.get("confirmed_pain_points"):
        result["confirmed_pain_points"] = state["confirmed_pain_points"]
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
    _persist_req_profile(project_id, state)
    return _result_from_state(project_id, state, next_nodes)


# 图节点 → 用户可读的阶段提示（等待体验：让用户知道后端真的在做事）
NODE_STAGE_LABELS = {
    "understand": "提取项目信息，整理业务要点…",
    "consult": "正在回答你的咨询…",
    "ask": "整理需要向你确认的问题…",
    "force_finish": "信息收集完成，开始准备方案…",
    "retrieve": "正在参考类似案例…",
    "generate": "生成完整落地方案（最耗时的一步，请耐心）…",
    "budget": "评估开发成本与工期…",
    "feasibility": "评估可行性与风险…",
    "output": "汇总方案与报价…",
    "revise": "正在按你的意见调整方案…",
    "finalize": "正在生成交付版本…",
    "reject": "正在收尾…",
}


def chat_turn_stream(project_id: int, message: str):
    """chat_turn 的生成器版：边执行图边 yield 事件，最后 yield 结果。

    yield ("stage",  (节点名, 用户可读提示))   —— 图每执行到一个关键节点
    yield ("token",  文本片段)                  —— 节点内实时流出（真流式，豆包效果）
    yield ("reset",  None)                      —— 前端清空已流出内容（机密兜底替换）
    yield ("result", 归一化结果 dict)           —— 图执行完毕（与 chat_turn 返回一致；
                                                    reply 中已流出的前缀不再重复推，
                                                    剩余部分放在 result["tail"]）

    图执行放在子线程：节点内 stream_sink.emit() 的 token 进入队列，
    本生成器主循环实时 drain 并 yield，SSE 层就能逐 token 推送，
    而不是等整个节点/整图跑完才推（旧观感：长时间空白后整段蹦出）。
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

    q: queue.Queue = queue.Queue()

    def _run() -> None:
        stream_sink.set_sink(q)  # 节点内 emit 直接进本队列（与图同线程）
        try:
            # stream_mode="updates"：每步产出 {节点名: 更新}，借它发阶段事件
            for chunk in diagnosis_graph.stream(payload, cfg, stream_mode="updates"):
                for node in chunk:
                    label = NODE_STAGE_LABELS.get(node)
                    if label:
                        q.put(("stage", (node, label)))
            snap = diagnosis_graph.get_state(cfg)
            _persist_req_profile(project_id, snap.values or {})
            result = _result_from_state(
                project_id, snap.values or {}, set(snap.next or ()))
            q.put(("result", result))
        except BaseException as e:  # 线程内异常带回主 generator 统一抛出
            q.put(("error", e))
        finally:
            q.put(("end", None))

    threading.Thread(target=_run, daemon=True).start()

    emitted: list[str] = []  # 已流出的 token 累计（reset 时清零）
    while True:
        kind, evt = q.get()
        if kind == "end":
            break
        if kind == "error":
            raise evt  # type: ignore[misc]
        if kind == "token":
            emitted.append(evt)
            # LLM 真 token 都很短；整段文本（如 output 的方案摘要）一次性 emit 时
            # 会变成一个巨型 delta 瞬间到达，观感等同「憋完再蹦」。
            # 大块切小 + 固定节奏 yield，还原打字机效果（LLM token 不受影响）。
            if len(evt) > 40:
                for i in range(0, len(evt), 8):
                    yield "token", evt[i:i + 8]
                    time.sleep(0.03)
                continue
        elif kind == "reset":
            emitted.clear()
        elif kind == "result":
            # 队列 FIFO：result 之前的 token 必然已全部消费并累计，
            # 在此计算未流出的尾部，交给 API 层打字机补完（已流出前缀不重复推）
            reply = evt["reply"]
            already = "".join(emitted)
            evt["tail"] = (
                reply[len(already):] if already and reply.startswith(already) else reply
            )
        yield kind, evt


def _persist_req_profile(project_id: int, state: dict) -> None:
    """把交互快照写入 projects.req_profile（重进会话恢复选项卡的唯一数据源）。

    独立于图 checkpoint：checkpoint 服务于 interrupt 恢复，
    req_profile 供项目详情 API 读取——前端刷新/重进历史项目时，
    靠它恢复问题选项卡（question_details）、痛点卡、预算档位横幅。
    新格式（含 requirements 键）；失败只告警不阻塞回复。
    """
    req = state.get("requirements")
    if not req:
        return
    from app.db.database import SessionLocal
    from app.db.models import Project

    tier = state.get("budget_tier")
    snapshot = {
        "requirements": req,
        "clarify_questions": state.get("clarify_questions") or [],
        "question_details": state.get("question_details") or [],
        "pain_points": state.get("pain_points") or [],
        "confirmed_pain_points": state.get("confirmed_pain_points") or [],
        "budget_tier": (
            {"tier": tier.get("tier"), "label": tier.get("label"), "recap": tier.get("recap")}
            if tier else None
        ),
    }
    db = SessionLocal()
    try:
        project = db.get(Project, project_id)
        if project is not None:
            import json
            project.req_profile = json.dumps(snapshot, ensure_ascii=False)
            db.commit()
            logger.info("[req_profile] project=%s 已落库（问题 %d 组）",
                        project_id, len(snapshot["question_details"]))
    except Exception:
        db.rollback()
        logger.exception("[req_profile] project=%s 落库失败", project_id)
    finally:
        db.close()


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
