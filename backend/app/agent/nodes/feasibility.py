"""可行性评估节点：需求 + 方案 + 预算 → FeasibilityReport JSON。

与 understand/generate 同款容错：json_object 强制 JSON → 失败退化普通调用 →
_extract_json 剥围栏 → Pydantic 校验。
"""

import json
import logging

from app.agent.prompt_loader import render
from app.agent.schemas import FeasibilityReport
from app.agent.nodes.understand import extract_json
from app.agent.state import DiagnosisState
from app.infra.model_client import chat_client

logger = logging.getLogger(__name__)


def feasibility_node(state: DiagnosisState) -> dict:
    """基于 requirements/plan/budget 出可行性评估，返回 {"feasibility": ...}。"""
    requirements, plan, budget = state.get("requirements"), state.get("plan"), state.get("budget")
    if not plan:
        return {"error": "可行性评估失败：缺少方案信息"}

    prompt = render(
        "feasibility",
        requirements_json=json.dumps(requirements or {}, ensure_ascii=False, indent=2),
        plan_json=json.dumps(plan, ensure_ascii=False, indent=2),
        # 免费思路版无预算：显式告知评估节点，避免编造金额
        budget_json=(
            json.dumps(budget, ensure_ascii=False, indent=2)
            if budget else "无（免费思路版方案，不涉及开发报价，预算合理性一笔带过即可）"
        ),
    )

    # 评估是判断型任务：低温度保证结论稳定
    try:
        answer = chat_client.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
    except Exception:
        logger.warning("response_format=json_object 调用失败，退化为普通调用")
        answer = chat_client.chat([{"role": "user", "content": prompt}], temperature=0.2)

    try:
        report = FeasibilityReport.model_validate(json.loads(extract_json(answer)))
    except (json.JSONDecodeError, ValueError) as e:
        logger.error("可行性评估输出解析失败: %s\n原始输出: %s", e, answer[:500])
        return {"error": f"可行性评估 JSON 解析失败: {e}"}

    logger.info("[feasibility] overall=%s risk=%s suggestions=%d",
                report.overall, report.risk_level, len(report.suggestions))
    return {"feasibility": report.model_dump()}
