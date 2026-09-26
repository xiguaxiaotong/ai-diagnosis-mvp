"""案例自动向量化（P2 清单项）—— 入库即检索可用。

背景：此前入库与向量化绑死（失败即回滚删行/500），且旧库迁移/向量文件
损坏后必须记得手动跑 --backfill 才有向量。本文件锁住新契约：
1. 入库即向量化：upload API / upsert_case_structured 均同步出向量，检索立刻可命中
2. 幂等：同案例重复导入按 case-{id} 覆盖（先 delete_by_doc 再重嵌入），
   无重复 chunk、无变短后的旧尾巴
3. 向量化失败不阻断入库：案例/字段保留、vector_id=None、检索静默跳过，
   backfill_vectors（--backfill）恢复
4. 上下架联动：下架案例不参与检索召回（retrieve_cases 的 published 过滤，
   W7 Day7 既有行为，此处锁住防回归）
"""

import io

import pytest

from app.db.database import SessionLocal
from app.db.models import Case
from app.retrieval.retriever import retrieve_cases
from app.retrieval.vector_store import get_vector_store
from app.services import case_service

BODY = ("# 社区团购接龙小程序案例\n"
        "某社区生鲜店用接龙小程序做预售。核心模块包括商品接龙、订单管理、"
        "微信支付、团长分佣、到店自提核销。技术栈是微信小程序加 Python 后端。\n" * 8)
QUERY = "我想给小区做个团购接龙小程序"


@pytest.fixture
def clean_store():
    store = get_vector_store()
    store.clear()
    yield store
    store.clear()


def _upload(client, title):
    return client.post(
        "/api/cases/upload",
        files={"file": ("case.md", io.BytesIO(BODY.encode("utf-8")), "text/markdown")},
        data={"title": title, "industry": "零售"},
    )


def _doc_items(store, case_id):
    return [it for it in store._items
            if (it.get("metadata") or {}).get("doc_id") == f"case-{case_id}"]


# ---------- 1. 入库即向量化 ----------

def test_upload_vectorized_immediately(client, admin_headers, clean_store):
    r = _upload(client, "自动向量化案例")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["vectorized"] is True
    assert body["vector_id"] == f"case-{body['id']}"
    # 向量库已有 chunk，检索立即可命中（无需 backfill）
    assert clean_store.get(f"{body['vector_id']}#0") is not None
    assert any(h["title"] == body["title"] for h in retrieve_cases(QUERY))


# ---------- 2. 幂等：重复导入按 case_id 覆盖 ----------

def test_reimport_idempotent_no_duplicate_vectors(tmp_path, clean_store):
    p = tmp_path / "case.md"
    p.write_text(BODY, encoding="utf-8")
    store = clean_store
    db = SessionLocal()
    cid = None
    try:
        case, created = case_service.upsert_case_structured(
            db, title="幂等导入案例", body=BODY, file_path=p, industry="零售")
        cid = case.id
        assert created and case.vector_id == f"case-{cid}"
        n_long = len(_doc_items(store, cid))
        assert n_long >= 2, "长正文应切多个 chunk"

        # 重复导入同标题 → 更新不新建，DB 一行、chunk 覆盖不重复
        p.write_text(BODY + "二期复盘：损耗下降三成。", encoding="utf-8")
        case2, created2 = case_service.upsert_case_structured(
            db, title="幂等导入案例", body=BODY, file_path=p, industry="零售")
        assert (not created2) and case2.id == cid
        assert db.query(Case).filter(Case.title == "幂等导入案例").count() == 1
        items = _doc_items(store, cid)
        ids = [it["id"] for it in items]
        assert len(ids) == len(set(ids)), "chunk id 不得重复"
        assert store.count() == len(items), "全库不得出现案例外的游离 chunk"

        # 正文改短 → 旧 chunk 尾巴不残留（delete_by_doc 先清）
        short = "# 幂等导入案例\n短复盘：接龙小程序上线两月。"
        p.write_text(short, encoding="utf-8")
        case_service.upsert_case_structured(
            db, title="幂等导入案例", body=short, file_path=p, industry="零售")
        items = _doc_items(store, cid)
        assert len(items) == 1 and items[0]["id"] == f"case-{cid}#0", \
            "变短后旧尾巴必须清掉"
    finally:
        if cid is not None:
            case_service.delete_case(db, cid)
        db.close()


# ---------- 3. 向量化失败不阻断入库 + backfill 兜底 ----------

def _boom(*args, **kwargs):
    raise RuntimeError("embedding 服务不可用")


def test_vectorize_failure_keeps_case_then_backfill(tmp_path, clean_store, monkeypatch):
    p = tmp_path / "case.md"
    p.write_text(BODY, encoding="utf-8")
    monkeypatch.setattr(case_service, "ingest_file", _boom)

    db = SessionLocal()
    cid = None
    try:
        case, created = case_service.upsert_case_structured(
            db, title="失败保留案例", body=BODY, file_path=p, industry="零售")
        cid = case.id
        assert created
        assert case.vector_id is None, "向量化失败不得回填 vector_id"

        # 案例行与字段均已落库（不再回滚删行）
        db2 = SessionLocal()
        try:
            row = db2.get(Case, cid)
            assert row is not None and row.industry == "零售" and row.summary
        finally:
            db2.close()

        # 检索侧：缺向量 = 静默不召回（store 已清空），不报错
        assert retrieve_cases(QUERY) == []

        # 兜底入口：向量服务恢复后 --backfill 补齐 → 检索可见
        monkeypatch.undo()
        restored = case_service.backfill_vectors(db)
        assert restored >= 1
        db.refresh(case)
        assert case.vector_id == f"case-{cid}"
        assert clean_store.get(f"case-{cid}#0") is not None
        assert any(h["title"] == "失败保留案例" for h in retrieve_cases(QUERY))
    finally:
        if cid is not None:
            case_service.delete_case(db, cid)
        db.close()


def test_upload_vector_failure_returns_201_with_flag(client, admin_headers,
                                                     clean_store, monkeypatch):
    """API 层同契约：向量失败照样 201 入库，响应标 vectorized=False。"""
    monkeypatch.setattr(case_service, "ingest_file", _boom)
    r = _upload(client, "向量失败入库案例")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["vectorized"] is False
    assert body["vector_id"] is None
    # DB 行在、源文件保留（backfill 依赖它重嵌入）
    db = SessionLocal()
    try:
        row = db.get(Case, body["id"])
        assert row is not None
        import pathlib
        assert pathlib.Path(row.file_path).exists()
    finally:
        db.close()


# ---------- 4. 上下架联动：下架不召回 ----------

def test_unpublished_case_excluded_from_retrieval(client, admin_headers, clean_store):
    r = _upload(client, "下架联动案例")
    assert r.status_code == 201 and r.json()["vectorized"] is True
    cid = r.json()["id"]
    assert any(h["title"] == "下架联动案例" for h in retrieve_cases(QUERY))

    # admin 下架 → 检索立即不召回（向量保留，重新上架零成本）
    r = client.patch(f"/api/admin/cases/{cid}", headers=admin_headers,
                     json={"published": False})
    assert r.status_code == 200, r.text
    assert not any(h["title"] == "下架联动案例" for h in retrieve_cases(QUERY))
    # 向量本体仍在库里
    assert clean_store.get(f"case-{cid}#0") is not None

    # 重新上架 → 恢复召回
    r = client.patch(f"/api/admin/cases/{cid}", headers=admin_headers,
                     json={"published": True})
    assert r.status_code == 200, r.text
    assert any(h["title"] == "下架联动案例" for h in retrieve_cases(QUERY))
