"""诊断智能体图（Week2 Day4：+ 方案生成节点）：

    START → understand → check ──ask──→ ask → wait_input（interrupt 等待用户输入）
                          │                              │ Command(resume=回答) 恢复
                          │                              └──→ understand（循环，重新理解）
                          ├──done──→ generate → END（信息齐全 → 生成方案）
                          └──force─→ force_finish → generate → END（5 轮强制 → 初步方案）

- ask 节点内 interrupt() 暂停图执行，等待用户输入（状态由 checkpointer 持久化）
- 调用方用 Command(resume=用户回答) 恢复图，回答写入 messages 后重新走 understand
- clarify_round 达到 MAX_CLARIFY_ROUNDS 仍缺信息 → force_finish 强制结束，
  仍会走 generate 出「初步方案」（与 Day3 话术承诺一致，缺失部分按假设处理）
- 需要传 thread_id：graph.invoke(input, {"configurable": {"thread_id": 会话id}})
- Week3 Day3：output 后接确认循环（确认 / 修改最多 3 轮 / 拒绝），见 nodes/confirm.py
"""

import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

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
from app.agent.nodes.consult import (
    consult_node,
    consult_router,
    route_intent_node,
)
from app.agent.nodes.feasibility import feasibility_node
from app.agent.nodes.force import force_finish_node
from app.agent.nodes.generate import generate_node
from app.agent.nodes.output import output_node
from app.agent.nodes.retrieve import retrieve_node
from app.agent.nodes.understand import understand_node
from app.agent.state import DiagnosisState
from app.agent.trace import traced


def build_consult_subgraph(g: StateGraph) -> None:
    """咨询子图（W9 Day2 第一步拆出）。

    节点：route_intent / consult

    字段归属（state.py 施工图）：
      读：messages / full_solution / final_output
      写：intent

    同构拆法：向父图注册自己的节点，节点名/拓扑与拆分前完全一致
    （存量 checkpoint 的 interrupt 挂在顶层节点名上，改名即作废）。
    本子图无自有边——route_intent / consult 的出边都是跨子图编排，
    由父图 build_graph() 接。
    """
    g.add_node("route_intent", traced("route_intent", route_intent_node))
    g.add_node("consult", traced("consult", consult_node))


def build_confirmation_subgraph(g: StateGraph) -> None:
    """方案确认子图（W9 Day2 第一步拆出）。

    节点：wait_confirmation / revise / finalize / reject

    字段归属（state.py 施工图）：
      读：final_output / full_solution / revision_round
      写：messages / decision / revision_round / revision_feedback / finalized

    自有边：finalize / reject → END（确认循环的两个终态收口）。
    wait_confirmation 的条件出边（确认/修改/满轮/拒绝/咨询分流）跨子图，
    由父图接。
    """
    g.add_node("wait_confirmation", traced("wait_confirmation", wait_confirmation_node))
    g.add_node("revise", traced("revise", revise_node))
    g.add_node("finalize", traced("finalize", finalize_node))
    g.add_node("reject", traced("reject", reject_node))
    g.add_edge("finalize", END)
    g.add_edge("reject", END)


def build_graph():
    """父图编排入口：三个子图构建函数 + 跨子图编排边 + checkpointer。

    W8 Day1：每个节点用 traced() 包装（trace 中间层），节点函数签名与
    图结构（节点/边/路由）完全不变——traced 只在执行前后记 trace。
    W9 Day2：图拆三个子图构建函数（同构拆法，详见各 builder 注释）。
    """
    g = StateGraph(DiagnosisState)
    build_consult_subgraph(g)
    build_confirmation_subgraph(g)

    # ---------- 诊断区（第二步拆出前的内联形态，节点+边原样） ----------
    g.add_node("understand", traced("understand", understand_node))
    g.add_node("ask", traced("ask", ask_node))
    g.add_node("wait_input", traced("wait_input", wait_input_node))
    g.add_node("force_finish", traced("force_finish", force_finish_node))
    g.add_node("retrieve", traced("retrieve", retrieve_node))
    g.add_node("generate", traced("generate", generate_node))
    g.add_node("budget", traced("budget", budget_node))
    g.add_node("feasibility", traced("feasibility", feasibility_node))
    g.add_node("output", traced("output", output_node))

    g.add_conditional_edges(
        "understand",
        check_completeness,
        {ROUTE_ASK: "ask", ROUTE_DONE: "retrieve", ROUTE_FORCE: "force_finish"},
    )
    g.add_edge("ask", "wait_input")
    g.add_edge("force_finish", "retrieve")
    g.add_edge("retrieve", "generate")
    g.add_edge("generate", "budget")
    g.add_edge("budget", "feasibility")
    g.add_edge("feasibility", "output")
    # ---------- 诊断区结束 ----------

    # ---------- 跨子图编排边（父图职责） ----------
    g.add_edge(START, "route_intent")
    g.add_conditional_edges(
        "route_intent",
        lambda s: "consult" if s.get("intent") == "consult" else "understand",
        {"consult": "consult", "understand": "understand"},
    )
    # 用户回答后先意图分流：咨询 → consult 回复后继续等输入；需求 → understand 重新理解
    g.add_edge("wait_input", "route_intent")
    # 方案确认循环：output → interrupt 等确认 → 确认/修改/拒绝/咨询/满轮
    g.add_edge("output", "wait_confirmation")
    g.add_conditional_edges(
        "wait_confirmation",
        review_router,
        {ROUTE_CONFIRMED: END, ROUTE_REVISED: "revise", ROUTE_MAXED: "finalize",
         ROUTE_REJECTED: "reject", ROUTE_CONSULT: "consult"},
    )
    # 咨询回复后：方案已出 → 回确认环节继续等；否则回追问等待输入
    g.add_conditional_edges(
        "consult",
        consult_router,
        {"wait_confirmation": "wait_confirmation", "wait_input": "wait_input"},
    )
    # 修改后重新检索案例 → 重跑 generate → budget → feasibility → output
    g.add_edge("revise", "retrieve")

    # SqliteSaver：checkpoint 落盘（默认 backend/data/checkpoints.sqlite，
    # 可用 env CHECKPOINTS_PATH 覆盖——测试隔离用），
    # 重启后 interrupt 会话 / requirements 实体记忆全部保留。
    # 旧 MemorySaver 是进程内存，重启即失忆（曾导致用户重新进入项目后 AI 从头追问）。
    # check_same_thread=False：图执行在后台线程（SSE 心跳改造）+ 主线程 get_state，
    # SqliteSaver 内部有锁保证串行写。
    from app.config import CHECKPOINTS_PATH
    conn = sqlite3.connect(str(CHECKPOINTS_PATH), check_same_thread=False)
    return g.compile(checkpointer=SqliteSaver(conn))


# 模块级单例：应用内复用（图编译有开销；thread_id 隔离各会话状态）
diagnosis_graph = build_graph()
