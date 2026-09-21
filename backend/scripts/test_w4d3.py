"""Week4 Day3 验收：案例管理 API（POST /api/cases/upload → SQLite + Chroma）。

验收标准：上传案例后能在数据库查到。
- TestClient 走完整 FastAPI 栈（multipart 上传）
- 断言：SQLite 有记录、Chroma 有向量、检索可命中、删除三处清干净

用法（在 backend/ 目录下运行，无需 key——bge 本地模型）：
    python scripts/test_w4d3.py
"""

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.retrieval.vector_store import get_vector_store  # noqa: E402

MD_BODY = (
    "社区团购小程序项目复盘。团长在微信群里开团发布商品，"
    "用户在接龙页面下单付款，次日到自提点取货。"
    "核心功能包括团长管理后台、商品上架与库存控制、"
    "微信支付分账与佣金结算、售后退款流程。"
    "采用微信小程序加 H5 双端方案，后端 Node.js 与 MongoDB，"
    "部署在云服务器上，单社区运营三个月实现日均两百单。"
) * 5  # >500 字，强制多 chunk


def main() -> None:
    with TestClient(app) as client:
        assert client.get("/api/health").json() == {"status": "ok"}

        # ========== 1. 上传案例（multipart） ==========
        files = {"file": ("案例-社区团购.md", MD_BODY.encode("utf-8"), "text/markdown")}
        r = client.post("/api/cases/upload",
                        data={"title": "社区团购案例", "industry": "电商"},
                        files=files)
        assert r.status_code == 201, r.text
        case = r.json()
        cid, vid = case["id"], case["vector_id"]
        assert vid == f"case-{cid}", f"vector_id 应为 case-前缀: {vid}"
        assert case["industry"] == "电商" and case["summary"], case
        print(f"[1] 上传 OK：id={cid}，vector_id={vid}，summary={case['summary'][:20]}...")

        # ========== 2. 数据库可查（列表 + 详情） ==========
        items = client.get("/api/cases").json()["items"]
        assert any(c["id"] == cid for c in items), "列表中应有新案例"
        detail = client.get(f"/api/cases/{cid}").json()
        assert detail["title"] == "社区团购案例"
        print(f"[2] 查库 OK：列表 {len(items)} 条，详情字段齐全")

        # ========== 3. 向量库可查（按 metadata 定位 + 语义检索） ==========
        store = get_vector_store()
        hits = store.search("团长开团 接龙下单 自提", top_k=3)
        assert hits, "检索无结果"
        assert hits[0]["metadata"].get("case_db_id") == cid, hits[0]["metadata"]
        n_chunks = store._collection.get(where={"doc_id": vid})["ids"]
        assert len(n_chunks) >= 2, f"应切出多个 chunk: {len(n_chunks)}"
        print(f"[3] 向量库 OK：{len(n_chunks)} chunks，检索 top1 命中本案例"
              f"（score={hits[0]['score']}）")

        # ========== 4. 通过 API 检索链路（案例 → 相似案例查询同款逻辑） ==========
        bad = client.post("/api/cases/upload",
                          data={"title": "x", "industry": ""},
                          files={"file": ("bad.exe", b"MZ...", "application/x-msdownload")})
        assert bad.status_code == 415, bad.status_code
        print(f"[4] 格式校验 OK：.exe 上传被 415 拒绝")

        # ========== 5. 删除：SQLite + Chroma + 文件三处清 ==========
        assert client.delete(f"/api/cases/{cid}").status_code == 200
        assert client.get(f"/api/cases/{cid}").status_code == 404
        assert store._collection.get(where={"doc_id": vid})["ids"] == [], "向量未清"
        assert not Path(detail["file_path"]).exists(), "原始文件未删"
        print(f"[5] 删除 OK：DB 行、Chroma 向量、原始文件三处清干净")

        # 再删一次应 404
        assert client.delete(f"/api/cases/{cid}").status_code == 404

    print("\n" + "=" * 54)
    print("✅ Week4 Day3 验收通过（案例上传 → SQLite + Chroma 双写 → 检索 → 删除）")
    print("=" * 54)


if __name__ == "__main__":
    main()
