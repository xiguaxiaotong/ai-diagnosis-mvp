"""W9 Day2：拆图后的 checkpoint 兼容回归（验收第 4/5 条）。

背景：图已拆成三个子图构建函数 + 父图编排（graph.py）。主库存量进行中
会话的 checkpoint 是拆分前旧组装写的——interrupt 挂在顶层节点名上
（wait_input / wait_confirmation）。

同构拆法保证节点名/拓扑/state schema 不变，本文件实证两件事：
1. 旧组装创建的 checkpoint（模拟存量会话）能被新父图接管续跑到终点；
2. 拆图后节点 trace 序列与拆前同构（逐节点名对照）。

对照（旧→新）：
- 旧：单一大 build_graph，无兼容性概念（只有一个图）
- 新：legacy 组装在本文件内原样复制（拆分前 git 版本），与新图
  共用同一 checkpoint 库（conftest 已指临时文件，不碰主库）
"""

import json
import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.agent.graph import diagnosis_graph
from app.agent.nodes.ask import ask_node, wait_input_node
from app.agent.nodes.budget import budget_node
from app.agent.nodes.check import ROUTE_ASK, ROUTE_DONE, ROUTE_FORCE, check_completeness
from app.agent.nodes.confirm import (
    ROUTE_CONFIRMED,
    ROUTE_CONSULT,
    ROUTE_MAXED,
    ROUTE_REJECTED,
    ROUTE_REVISED,
    finalize_node,
    reject_node,
    review_router,
    revise_node,
    wait_confirmation_node,
)
from app.agent.nodes.consult import consult_node, consult_router, route_intent_node
from app.agent.nodes.feasibility import feasibility_node
from app.agent.nodes.force import force_finish_node
from app.agent.nodes.generate import generate_node
from app.agent.nodes.output import output_node
from app.agent.nodes.retrieve import retrieve_node
from app.agent.nodes.understand import understand_node
from app.agent.state import DiagnosisState
from app.agent.trace import traced
from app.config import CHECKPOINTS_PATH

IDEA = "我想给奶茶店做扫码点单小程序"
ANSWER = "预算8万，两个月上线，堂食为主"


def _legacy_build_graph():
    """拆分前的 build_graph（单一大函数，W9 Day2 之前的 git 版本原样复制）。

    刻意不 import 新 graph.py 的 builder——「旧」侧必须完全独立于新组装。
    """
    g = StateGraph(DiagnosisState)
    g.add_node("understand", traced("understand", understand_node))
    g.add_node("ask", traced("ask", ask_node))
    g.add_node("wait_input", traced("wait_input", wait_input_node))
    g.add_node("force_finish", traced("force_finish", force_finish_node))
    g.add_node("retrieve", traced("retrieve", retrieve_node))
    g.add_node("generate", traced("generate", generate_node))
    g.add_node("budget", traced("budget", budget_node))
    g.add_node("feasibility", traced("feasibility", feasibility_node))
    g.add_node("output", traced("output", output_node))
    g.add_node("wait_confirmation", traced("wait_confirmation", wait_confirmation_node))
    g.add_node("revise", traced("revise", revise_node))
    g.add_node("finalize", traced("finalize", finalize_node))
    g.add_node("reject", traced("reject", reject_node))
    g.add_node("route_intent", traced("route_intent", route_intent_node))
    g.add_node("consult", traced("consult", consult_node))

    g.add_edge(START, "route_intent")
    g.add_conditional_edges(
        "route_intent",
        lambda s: "consult" if s.get("intent") == "consult" else "understand",
        {"consult": "consult", "understand": "understand"},
    )
    g.add_conditional_edges(
        "understand",
        check_completeness,
        {ROUTE_ASK: "ask", ROUTE_DONE: "retrieve", ROUTE_FORCE: "force_finish"},
    )
    g.add_edge("ask", "wait_input")
    g.add_edge("wait_input", "route_intent")
    g.add_edge("force_finish", "retrieve")
    g.add_edge("generate", "budget")
    g.add_edge("budget", "feasibility")
    g.add_edge("feasibility", "output")
    g.add_edge("output", "wait_confirmation")
    g.add_conditional_edges(
        "wait_confirmation",
        review_router,
        {ROUTE_CONFIRMED: END, ROUTE_REVISED: "revise", ROUTE_MAXED: "finalize",
         ROUTE_REJECTED: "reject", ROUTE_CONSULT: "consult"},
    )
    g.add_conditional_edges(
        "consult",
        consult_router,
        {"wait_confirmation": "wait_confirmation", "wait_input": "wait_input"},
    )
    g.add_edge("revise", "retrieve")
    g.add_edge("retrieve", "generate")
    g.add_edge("finalize", END)
    g.add_edge("reject", END)

    conn = sqlite3.connect(str(CHECKPOINTS_PATH), check_same_thread=False)
    return g.compile(checkpointer=SqliteSaver(conn))


def test_old_wait_input_checkpoint_resumes_on_new_graph(stub_llm, new_thread):
    """旧组装跑到 wait_input interrupt（存量追问中会话）→ 新父图接管续跑。"""
    legacy = _legacy_build_graph()
    stub_llm["understand"] = "missing_then_full"

    legacy.invoke(
        {"raw_idea": IDEA, "messages": [{"role": "user", "content": IDEA}]}, new_thread)
    snap = legacy.get_state(new_thread)
    assert "wait_input" in snap.next, f"旧组装应停在追问等待: {snap.next}"

    # 新父图（三个子图构建函数 + 编排）接管同一 thread 的 checkpoint
    state = diagnosis_graph.invoke(Command(resume=ANSWER), new_thread)
    snap2 = diagnosis_graph.get_state(new_thread)
    assert "wait_confirmation" in snap2.next, f"新图续跑应出方案: {snap2.next}"
    assert state["needs_clarify"] is False
    assert state.get("plan"), "续跑后应已生成方案"


def test_old_wait_confirmation_checkpoint_resumes_on_new_graph(stub_llm, new_thread):
    """旧组装跑到 wait_confirmation interrupt（存量待确认会话）→ 新父图确认收尾。"""
    legacy = _legacy_build_graph()
    stub_llm["understand"] = "full"

    legacy.invoke(
        {"raw_idea": IDEA, "messages": [{"role": "user", "content": IDEA}]}, new_thread)
    snap = legacy.get_state(new_thread)
    assert "wait_confirmation" in snap.next, f"旧组装应停在方案确认: {snap.next}"

    state = diagnosis_graph.invoke(Command(resume="确认，就这样"), new_thread)
    snap2 = diagnosis_graph.get_state(new_thread)
    assert not snap2.next, f"确认后应到 END: {snap2.next}"
    assert state["decision"] == "confirmed"
    assert state.get("final_output"), "最终方案文本应在"


def test_trace_node_sequence_unchanged_after_split(stub_llm, new_thread, monkeypatch, tmp_path):
    """验收第 5 条：拆图后 trace 节点序列与拆前同构（节点名逐个一致）。

    序列是拓扑决定的（同构拆法 → 拓扑不变 → 序列必然一致），这里固化
    断言防后续有人改组装时无意动了拓扑。
    """
    trace_file = tmp_path / "trace.jsonl"
    monkeypatch.setattr("app.agent.trace.TRACE_PATH", trace_file)

    stub_llm["understand"] = "full"
    diagnosis_graph.invoke(
        {"raw_idea": IDEA, "messages": [{"role": "user", "content": IDEA}]}, new_thread)

    lines = trace_file.read_text(encoding="utf-8").splitlines()
    records = [json.loads(ln) for ln in lines if ln]
    node_seq = [r["node"] for r in records if r.get("type") == "node"]
    # 拆图前（W8 验收 thread 97bb7702 模式）完整直答路径的节点序列：
    # route_intent → understand → retrieve → generate → budget →
    # feasibility → output → wait_confirmation（interrupt 停住）
    assert node_seq == [
        "route_intent", "understand", "retrieve", "generate",
        "budget", "feasibility", "output", "wait_confirmation",
    ], f"拆图后节点序列变化: {node_seq}"
    # 子状态校验镜像：完整跑一遍，state_errors 必须为空（验收第 3 条）
    assert all("state_errors" not in r for r in records), [
        r["state_errors"] for r in records if "state_errors" in r]
