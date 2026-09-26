"""节点错误处理工具。

集中处理 LLM JSON 解析失败时的回退策略，避免每个节点重复实现
「错误落 state → 让图流转到 retrieve/generate → 二次失败 → 卡在 wait_confirmation 空 reply」的连锁故障。

策略：
- understand_node / generate_node / feasibility_node 解析失败时：
  * 记录 error 到 state（供日志/排查）
  * understand 失败 → 走 needs_clarify + 澄清问题"我没太理解，请换个说法再说"，让图回到 wait_input
  * generate / feasibility 失败 → 不让图继续推进（缺 requirements/plan/budget 时节点自我短路），
    把错误直接暴露给 finalize 或上层，避免无意义重试
"""

import logging

from app.agent.state import DiagnosisState

logger = logging.getLogger(__name__)


def user_friendly_understand_error(reason: str) -> dict:
    """understand 节点 LLM 输出解析失败时的回退。

    不让图继续推进到 retrieve/generate（依赖合法 requirements），
    而是回到 wait_input 并友好提示用户换种说法再说一遍。
    注意：不写 state.error（check_completeness 见 error 会强走 ROUTE_DONE，
    反而继续进 retrieve/generate 死循环）。
    """
    logger.warning("[understand] 解析失败，触发重述引导：%s", reason)
    return {
        "needs_clarify": True,
        "clarify_questions": ["刚才没太理解您的需求，能换个说法再说一遍吗？例如想做什么、给谁用、预算和工期大概多少。"],
        "clarify_round": 0,  # 不消耗追问轮次；用户有重新描述的机会
    }


def fatal_node_error(stage: str, reason: str) -> dict:
    """generate / feasibility 失败时的兜底：只记 error，不让图继续死循环。

    调用方应保证对应节点前置依赖齐全；若仍失败，本节点返回 error，
    由 output_node / finalize 看到 requirements 缺失时统一暴露给上层。
    """
    logger.error("[%s] 解析失败（致命）：%s", stage, reason)
    return {"error": f"{stage} 失败: {reason}"}


def safe_call_llm_json(
    stage: str, prompt: str, temperature: float, max_retries: int = 2
) -> tuple[str | None, str | None]:
    """统一 LLM 调用入口：兼容 response_format=json_object 失败退化 + 重试。

    返回 (answer, error_reason)：成功 answer 非空；失败 answer=None, error_reason 为可读原因。
    """
    from app.infra.model_client import chat_client

    last_err = ""
    for attempt in range(max_retries + 1):
        try:
            try:
                return chat_client.chat(
                    [{"role": "user", "content": prompt}],
                    temperature=temperature,
                    response_format={"type": "json_object"},
                ), None
            except Exception as e:
                logger.warning("[%s] response_format=json_object 调用失败（%s），退化为普通调用", stage, e)
                return chat_client.chat([{"role": "user", "content": prompt}], temperature=temperature), None
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            logger.warning("[%s] 第 %d 次调用失败：%s", stage, attempt + 1, last_err)
    return None, last_err


def _ensure_state(state: DiagnosisState) -> DiagnosisState:
    """类型占位，实际不消费；保留方便后续扩展。"""
    return state
