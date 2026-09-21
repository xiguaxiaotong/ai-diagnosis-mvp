"""方案生成节点：结构化需求 → 业务方案 + 技术方案（SolutionPlan JSON）。

验收标准（Week2 Day4）：需求完整后能生成方案 JSON。
与 understand 节点同款容错：json_object 强制 JSON → 失败退化普通调用 →
_extract_json 剥围栏 → Pydantic 校验。
"""

import json
import logging

from app.agent.prompt_loader import render
from app.agent.schemas import SolutionPlan
from app.agent.nodes.understand import extract_json
from app.agent.state import DiagnosisState
from app.infra.model_client import chat_client

logger = logging.getLogger(__name__)


def generate_node(state: DiagnosisState) -> dict:
    """基于 requirements 生成 SolutionPlan，返回状态增量 {"plan": ...}。"""
    requirements = state.get("requirements")
    if not requirements:
        return {"error": "方案生成失败：缺少需求信息"}

    # 用户确认循环中的修改要求（首轮生成时为空）
    feedback = (state.get("revision_feedback") or "").strip()
    feedback_section = f"\n## 用户修改要求（必须落实到方案中）\n\n{feedback}\n" if feedback else ""
    prompt = render(
        "generate",
        requirements_json=json.dumps(requirements, ensure_ascii=False, indent=2),
        revision_feedback=feedback_section,
    )

    # 方案生成用 0.3 温度：比抽取稍高留一点创造性，但保证结构稳定
    try:
        answer = chat_client.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            response_format={"type": "json_object"},
        )
    except Exception:
        logger.warning("response_format=json_object 调用失败，退化为普通调用")
        answer = chat_client.chat([{"role": "user", "content": prompt}], temperature=0.3)

    try:
        data = json.loads(extract_json(answer))
        plan = SolutionPlan.model_validate(data)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error("方案生成输出解析失败: %s\n原始输出: %s", e, answer[:500])
        return {"error": f"方案生成 JSON 解析失败: {e}"}

    logger.info(
        "[generate] project=%s modules=%d stack=%d phases=%d",
        plan.project_name, len(plan.core_business_modules),
        len(plan.tech_stack), len(plan.implementation_phases),
    )
    return {"plan": plan.model_dump()}
