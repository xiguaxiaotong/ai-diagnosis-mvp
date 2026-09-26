"""检索链路 —— 收编自 test_w4d1(向量库) / test_w4d2(切分入库) /
test_w4d4(检索接入诊断)。

全部走真实 bge-small 本地 embedding（零 token，但首次加载模型约 10s，
标 slow）。PDF/docx 样例生成依赖平台字体（原脚本耦合 Windows 字体路径），
pytest 版只收 md 文件路径，pdf/docx 属 e2e 不收。
"""

import pytest

from app.retrieval.vector_store import get_vector_store

CASE_MD = """# 社区团购接龙小程序案例

某社区生鲜店用接龙小程序做预售。核心模块包括商品接龙、订单管理、
微信支付、团长分佣、到店自提核销。技术栈是微信小程序加 Python 后端，
数据库 MySQL。上线两个月日均接龙五十单，损耗下降三成。
"""


@pytest.fixture
def clean_store():
    """每个检索测试用干净向量库（session 共享 CHROMA_DIR，测试间互清）。"""
    store = get_vector_store()
    store.clear()
    yield store
    store.clear()


# ---------- w4d1：向量库增删查 ----------

@pytest.mark.slow
def test_vector_store_upsert_search(clean_store):
    store = clean_store
    docs = [
        {"id": "c1", "text": "连锁餐饮门店扫码点单系统", "metadata": {"industry": "餐饮"}},
        {"id": "c2", "text": "企业客户管理系统 CRM", "metadata": {"industry": "企业服务"}},
        {"id": "c3", "text": "健身房会员约课系统", "metadata": {"industry": "体育健身"}},
        {"id": "c4", "text": "律师事务所合同审查助手", "metadata": {"industry": "法律"}},
    ]
    assert store.upsert(docs) == 4

    hits = store.search("餐饮门店点单小程序", top_k=3)
    assert hits and hits[0]["id"] == "c1"
    assert hits[0]["score"] > 0.5, f"top1 相似度应高: {hits[0]['score']}"
    assert all(h["metadata"]["industry"] for h in hits)


@pytest.mark.slow
def test_vector_store_persist_and_delete(clean_store):
    store = clean_store
    store.add_text("extra-1", "供应商自动对账结算系统", {"industry": "零售"})
    assert len(store._items) == 1

    # 重开实例 → 持久化生效（numpy npy + items.json 落盘）
    from app.retrieval.vector_store import VectorStore
    store2 = VectorStore()  # 同 CHROMA_DIR（conftest 临时目录）
    assert len(store2._items) == 1
    assert "供应商" in store2._items[0]["text"]

    store2.delete(["extra-1"])
    assert len(store2._items) == 0
    assert store2.search("对账") == []
    assert VectorStore()._items == []  # 删除已落盘


@pytest.mark.slow
def test_empty_store_search_returns_empty():
    store = get_vector_store()
    store.clear()
    assert store.search("任何查询") == []


# ---------- w4d2：md 文档切分入库 ----------

@pytest.mark.slow
def test_ingest_md_file(clean_store):
    import tempfile
    from pathlib import Path

    from app.retrieval.loader import ingest_file

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                     encoding="utf-8") as f:
        f.write(CASE_MD * 8)  # 拉长保证多 chunk
        path = Path(f.name)
    try:
        n = ingest_file(path, clean_store, metadata={"industry": "零售"})
        assert n >= 2, "长文应切多个 chunk"
        hits = clean_store.search("接龙小程序", top_k=3)
        assert hits, "入库后应能检索到"
    finally:
        path.unlink(missing_ok=True)


# ---------- w4d4：案例 → 检索器 → 诊断 state ----------

@pytest.mark.slow
def test_retrieve_cases_end_to_end(clean_store):
    """案例经 case_service 正规入库（DB + 向量双写）→ 检索器命中标题。"""
    import tempfile
    from pathlib import Path

    from app.db.database import SessionLocal
    from app.retrieval.retriever import retrieve_cases
    from app.services import case_service

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                     encoding="utf-8") as f:
        f.write(CASE_MD * 8)
        path = Path(f.name)
    db = SessionLocal()
    cid = None
    try:
        case = case_service.create_case_from_file(
            db, path, title="社区团购接龙小程序案例", industry="零售")
        cid = case.id
        assert case.vector_id == f"case-{case.id}"

        hits = retrieve_cases("我想给小区做个团购接龙小程序")
        assert hits, "应检索到刚入库的案例"
        assert hits[0]["title"] == "社区团购接龙小程序案例"
        assert hits[0]["score"] >= 0.35
    finally:
        if cid is not None:
            case_service.delete_case(db, cid)
        db.close()
        path.unlink(missing_ok=True)
