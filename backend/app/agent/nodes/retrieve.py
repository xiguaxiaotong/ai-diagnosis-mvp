"""案例检索节点：生成方案前查相似历史案例，写入 retrieved_cases。

位于 understand 路由之后、generate 之前（done / force / revise 三条路都过这里）。
fail-open：检索失败不阻断诊断，retrieved_cases 置空。
"""

import logging

from app.agent.state import DiagnosisState
from app.retrieval.retriever import retrieve_cases

logger = logging.getLogger(__name__)


def _build_query(state: DiagnosisState) -> str:
    """拼接检索 query：原始想法 + 项目名 + 核心功能（语义检索的锚点）。"""
    parts: list[str] = []
    if state.get("raw_idea"):
        parts.append(state["raw_idea"])
    req = state.get("requirements") or {}
    if req.get("project_title"):
        parts.append(req["project_title"])
    if req.get("business_type"):
        parts.append(req["business_type"])
    for f in (req.get("core_features") or [])[:5]:
        parts.append(f)
    return " ".join(parts).strip()


def retrieve_node(state: DiagnosisState) -> dict:
    """查相似案例 → {"retrieved_cases": [...]}。"""
    query = _build_query(state)
    try:
        cases = retrieve_cases(query)
    except Exception:
        logger.exception("retrieve 节点异常（降级为空结果）")
        cases = []
    return {"retrieved_cases": cases}
