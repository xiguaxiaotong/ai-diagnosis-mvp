"""P1 案例检索器：需求 → 相似历史案例摘要（喂给方案生成 Prompt）。

检索链路：Chroma 向量检索（chunk 级）→ 按 doc_id 聚合（一个案例取最高分
chunk）→ 联 SQLite cases 表取标题 → 返回 [{title, industry, summary, score}]。
检索失败/空库一律返回 []，绝不阻断诊断主流程。
"""

import logging
from typing import Any

from app.db.database import SessionLocal
from app.db.models import Case
from app.retrieval.vector_store import get_vector_store

logger = logging.getLogger(__name__)

# 相似度阈值：cosine score 低于此值视为不相关（bge-small 中文经验值）
MIN_SCORE = 0.35


def retrieve_cases(query: str, top_k: int = 3,
                   min_score: float = MIN_SCORE) -> list[dict[str, Any]]:
    """按语义检索相似案例，返回去重后的案例级结果（按最高分排序）。"""
    if not query or not query.strip():
        return []
    try:
        hits = get_vector_store().search(query.strip(), top_k=top_k * 4)
    except Exception:
        logger.exception("案例检索失败（降级为空结果）")
        return []

    # 按 doc_id 聚合：同一案例的多个 chunk 只保留最高分那个
    best: dict[str, dict[str, Any]] = {}
    for h in hits:
        if h["score"] < min_score:
            continue
        doc_id = h["metadata"].get("doc_id")
        if not doc_id:
            continue
        if doc_id not in best or h["score"] > best[doc_id]["score"]:
            best[doc_id] = h

    if not best:
        return []

    # 联 SQLite 取案例标题（vector_id 存的是 doc_id 前缀 case-{id}）
    # W7 Day7：只取已上架（published）案例——下架案例检索不召回，但向量保留可重新上架
    results: list[dict[str, Any]] = []
    db = SessionLocal()
    try:
        cases = (
            db.query(Case)
            .filter(Case.vector_id.in_(list(best)))
            .filter(Case.published == True)  # noqa: E712
            .all()
        )
        title_by_vector = {c.vector_id: c for c in cases}
        for doc_id, h in sorted(best.items(), key=lambda kv: -kv[1]["score"]):
            case = title_by_vector.get(doc_id)
            if case is None:
                # 下架了，或向量库里有孤儿 chunk（案例已删但向量残留）→ 跳过
                continue
            results.append({
                "title": case.title,
                "industry": (case.industry if case else None)
                            or h["metadata"].get("industry") or "",
                "summary": (case.summary if case else "") or h["text"][:120],
                "score": h["score"],
            })
    finally:
        db.close()

    logger.info("[retrieve] query=%r → %d 案例（top=%s）",
                query[:30], len(results),
                results[0]["title"] if results else "-")
    return results[:top_k]
