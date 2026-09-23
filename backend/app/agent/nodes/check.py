"""条件路由：根据需求信息是否齐全决定下一步。

LangGraph 条件边函数：返回下一个节点的名称。
"""

from app.agent.state import DiagnosisState

# 路由目标
ROUTE_ASK = "ask"          # 信息不全 → 追问节点（interrupt 等待用户输入）
ROUTE_DONE = "done"        # 信息齐全 → 进入方案生成（后续阶段接 retrieve/generate）
ROUTE_FORCE = "force"      # 达到最大追问轮数 → 强制结束追问循环

# 最大追问轮数：understand 执行次数达到该值仍缺信息，则停止追问。
# 对应商业计划书「AI 方案偏差 → 人工确认」策略：宁可基于假设出初步方案，
# 也不无限追问消耗用户耐心。
MAX_CLARIFY_ROUNDS = 5


def check_completeness(state: DiagnosisState) -> str:
    """路由：缺信息 ask（needs_clarify 优先，避免错误状态把图推进到 retrieve/generate）/
    轮次用尽 force / 齐全 done。

    注意：needs_clarify 优先于 error。
    之前曾因 understand 解析失败时同时返回 needs_clarify+error，
    error 优先让图继续走到 retrieve/generate 二次失败，最终卡在
    wait_confirmation 显示空 reply 的体验灾难。
    """
    if state.get("needs_clarify"):
        if state.get("clarify_round", 0) >= MAX_CLARIFY_ROUNDS:
            return ROUTE_FORCE
        return ROUTE_ASK
    return ROUTE_DONE
