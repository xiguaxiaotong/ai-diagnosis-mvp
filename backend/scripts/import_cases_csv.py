"""W7 Day6：CSV 种子案例导入（第一批 30 条报价数据，全部本地不上云）。

用法（在 backend/ 目录下运行）：
    python scripts/import_cases_csv.py --csv "C:\\path\\种子案例库.csv"           # 全量
    python scripts/import_cases_csv.py --csv "C:\\path\\种子案例库.csv" --limit 3  # 先导前 3 条跑通
    python scripts/import_cases_csv.py --csv "..." --limit 3 --verify            # 导完顺带检索验证

幂等：按 title 去重 upsert（已存在 → 更新字段 + 重新向量化，不重复插入）。
复用 case_service.upsert_case_structured：正文写 backend/data/cases/case_csv_{id}.md，
向量化走现有 bge-small + numpy/JSON 持久化，vector_id 回填 case-{db_id} 前缀。

CSV 列映射：
    title/industry/summary → 已有字段
    status → review_status（待核验/已核验口径）
    其余列 → W7 Day6 新增结构化字段
"""
import argparse
import csv
import sys
from datetime import date
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import CASES_DIR  # noqa: E402
from app.db.database import SessionLocal, init_db  # noqa: E402
from app.db.models import Case  # noqa: E402
from app.services import case_service  # noqa: E402


def _parse_int(v: str | None) -> int | None:
    v = (v or "").strip()
    if not v:
        return None
    return int(float(v))  # 容忍 "80000.0" 这类脏数据


def _parse_date(v: str | None) -> date | None:
    v = (v or "").strip()
    if not v:
        return None
    return date.fromisoformat(v)


def _compose_body(row: dict) -> str:
    """CSV 行 → 向量化正文（结构化字段拼成可检索的自然语言段落）。

    embedding 质量取决于这段文本：把场景/功能/预算/工期都写进去，
    检索时「想做客服预算几万」这类问题才能命中。
    """
    budget = ""
    if row.get("budget_min") or row.get("budget_max"):
        lo = row.get("budget_min") or ""
        hi = row.get("budget_max") or ""
        budget = f"{lo}-{hi} 元" if lo != hi else f"{lo} 元"
    parts = [
        f"# {row['title']}",
        f"场景：{row.get('scenario', '')}",
        f"行业：{row.get('industry', '')}",
        f"功能：{row.get('features', '')}",
        f"技术栈：{row.get('tech_stack', '')}",
        f"预算区间：{budget}",
        f"工期：{row.get('duration_weeks', '')} 周",
        f"备注：{row.get('summary', '')}",
    ]
    return "\n".join(p for p in parts if p and not p.endswith("："))


def import_csv(csv_path: str, limit: int | None = None) -> None:
    p = Path(csv_path)
    if not p.exists():
        print(f"❌ CSV 不存在: {p}")
        sys.exit(1)

    init_db()
    CASES_DIR.mkdir(parents=True, exist_ok=True)
    db = SessionLocal()
    created_n = updated_n = failed_n = 0
    try:
        with p.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        if limit:
            rows = rows[:limit]

        for row in rows:
            title = (row.get("title") or "").strip()
            if not title:
                continue
            # 正文落文件（与现有文档型案例同构，file_path 指向它）
            body = _compose_body(row)
            file_name = f"case_csv_{int(row.get('id') or 0):03d}.md"
            body_path = CASES_DIR / file_name
            body_path.write_text(body, encoding="utf-8")
            try:
                case, created = case_service.upsert_case_structured(
                    db,
                    title=title,
                    body=body,
                    file_path=body_path,
                    industry=(row.get("industry") or "").strip() or None,
                    scenario=(row.get("scenario") or "").strip() or None,
                    features=(row.get("features") or "").strip() or None,
                    tech_stack=(row.get("tech_stack") or "").strip() or None,
                    budget_min=_parse_int(row.get("budget_min")),
                    budget_max=_parse_int(row.get("budget_max")),
                    duration_weeks=(row.get("duration_weeks") or "").strip() or None,
                    source_url=(row.get("source_url") or "").strip() or None,
                    source_type=(row.get("source_type") or "").strip() or None,
                    collected_at=_parse_date(row.get("collected_at")),
                    data_quality=(row.get("data_quality") or "").strip() or None,
                    review_status=(row.get("status") or "pending").strip() or "pending",
                )
                print(f"[{'新建' if created else '更新'}] id={case.id} "
                      f"{title}（{case.scenario}，预算 {case.budget_min}-{case.budget_max}）")
                created_n += int(created)
                updated_n += int(not created)
            except Exception as e:
                failed_n += 1
                print(f"[失败] {title} → {e}")

        total = db.query(Case).count()
        no_vec = db.query(Case).filter(Case.vector_id.is_(None)).count()
        print(f"\n完成：新建 {created_n}，更新 {updated_n}，失败 {failed_n}")
        print(f"案例库共 {total} 条，vector_id 为空 {no_vec} 条")
    finally:
        db.close()


def verify(query: str) -> None:
    """真实诊断问题检索验证。"""
    from app.retrieval.retriever import retrieve_cases
    print(f"\n检索验证：{query!r}")
    hits = retrieve_cases(query, top_k=3)
    if not hits:
        print("  ⚠️ 无命中（score < 0.35 阈值）")
        return
    for h in hits:
        print(f"  {h['score']:.4f}  {h['title']}  [{h['industry']}]")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=None, help="CSV 文件路径（--backfill 单独用时可不填）")
    ap.add_argument("--limit", type=int, default=None, help="只导入前 N 条")
    ap.add_argument("--backfill", action="store_true",
                    help="补齐向量库缺失的旧案例向量（不动的 DB 字段，只重嵌入）")
    ap.add_argument("--verify", action="store_true", help="导入后跑检索验证")
    args = ap.parse_args()

    if args.backfill:
        init_db()
        db = SessionLocal()
        try:
            n = case_service.backfill_vectors(db)
            print(f"向量补齐完成：重建 {n} 条")
        finally:
            db.close()

    if args.csv:
        import_csv(args.csv, args.limit)
    if args.verify:
        verify("我想做个能自动回客户咨询的客服")
