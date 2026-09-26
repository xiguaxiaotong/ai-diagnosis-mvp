"""案例管理 API —— 收编自 test_w4d3（上传/列表/详情/删除/415/文件清理）。"""

import io

from app.config import CASES_DIR
from app.db.database import SessionLocal
from app.db.models import Case
from app.retrieval.vector_store import get_vector_store

MD = ("# 测试案例\n某连锁咖啡品牌点单小程序项目复盘。核心模块包括扫码点单、"
      "会员积分、多门店库存、经营报表。\n" * 8)


def _upload(client, filename: str = "case.md", content: bytes = MD.encode("utf-8"),
            title: str = "pytest 上传案例"):
    return client.post(
        "/api/cases/upload",
        files={"file": (filename, io.BytesIO(content), "text/markdown")},
        data={"title": title, "industry": "餐饮"},
    )


def test_upload_and_detail(client, admin_headers):
    get_vector_store().clear()
    r = _upload(client)
    assert r.status_code == 201, r.text
    case = r.json()
    assert case["vector_id"] == f"case-{case['id']}"
    assert case["industry"] == "餐饮"
    assert case["summary"]

    # 列表 / 详情可查
    r = client.get("/api/cases")
    assert any(c["id"] == case["id"] for c in r.json()["items"])
    r = client.get(f"/api/cases/{case['id']}")
    assert r.status_code == 200

    # 检索能命中（入库即向量化）
    from app.retrieval.retriever import retrieve_cases
    hits = retrieve_cases("咖啡点单小程序")
    assert any(h["title"] == case["title"] for h in hits)


def test_upload_rejects_exe(client, admin_headers):
    r = _upload(client, filename="virus.exe", content=b"MZ...")
    assert r.status_code == 415


def test_delete_case_cleans_up(client, admin_headers):
    get_vector_store().clear()
    r = _upload(client, title="待删除案例")
    case = r.json()

    file_path = None
    db = SessionLocal()
    try:
        c = db.get(Case, case["id"])
        file_path = c.file_path
    finally:
        db.close()

    r = client.delete(f"/api/cases/{case['id']}")
    assert r.status_code == 200
    assert client.get(f"/api/cases/{case['id']}").status_code == 404
    # 向量清理：doc_id 下无残留 chunk
    store = get_vector_store()
    assert all((it.get("metadata") or {}).get("doc_id") != case["vector_id"]
               for it in store._items)
    # 原始文件删除（file_path 落在临时 CASES_DIR）
    import pathlib
    assert not (file_path and pathlib.Path(file_path).exists())
    # 重复删除 → 404
    assert client.delete(f"/api/cases/{case['id']}").status_code == 404


def test_admin_cases_requires_admin(client, admin_headers):
    """W7 Day7 权限回归：/api/admin/cases 仅 admin。"""
    r = client.post("/api/auth/register", json={
        "username": "plain_user", "password": "plain_user_1"})
    assert r.status_code == 201
    r = client.post("/api/auth/login", json={
        "username": "plain_user", "password": "plain_user_1"})
    user_h = {"Authorization": "Bearer " + r.json()["token"]}
    assert client.get("/api/admin/cases", headers=user_h).status_code == 403
    assert client.get("/api/admin/cases").status_code in (401, 403)
    assert client.get("/api/admin/cases", headers=admin_headers).status_code == 200
