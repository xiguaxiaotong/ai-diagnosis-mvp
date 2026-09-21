"""Week4 Day1 验收：Chroma 集成（vector_store.py 增删查 + bge Embedding）。

验收标准：能插入文本、按相似度检索。
全部离线（bge 本地模型，无需 key），使用临时目录不污染真实库。

用法（在 backend/ 目录下运行）：
    python scripts/test_w4d1.py
"""

import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.retrieval.vector_store import VectorStore  # noqa: E402

CASES = [
    {"id": "c1", "text": "连锁餐饮扫码点单微信小程序：顾客桌边扫码点餐，后厨出单，支持会员储值和优惠券",
     "metadata": {"industry": "餐饮", "scale": "3 家门店"}},
    {"id": "c2", "text": "外贸公司客户管理系统：客户跟进记录、商机漏斗、邮件模板，网页端使用",
     "metadata": {"industry": "外贸", "scale": "10 人团队"}},
    {"id": "c3", "text": "社区团购小程序：团长开团、用户接龙下单、次日自提，对接微信支付",
     "metadata": {"industry": "电商", "scale": "单社区"}},
    {"id": "c4", "text": "健身房会员约课系统：团课排期、约课消课、教练排班，H5 页面",
     "metadata": {"industry": "健身", "scale": "2 家门店"}},
]


def main() -> None:
    tmp = tempfile.mkdtemp(prefix="chroma_w4d1_")
    store = VectorStore(path=tmp)
    print(f"[0] 临时库已创建: {tmp}")

    # ========== 1. 插入 ==========
    n = store.upsert(CASES)
    assert n == 4 and store.count() == 4, (n, store.count())
    print(f"[1] 插入 OK：{store.count()} 条文档已入库（bge 向量化）")

    # ========== 2. 相似度检索：语义命中 ==========
    hits = store.search("我想做个顾客扫码点餐的小程序", top_k=2)
    assert len(hits) == 2, hits
    assert hits[0]["id"] == "c1", f"top1 应为点单案例 c1: {hits[0]['id']}"
    assert hits[0]["score"] > 0.5, f"相关案例相似度过低: {hits[0]['score']}"
    print(f"[2] 检索 OK：top1={hits[0]['id']}（score={hits[0]['score']}），"
          f"top2={hits[1]['id']}（score={hits[1]['score']}）")
    print(f"    top1 内容: {hits[0]['text'][:30]}...")

    # ========== 3. metadata 过滤检索 ==========
    hits = store.search("管理客户跟进", top_k=4, where={"industry": "餐饮"})
    assert all(h["metadata"].get("industry") == "餐饮" for h in hits), hits
    print(f"[3] metadata 过滤 OK：industry=餐饮 命中 {len(hits)} 条")

    # ========== 4. upsert 覆盖 + 单条便捷插入 ==========
    store.add_text("c3-updated", "社区团购小程序（新版）：多城市运营，含供应商结算",
                   {"industry": "电商"})
    doc = store.get("c3-updated")
    assert doc and "供应商结算" in doc["text"], doc
    assert store.count() == 5, store.count()
    print(f"[4] add_text/upsert OK：单条插入后共 {store.count()} 条")

    # ========== 5. 持久化：重开实例数据还在 ==========
    store2 = VectorStore(path=tmp)
    assert store2.count() == 5, store2.count()
    hits = store2.search("团长开团接龙下单", top_k=1)
    assert hits and hits[0]["score"] > 0.5, hits
    print(f"[5] 持久化 OK：重开实例 count={store2.count()}，"
          f"检索 top1={hits[0]['id']}（score={hits[0]['score']}）")

    # ========== 6. 删除 ==========
    store2.delete(["c3-updated"])
    assert store2.count() == 4 and store2.get("c3-updated") is None
    print(f"[6] 删除 OK：剩余 {store2.count()} 条")

    # ========== 7. 空库检索不报错 ==========
    empty = VectorStore(path=f"{tmp}/empty")
    assert empty.search("随便查查") == []
    print(f"[7] 空库边界 OK：返回空列表")

    print("\n" + "=" * 54)
    print("✅ Week4 Day1 验收通过（Chroma 增删查 + 相似度检索 + 持久化）")
    print("=" * 54)


if __name__ == "__main__":
    main()
