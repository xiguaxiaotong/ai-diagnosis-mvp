"""P2 案例服务：案例元数据（SQLite）+ 向量（Chroma）双向管理。

约定：Chroma 中一个案例的所有 chunk 共用 doc_id 前缀 "case-{db_id}"，
Case.vector_id 存这个前缀，删除/查询时按前缀定位。
"""

import logging
from pathlib import Path
from sqlalchemy.orm import Session

from app.config import CASES_DIR
from app.db.models import Case
from app.retrieval.loader import ingest_file
from app.retrieval.vector_store import get_vector_store

logger = logging.getLogger(__name__)


def case_vector_prefix(case_id: int) -> str:
    return f"case-{case_id}"


def create_case_from_file(db: Session, file_path: str | Path, title: str,
                          industry: str | None = None) -> Case:
    """上传文件 → 切分入库（Chroma）→ 元数据落库（SQLite）。

    顺序：先建 DB 行拿 id，再以 case-{id} 为 doc_id 入向量库，最后回填 vector_id。
    """
    p = Path(file_path)
    case = Case(title=title, industry=industry, file_path=str(p))
    db.add(case)
    db.commit()
    db.refresh(case)

    prefix = case_vector_prefix(case.id)
    try:
        store = get_vector_store()
        from app.retrieval.loader import load_text
        text = load_text(p)
        n_chunks = ingest_file(p, store, metadata={
            "industry": industry or "",
            "case_db_id": case.id,
        }, doc_id=prefix)
        case.vector_id = prefix
        case.summary = (text or "")[:120]
        db.commit()
        logger.info("案例 %s 入库: %d chunks", prefix, n_chunks)
    except Exception:
        # 向量入库失败要回滚 DB 行，避免出现查不到向量的幽灵案例
        db.rollback()
        db.delete(case)
        db.commit()
        raise
    return case


def list_cases(db: Session, limit: int = 50) -> list[Case]:
    return db.query(Case).order_by(Case.id.desc()).limit(limit).all()


def get_case(db: Session, case_id: int) -> Case | None:
    return db.get(Case, case_id)


def delete_case(db: Session, case_id: int) -> bool:
    """删 SQLite 行 + Chroma 向量 + 原始文件，三处都清。"""
    case = db.get(Case, case_id)
    if case is None:
        return False
    if case.vector_id:
        get_vector_store().delete_by_doc(case.vector_id)
    file_path = case.file_path
    db.delete(case)
    db.commit()
    if file_path and Path(file_path).exists():
        Path(file_path).unlink(missing_ok=True)
    return True


def case_to_dict(case: Case) -> dict:
    return {
        "id": case.id,
        "title": case.title,
        "industry": case.industry,
        "summary": case.summary,
        "file_path": case.file_path,
        "vector_id": case.vector_id,
        "created_at": case.created_at.isoformat() if case.created_at else None,
    }
