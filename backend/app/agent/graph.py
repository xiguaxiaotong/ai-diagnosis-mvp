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
"""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.agent.nodes.ask import ask_node, wait_input_node
from app.agent.nodes.budget import budget_node
from app.agent.nodes.check import ROUTE_ASK, ROUTE_DONE, ROUTE_FORCE, check_completeness
from app.agent.nodes.force import force_finish_node
from app.agent.nodes.generate import generate_node
from app.agent.nodes.understand import understand_node
from app.agent.state import DiagnosisState


def build_graph():
    """构建诊断图：追问循环（interrupt 等待输入）+ 5 轮强制结束 + 方案生成。"""
    g = StateGraph(DiagnosisState)
    g.add_node("understand", understand_node)
    g.add_node("ask", ask_node)
    g.add_node("wait_input", wait_input_node)
    g.add_node("force_finish", force_finish_node)
    g.add_node("generate", generate_node)
    g.add_node("budget", budget_node)

    g.add_edge(START, "understand")
    g.add_conditional_edges(
        "understand",
        check_completeness,
        {ROUTE_ASK: "ask", ROUTE_DONE: "generate", ROUTE_FORCE: "force_finish"},
    )
    g.add_edge("ask", "wait_input")
    # 用户回答后回到 understand 重新理解 → 追问循环
    g.add_edge("wait_input", "understand")
    g.add_edge("force_finish", "generate")
    g.add_edge("generate", "budget")
    g.add_edge("budget", END)

    # MemorySaver：进程内 checkpoint，interrupt 恢复必需。
    # 生产环境换 PostgresSaver/RedisSaver，接口不变。
    return g.compile(checkpointer=MemorySaver())


# 模块级单例：应用内复用（图编译有开销；thread_id 隔离各会话状态）
diagnosis_graph = build_graph()
