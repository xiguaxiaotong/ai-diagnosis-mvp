"""P2 案例服务：案例元数据（SQLite）+ 向量（Chroma）双向管理。

约定：Chroma 中一个案例的所有 chunk 共用 doc_id 前缀 "case-{db_id}"，
Case.vector_id 存这个前缀，删除/查询时按前缀定位。
"""

import logging
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Case
from app.retrieval.loader import ingest_file
from app.retrieval.vector_store import get_vector_store

logger = logging.getLogger(__name__)


def case_vector_prefix(case_id: int) -> str:
    return f"case-{case_id}"


def vectorize_case(db: Session, case: Case) -> bool:
    """统一向量化入口（P2 案例自动向量化）。

    按 case-{id} 前缀重嵌入：先 delete_by_doc 清旧 chunk（幂等——chunk 数
    变少时旧尾巴不残留），再 ingest_file，成功后回填 vector_id。
    失败不抛（入库不被向量计算阻断）：回滚 DB 改动，案例保留
    （vector_id=None → 检索联表时静默不召回），记 warning 日志，
    由 backfill_vectors（import_cases_csv.py --backfill）手动补跑兜底。

    返回 True=向量可用；False=失败（案例已存，检索暂不可见）。
    """
    prefix = case_vector_prefix(case.id)
    path = Path(case.file_path) if case.file_path else None
    if path is None or not path.exists():
        logger.warning("案例 %s(%s) 源文件缺失，跳过向量化: %s",
                       case.id, case.title, case.file_path)
        return False
    try:
        store = get_vector_store()
        store.delete_by_doc(prefix)  # 清旧 chunk（含首次入库的空操作）
        n_chunks = ingest_file(path, store, metadata={
            "industry": case.industry or "",
            "case_db_id": case.id,
        }, doc_id=prefix)
        case.vector_id = prefix
        db.commit()
        logger.info("案例 %s 向量化: %d chunks", prefix, n_chunks)
        return True
    except Exception:
        db.rollback()
        logger.warning("案例 %s(%s) 向量化失败：案例已保留、检索暂不可见，"
                       "跑 scripts/import_cases_csv.py --backfill 补齐",
                       case.id, case.title, exc_info=True)
        return False


def create_case_from_file(db: Session, file_path: str | Path, title: str,
                          industry: str | None = None) -> Case:
    """上传文件 → 元数据落库（SQLite）→ 向量化（统一入口，失败不阻断）。

    顺序：先建 DB 行拿 id，再 vectorize_case（以 case-{id} 为 doc_id 入向量库，
    成功回填 vector_id）。向量计算失败时案例照样入库（vector_id=None，
    检索静默不召回），记日志 + --backfill 兜底——入库成功与检索可用解耦。
    """
    from app.retrieval.loader import load_text

    p = Path(file_path)
    text = load_text(p)  # 解析失败（类型不支持/空文档）仍直接抛给 API 层
    case = Case(title=title, industry=industry, file_path=str(p),
                summary=(text or "")[:120])
    db.add(case)
    db.commit()
    db.refresh(case)

    vectorize_case(db, case)
    return case


def upsert_case_structured(db: Session, *, title: str, body: str,
                           file_path: str | Path,
                           industry: str | None = None,
                           scenario: str | None = None,
                           features: str | None = None,
                           tech_stack: str | None = None,
                           budget_min: int | None = None,
                           budget_max: int | None = None,
                           duration_weeks: str | None = None,
                           source_url: str | None = None,
                           source_type: str | None = None,
                           collected_at: date | None = None,
                           data_quality: str | None = None,
                           review_status: str = Case.REVIEW_PENDING,
                           ) -> tuple[Case, bool]:
    """W7 Day6：CSV 种子案例 upsert（幂等，可重复跑）。

    与 create_case_from_file 的区别：
    - 按 title 判重：已存在则更新（结构化字段 + 重新向量化），不重复插入
    - 带 W7 Day6 新增的结构化报价字段（scenario / budget_* / …）

    幂等语义（P2 案例自动向量化）：重复导入按 case-{id} 前缀覆盖向量
    （vectorize_case 先 delete_by_doc 再重嵌入），不产生重复 chunk。

    向量化走统一入口 vectorize_case：失败不阻断入库（P2 起改为字段先落库，
    案例/字段保留、vector_id 视成败回填），--backfill 兜底。
    """
    p = Path(file_path)
    case = db.query(Case).filter(Case.title == title).first()
    created = case is None
    if case is None:
        case = Case(title=title)
        db.add(case)
        db.commit()
        db.refresh(case)

    # 先落全部字段（入库不被向量计算阻断），再统一向量化
    case.industry = industry
    case.file_path = str(p)
    case.summary = body[:120]
    case.scenario = scenario
    case.features = features
    case.tech_stack = tech_stack
    case.budget_min = budget_min
    case.budget_max = budget_max
    case.duration_weeks = duration_weeks
    case.source_url = source_url
    case.source_type = source_type
    case.collected_at = collected_at
    case.data_quality = data_quality
    case.review_status = review_status
    db.commit()
    db.refresh(case)

    vectorize_case(db, case)
    return case, created


def backfill_vectors(db: Session) -> int:
    """W7 Day6：补齐向量库缺失的案例向量（幂等，可重复跑）。

    背景：本地 dev 库是 Chroma 时代种子导入的（向量存 chroma.sqlite3），
    切 numpy+JSON 持久化后只重导了服务器，本地旧 20 条 case.vector_id 指向
    numpy 库里不存在的 chunk → 检索永远召回不到。

    通用价值：向量文件损坏 / 误删后按 file_path 原文件重嵌入，DB 字段不动。
    判断标准：store 里查不到 {vector_id}#0 chunk 且源文件存在 → 重嵌入。
    """
    store = get_vector_store()
    restored = 0
    for case in db.query(Case).all():
        if not case.vector_id:
            case.vector_id = case_vector_prefix(case.id)
        if store.get(f"{case.vector_id}#0") is not None:
            continue  # 向量在，跳过
        path = Path(case.file_path) if case.file_path else None
        if not path or not path.exists():
            logger.warning("案例 %s 向量缺失且源文件不存在，跳过: %s",
                           case.id, case.file_path)
            continue
        store.delete_by_doc(case.vector_id)  # 清可能残留的半截 chunk
        ingest_file(path, store, metadata={
            "industry": case.industry or "",
            "case_db_id": case.id,
        }, doc_id=case.vector_id)
        db.commit()
        restored += 1
        logger.info("案例 %s 向量已重建: %s", case.vector_id, case.title)
    return restored


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


def case_to_dict(case: Case) -> dict[str, Any]:
    return {
        "id": case.id,
        "title": case.title,
        "industry": case.industry,
        "summary": case.summary,
        "file_path": case.file_path,
        "vector_id": case.vector_id,
        "created_at": case.created_at.isoformat() if case.created_at else None,
    }
