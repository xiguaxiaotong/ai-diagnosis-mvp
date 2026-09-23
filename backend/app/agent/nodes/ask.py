"""追问节点 + 等待输入节点：发问与等待分离。

拆成两个节点的原因：interrupt() 打断时节点内的状态更新不会落盘，
把「追加追问消息」放在 ask 节点先提交，interrupt 放在独立的
wait_input 节点——图暂停时 messages[-1] 就是追问内容，
API 层直接读状态即可展示给用户。

用户回答后调用方用 Command(resume=回答) 恢复图。
"""

from langgraph.types import interrupt

from app.agent.state import DiagnosisState


def ask_node(state: DiagnosisState) -> dict:
    """生成追问消息并追加到 messages（确定性拼接，不调 LLM）。"""
    questions = state.get("clarify_questions", [])
    if not questions:
        return {}

    lines = []
    # 约束回顾（P8）：每轮开头简短复述已锁定的预算档，用户随时知道方案往哪走
    tier = state.get("budget_tier")
    if tier:
        lines.append(f"📍 {tier['recap']}")
        lines.append("")
    lines.append("为了给您出准确的方案和报价，我需要先确认几个问题：")
    for i, q in enumerate(questions, 1):
        lines.append(f"{i}. {q}")
    content = "\n".join(lines)

    messages = list(state.get("messages", []))
    messages.append({"role": "assistant", "content": content})
    return {"messages": messages}


def wait_input_node(state: DiagnosisState) -> dict:
    """interrupt 暂停等待用户输入；恢复后把回答写入 messages。"""
    user_reply = interrupt({"questions": state.get("clarify_questions", [])})
    messages = list(state.get("messages", []))
    messages.append({"role": "user", "content": str(user_reply)})
    return {"messages": messages}
