"""强制结束节点：追问轮数用尽，基于当前信息出初步方案。

对应用户画像痛点「没成本参考、不想被问烦」：
明确告知用户后续按行业常见做法做假设，可随时补充修正。
"""

from app.agent.state import DiagnosisState


def force_finish_node(state: DiagnosisState) -> dict:
    """追加说明消息并打上 clarify_exhausted 标记，结束追问循环。"""
    round_no = state.get("clarify_round", 0)
    content = (
        f"好的，为了不耽误您的时间，需求确认先到这里（已确认 {round_no} 轮）。"
        "接下来我会基于您提供的信息给出初步方案和预算区间，"
        "其中缺失的部分我会按行业常见做法做假设，您看到方案后随时可以补充修正。"
    )
    messages = list(state.get("messages", []))
    messages.append({"role": "assistant", "content": content})
    return {"messages": messages, "clarify_exhausted": True}
