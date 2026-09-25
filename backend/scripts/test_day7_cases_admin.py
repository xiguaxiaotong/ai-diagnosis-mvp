"""W7 Day7 验收：admin 案例库管理（列表 / 检索预览 / 上下架）。

⚠️ 测试隔离：所有数据走独立临时目录（SQLITE_PATH / CHROMA_DIR / CASES_DIR
env 覆盖，Day7 新增的基础设施），不碰 backend/data 主库（:8000 用的那个）。

验证点：
- [1] GET /api/admin/cases 列表：结构化字段全量返回，默认全部 published=true
- [2] PATCH /api/admin/cases/{id} 下架 → 列表 published=false；?published=false 筛中它
- [3] 检索预览 GET /api/admin/cases/retrieve-preview：与用户侧 retrieve_cases 同源；
      下架案例不再出现在预演结果里（重新上架后恢复）
- [4] 服务层 retrieve_cases 直查：下架过滤生效（防 API 层假阳性）
- [5] 非 admin（不在 ADMIN_USER_IDS 白名单）PATCH → 403
- [6] 幂等：PATCH 重复下架不报错

用法（在 backend/ 下，离线零 token，embedding 本地跑）：
    python scripts/test_day7_cases_admin.py
"""
import os
import sys
import tempfile
from pathlib import Path

# ---------- 测试隔离：env 必须在 import app 之前设置 ----------
_TMP = Path(tempfile.mkdtemp(prefix="day7_test_"))
os.environ["SQLITE_PATH"] = str(_TMP / "sqlite.db")
os.environ["CHROMA_DIR"] = str(_TMP / "chroma")
os.environ["CASES_DIR"] = str(_TMP / "cases")
os.environ["CHECKPOINTS_PATH"] = str(_TMP / "checkpoints.sqlite")
os.environ["ADMIN_USER_IDS"] = "1"  # user.id=1 是 admin

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.db.database import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402

PASS, FAIL = 0, 0


def check(name: str, ok: bool, detail: str = ""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}  {detail}")


def seed_cases() -> dict:
    """灌 3 条案例进独立库（2 客服 + 1 点单），返回 {title: case_id}。"""
    from app.services import case_service

    db = SessionLocal()
    ids = {}
    try:
        specs = [
            ("测试客服A：单渠道智能客服问答", "智能客服", "自动回复常见问题；单渠道接入；转人工",
             "客服A正文：面向公众号的智能客服，自动回复常见业务问题，复杂问题转人工坐席。",
             5000, 15000),
            ("测试客服B：多渠道客服中台", "智能客服", "多渠道接入；工单流转；质检",
             "客服B正文：多渠道智能客服中台，含工单自动生成分配与跨部门协同质检。",
             50000, 150000),
            ("测试点单：门店扫码点餐小程序", "餐饮", "扫码点单；会员储值；库存同步",
             "点单正文：连锁餐饮门店扫码点餐小程序，含会员储值与门店库存同步。",
             8000, 30000),
        ]
        for title, scenario, features, body, bmin, bmax in specs:
            cases_dir = Path(os.environ["CASES_DIR"])
            cases_dir.mkdir(parents=True, exist_ok=True)
            p = cases_dir / f"day7_{len(ids)}.md"
            p.write_text(f"# {title}\n\n{body}", encoding="utf-8")
            case, _ = case_service.upsert_case_structured(
                db, title=title, body=body, file_path=p,
                industry=scenario, scenario=scenario, features=features,
                budget_min=bmin, budget_max=bmax,
            )
            ids[title] = case.id
    finally:
        db.close()
    return ids


def main():
    init_db()  # 在独立库上跑全部迁移（0001→0008）

    client = TestClient(app)

    # admin 账号（id=1，在白名单内）
    r = client.post("/api/auth/register", json={
        "username": "day7_admin", "password": "day7pass123"})
    assert r.status_code == 201, r.text
    r = client.post("/api/auth/login", json={
        "username": "day7_admin", "password": "day7pass123"})
    assert r.status_code == 200, r.text
    admin_headers = {"Authorization": "Bearer " + r.json()["token"]}

    # 非 admin 账号（id=2，不在白名单）
    r = client.post("/api/auth/register", json={
        "username": "day7_user", "password": "day7pass456"})
    r = client.post("/api/auth/login", json={
        "username": "day7_user", "password": "day7pass456"})
    user_headers = {"Authorization": "Bearer " + r.json()["token"]}

    ids = seed_cases()
    print(f"\n[seed] 独立库灌入 {len(ids)} 条案例，库目录 {_TMP}\n")

    # ---- [1] 列表 ----
    print("[1] admin 案例列表")
    r = client.get("/api/admin/cases", headers=admin_headers)
    check("GET /api/admin/cases 200", r.status_code == 200, r.text[:200])
    items = r.json()["items"]
    check(f"返回 3 条（实际 {len(items)}）", len(items) == 3)
    check("默认全部上架", all(i["published"] is True for i in items))
    check("结构化字段返回（scenario/budget_min/published）",
          all("scenario" in i and "budget_min" in i and "published" in i for i in items))
    check("按 id 倒序", [i["id"] for i in items] == sorted(
        [i["id"] for i in items], reverse=True))

    # 搜索过滤
    r = client.get("/api/admin/cases", params={"q": "点餐"}, headers=admin_headers)
    check("q=点餐 只命中点单案例", len(r.json()["items"]) == 1
          and "点单" in r.json()["items"][0]["title"])

    # ---- [5] 越权 ----
    print("\n[2] 越权拦截")
    r = client.get("/api/admin/cases", headers=user_headers)
    check("非 admin 列表 403", r.status_code == 403, f"实际 {r.status_code}")
    r = client.patch(f"/api/admin/cases/{ids['测试客服A：单渠道智能客服问答']}",
                     json={"published": False}, headers=user_headers)
    check("非 admin PATCH 403", r.status_code == 403, f"实际 {r.status_code}")
    r = client.get("/api/admin/cases")  # 未登录
    check("未登录 401/403", r.status_code in (401, 403), f"实际 {r.status_code}")

    # ---- [3] 检索预览（下架前基线）----
    print("\n[3] 检索预览（下架前）")
    q = "我想做个能自动回复客户咨询的客服"
    r = client.get("/api/admin/cases/retrieve-preview",
                   params={"query": q, "top_k": 3}, headers=admin_headers)
    check("retrieve-preview 200", r.status_code == 200, r.text[:200])
    hits = r.json()["items"]
    titles = [h["title"] for h in hits]
    check("客服A/客服B 至少命中一个", any("客服" in t for t in titles), str(titles))

    # ---- [2] 下架 → 检索过滤 ----
    print("\n[4] 下架最相关的客服A")
    off_id = ids["测试客服A：单渠道智能客服问答"]
    r = client.patch(f"/api/admin/cases/{off_id}", json={"published": False},
                     headers=admin_headers)
    check("PATCH 下架 200", r.status_code == 200, r.text[:200])
    check("返回 published=false", r.json()["case"]["published"] is False)

    # 列表能看到（admin 全量视角）
    r = client.get("/api/admin/cases", headers=admin_headers)
    off_item = next((i for i in r.json()["items"] if i["id"] == off_id), None)
    check("列表仍含下架案例（admin 视角全量）", off_item is not None
          and off_item["published"] is False)
    r = client.get("/api/admin/cases", params={"published": "false"}, headers=admin_headers)
    check("?published=false 只筛出 1 条", len(r.json()["items"]) == 1
          and r.json()["items"][0]["id"] == off_id)

    # 检索预览不再召回客服A
    r = client.get("/api/admin/cases/retrieve-preview",
                   params={"query": q, "top_k": 3}, headers=admin_headers)
    titles = [h["title"] for h in r.json()["items"]]
    check("下架案例不在预演结果", "客服A" not in "".join(titles), str(titles))
    check("客服B 仍在（只下架了A）", any("客服B" in t for t in titles), str(titles))

    # ---- [4] 服务层直查 ----
    print("\n[5] 服务层 retrieve_cases 直查")
    from app.retrieval.retriever import retrieve_cases
    svc_titles = [h["title"] for h in retrieve_cases(q, top_k=3)]
    check("服务层同样过滤下架", "客服A" not in "".join(svc_titles), str(svc_titles))

    # ---- [6] 重复下架幂等 ----
    print("\n[6] 幂等")
    r = client.patch(f"/api/admin/cases/{off_id}", json={"published": False},
                     headers=admin_headers)
    check("重复下架不报错", r.status_code == 200 and r.json()["case"]["published"] is False)

    # ---- 重新上架恢复 ----
    print("\n[7] 重新上架恢复")
    r = client.patch(f"/api/admin/cases/{off_id}", json={"published": True},
                     headers=admin_headers)
    check("重新上架 200", r.status_code == 200)
    r = client.get("/api/admin/cases/retrieve-preview",
                   params={"query": q, "top_k": 3}, headers=admin_headers)
    titles = [h["title"] for h in r.json()["items"]]
    check("上架后重新可召回", any("客服A" in t for t in titles), str(titles))

    # ---- 404 ----
    r = client.patch("/api/admin/cases/99999", json={"published": False},
                     headers=admin_headers)
    check("不存在案例 404", r.status_code == 404, f"实际 {r.status_code}")

    print(f"\n{'='*50}\n结果：{PASS} 通过 / {FAIL} 失败 · 测试库：{_TMP}")
    if FAIL == 0:
        print("主库未受影响（全程独立库）")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
