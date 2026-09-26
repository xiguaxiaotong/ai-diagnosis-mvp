"""HTTP API 层 —— 收编自 test_w3d4 / test_w5d1 / test_w5d2 / test_w5d4 /
test_w5d6 / test_w3d5(404 分支)。

TestClient 下 SSE 是整体响应（无真实网络时序）——断言事件序列顺序，
真实流式增量属 e2e 范畴不在此收编。前端 HTML 断言（w5d1[5]/w5d2[0] 等）
属前端验收，不收。
"""

import json

IDEA = "我想给奶茶店做扫码点单小程序"
ANSWER = "预算8万，两个月上线，堂食为主"


def _sse_events(text: str) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in text.splitlines()
            if line.startswith("data: ")]


def _api_project(client, headers, title: str = "API 测试项目") -> dict:
    r = client.post("/api/projects", headers=headers,
                    json={"title": title, "raw_idea": IDEA})
    assert r.status_code == 201, r.text
    return r.json()


# ---------- 基础 ----------

def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_auth_logout_revocation(client):
    """W10 Day1：登出 → token 立即失效（权限回收）；幂等；重新登录恢复。"""
    r = client.post("/api/auth/register", json={
        "username": "api_logout_user", "password": "api_logout_1"})
    assert r.status_code == 201, r.text
    headers = {"Authorization": "Bearer " + r.json()["token"]}
    assert client.get("/api/auth/me", headers=headers).status_code == 200

    # 登出 → 旧 token 权限回收
    assert client.post("/api/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    # 幂等：无效 token 重复登出仍 200（不泄漏 token 有效性）
    assert client.post("/api/auth/logout", headers=headers).status_code == 200

    # 重新登录恢复
    r = client.post("/api/auth/login", json={
        "username": "api_logout_user", "password": "api_logout_1"})
    assert r.status_code == 200, r.text
    assert client.get("/api/auth/me",
                      headers={"Authorization": "Bearer " + r.json()["token"]}).status_code == 200


def test_project_crud_api(client, admin_headers):
    p = _api_project(client, admin_headers, title="CRUD 接口项目")
    assert p["status"] == "diagnosing"
    assert p["title"] == "CRUD 接口项目"

    p2 = _api_project(client, admin_headers, title="第二个项目")
    r = client.get("/api/projects", headers=admin_headers)
    items = r.json()["items"]
    # 按时间倒序：最新在前
    assert items[0]["id"] == p2["id"] and items[1]["id"] == p["id"]

    r = client.get(f"/api/projects/{p['id']}", headers=admin_headers)
    d = r.json()
    assert d["raw_idea"] == IDEA
    assert d["messages"] == []

    r = client.delete(f"/api/projects/{p['id']}", headers=admin_headers)
    assert r.status_code == 200
    r = client.get(f"/api/projects/{p['id']}", headers=admin_headers)
    assert r.status_code == 404


def test_project_404s(client, admin_headers):
    # w3d5 的 404 分支
    assert client.get("/api/projects/999999",
                      headers=admin_headers).status_code == 404
    r = client.post("/api/chat", headers=admin_headers,
                    json={"project_id": 999999, "message": "你好"})
    assert r.status_code == 404


# ---------- SSE 对话流 ----------

def test_sse_chat_flow(client, admin_headers, stub_llm):
    """SSE 事件序列：meta 首个、delta 有内容、done 末个；轮次可推进。"""
    stub_llm["understand"] = "missing_then_full"
    p = _api_project(client, admin_headers)

    r = client.post("/api/chat", headers=admin_headers,
                    json={"project_id": p["id"], "message": IDEA})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    evts = _sse_events(r.text)
    # 事件序列：stage（0..n）→ meta → delta(s) → done；meta 是首个结果事件
    meta = next(e for e in evts if e["type"] == "meta")
    assert meta["phase"] == "clarify"
    assert evts[-1]["type"] == "done"
    deltas = [e for e in evts if e["type"] == "delta"]
    assert deltas, "正文增量不能为空"
    reply1 = "".join(e["content"] for e in deltas)
    assert reply1, "流式回复非空"

    # 第二轮补全 → 出方案（方案本体不随 SSE meta 下发，靠详情接口断言）
    r = client.post("/api/chat", headers=admin_headers,
                    json={"project_id": p["id"], "message": ANSWER})
    evts2 = _sse_events(r.text)
    meta2 = next(e for e in evts2 if e["type"] == "meta")
    assert meta2["phase"] == "confirm_wait"

    # 方案详情落库
    r = client.get(f"/api/projects/{p['id']}", headers=admin_headers)
    d = r.json()
    assert d["status"] == "plan_generated"
    msgs = d["messages"]
    assert len(msgs) >= 4, "双向落库：user + assistant 各两轮"
    assert [m["role"] for m in msgs[:2]] == ["user", "assistant"]


def test_sse_stage_events(client, admin_headers, stub_llm):
    """stage 事件（图节点阶段）先于正文，方案轮应含 generate。"""
    stub_llm["understand"] = "full"
    p = _api_project(client, admin_headers)
    r = client.post("/api/chat", headers=admin_headers,
                    json={"project_id": p["id"], "message": IDEA})
    evts = _sse_events(r.text)
    # SSE stage 事件字段名是 "stage"（{"type":"stage","stage":节点名,"label":提示}）
    stages = [e for e in evts if e["type"] == "stage"]
    meta_idx = next(i for i, e in enumerate(evts) if e["type"] == "meta")
    assert stages, "方案轮应有 stage 事件"
    assert all(i < meta_idx for i, e in enumerate(evts) if e["type"] == "stage")
    nodes = {e["stage"] for e in stages}
    assert {"understand", "generate", "budget"} <= nodes, f"节点阶段缺失: {nodes}"


# ---------- 确认循环 API ----------

def test_confirm_api_revise_then_confirm(client, admin_headers, stub_llm):
    stub_llm["understand"] = "missing_then_full"
    p = _api_project(client, admin_headers)
    client.post("/api/chat", headers=admin_headers,
                json={"project_id": p["id"], "message": IDEA})
    r = client.post("/api/chat", headers=admin_headers,
                    json={"project_id": p["id"], "message": ANSWER})
    evts = _sse_events(r.text)
    assert next(e for e in evts if e["type"] == "meta")["phase"] == "confirm_wait"

    # 修改一轮
    r = client.post(f"/api/project/{p['id']}/confirm", headers=admin_headers,
                    json={"action": "revise", "feedback": "去掉会员储值"})
    assert r.status_code == 200
    assert r.json()["phase"] == "confirm_wait"
    assert r.json()["revision_round"] == 1

    # 确认收尾
    r = client.post(f"/api/project/{p['id']}/confirm", headers=admin_headers,
                    json={"action": "confirm"})
    assert r.status_code == 200
    body = r.json()
    assert body["phase"] == "done"
    assert "方案已确认" in body["reply"]
    assert len(body["reply"]) < 200, "确认话术应短"
    r = client.get(f"/api/projects/{p['id']}", headers=admin_headers)
    assert r.json()["status"] == "confirmed"


def test_chat_requires_auth(client):
    r = client.post("/api/chat", json={"project_id": 1, "message": "你好"})
    assert r.status_code in (401, 403)
