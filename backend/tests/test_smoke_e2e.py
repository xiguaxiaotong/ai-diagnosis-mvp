"""W10 Day1：API 层端到端冒烟套件（为 v2.0 上线做准备）。

与《生产上线冒烟清单.docx》的对照（2026-09-26 版，43 项）：
- 能自动化的用例见各 test 的 docstring（标【清单 x.y】）；
- 浏览器视觉 / 移动端 / 部署环境类无法（或不应）在本套件自动化，列为人肉项：

人肉项（上线日在正式环境人工核对，本套件不覆盖）：
- 1.1-1.6  部署与环境：DNS / HTTPS / 强跳 / 容器状态 / volume 挂载 / 中文字体与 OCR 视觉
           （本地无对应物；1.6 的文本提取管线已被 tests/test_retrieval 等覆盖）
- 2.3      「当前问题」提示条交互（前端视觉）
- 2.5      方案展示页完整性（业务/技术/预算/可行性齐全——视觉核对；数据层由 09 号用例部分覆盖）
- 2.6      确认后收尾话术 + 刷新状态保持（触发确认需再烧一轮 LLM，成本不划算，人工点）
- 2.7      「修改需求」回显交互（前端视觉）
- 3.1/3.2  意图分流 / 商业机密引导（真实 LLM 语义判断，已由黄金集 + tests/test_consult 覆盖，
           冒烟不重复烧钱）
- 3.3      文件上传识别（txt/docx/pdf/OCR——上传即触发 LLM 轮，人工冒烟）
- 3.4      打字指示器 / 手机端 SSE 心跳视觉
- 3.6      历史项目列表 UI（数据层由 03 号用例覆盖）
- 4.1      登录态跨端/刷新保持（浏览器行为；token 复用语义由 02/11 号用例覆盖）
- 5.1-5.4  移动端适配（全部）
- 6.1      prompt 注入告警日志查看（扫描逻辑已由 tests/test_security 覆盖）
- 6.3      断网恢复 / 删除二次确认（前端交互）
- 6.4      FAQ 文案
- 6.5      反馈渠道
- 7.1-7.3  备案与合规展示（正式环境备案号）
- 8.1-8.4  性能 / 并发 / 日志查看 / 成本统计（上线日人工观察；后端日志由 run_smoke.bat
           落盘 logs/smoke_server.log 辅助排查）
- 9.1-9.3  镜像 tag / 回滚步骤 / 上线前备份（backup_db.py 已有，上线日人工执行并核对）

运行方式（唯一入口）：
    backend\\scripts\\run_smoke.bat
    = 起本地服务(8000) -> 等就绪 -> 跑本套件（真实 LLM 一轮，约 4 分钱）-> PASS/FAIL -> 清理

隔离与自净（不污染主库）：
- run_smoke.bat 用独立 data/smoke/ 库起服务，主库 / 主 checkpoint / 主 trace 零接触；
- 本套件所有注册数据带 smoke_ 前缀，结尾自动清掉自己造的数据（API 删项目 + DB 删
  smoke_ 前缀用户/会话），重复跑或对着主库直跑也不留垃圾；
- 需要显式 SMOKE_E2E=1 才会执行（快速档 `-m "not llm and not slow"` 收集到也自动跳过）。
"""

import json
import os
import sqlite3
import uuid

import httpx
import pytest

# ---------- 门槛：只在 SMOKE_E2E=1 时跑（run_smoke.bat 设置；快速档自动跳过） ----------
pytestmark = [
    pytest.mark.smoke,
    pytest.mark.skipif(
        os.environ.get("SMOKE_E2E") != "1",
        reason="端到端冒烟需直连运行中的服务：用 backend/scripts/run_smoke.bat（设 SMOKE_E2E=1）",
    ),
]

BASE_URL = os.environ.get("SMOKE_BASE_URL", "http://127.0.0.1:8000")
SMOKE_DB = os.environ.get("SMOKE_DB", "")
SMOKE_LIKE = "smoke\\_%"  # LIKE 参数（转义下划线，只匹配字面 smoke_ 前缀）

# 故意信息残缺的业务想法（无预算/无工期/功能模糊）→ understand 节点必然走追问
IDEA = "我想在小区里做一个宠物临时寄养的小程序，帮邻居出差时托管猫狗"
PASSWORD = "smoke_pass_1"

_TIMEOUT = httpx.Timeout(connect=5.0, read=300.0, write=30.0, pool=30.0)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _iter_sse_events(resp: httpx.Response) -> list[dict]:
    """解析 SSE（data: JSON 行）为事件列表。"""
    events = []
    for line in resp.iter_lines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


def _cleanup_api(ctx: dict) -> None:
    """清理第一步（API 层）：重登 admin（登出用例可能已换 token）→ 删冒烟项目。

    幂等：项目已删 / 登录失败都安静跳过（用户行清理在 _cleanup_db 里兜底）。
    """
    try:
        r = ctx["client"].post("/api/auth/login", json={
            "username": ctx["admin_user"], "password": PASSWORD})
        if r.status_code == 200:
            ctx["admin_token"] = r.json()["token"]
    except Exception:
        pass
    if ctx.get("project_id") is not None:
        try:
            ctx["client"].delete(f"/api/projects/{ctx['project_id']}",
                                 headers=_auth(ctx["admin_token"]))
        except Exception:
            pass


def _cleanup_db(*, expect_clean: bool) -> None:
    """清理第二步（DB 层）：清掉全部 smoke_ 前缀数据（幂等）。

    项目已由 API 删除（service 级联 conversations/leads/worksheets）；
    这里兜底清 conversations 残留 + smoke_ 用户与会话行（无用户删除 API）。
    注意：删用户即删会话 → 所有 smoke token 从此失效，故凡需要有效 token 的
    验证必须在调用本函数之前完成。
    """
    if not (SMOKE_DB and os.path.exists(SMOKE_DB)):
        return
    con = sqlite3.connect(SMOKE_DB, timeout=10)
    try:
        cur = con.cursor()
        cur.execute(
            "DELETE FROM conversations WHERE project_id IN "
            "(SELECT p.id FROM projects p JOIN users u ON p.user_id = u.id "
            " WHERE u.username LIKE ? ESCAPE '\\')", (SMOKE_LIKE,))
        cur.execute(
            "DELETE FROM projects WHERE user_id IN "
            "(SELECT id FROM users WHERE username LIKE ? ESCAPE '\\')", (SMOKE_LIKE,))
        cur.execute(
            "DELETE FROM auth_sessions WHERE user_id IN "
            "(SELECT id FROM users WHERE username LIKE ? ESCAPE '\\')", (SMOKE_LIKE,))
        cur.execute("DELETE FROM users WHERE username LIKE ? ESCAPE '\\'", (SMOKE_LIKE,))
        con.commit()
        if expect_clean:
            left = cur.execute(
                "SELECT COUNT(*) FROM users WHERE username LIKE ? ESCAPE '\\'",
                (SMOKE_LIKE,)).fetchone()[0]
            assert left == 0, f"清理后仍有 {left} 个 smoke_ 用户残留"
    finally:
        con.close()


@pytest.fixture(scope="module")
def ctx():
    """冒烟全程共享的会话状态：admin（首个注册 → id=1 → ADMIN_USER_IDS=1 即运营）+ 普通用户 B。

    run_smoke.bat 每次起服务前重建 data/smoke/（全新库），保证注册顺序决定 id：
    admin 必须第一个注册。对着手工启动的服务跑时该假设可能不成立（admin 不是 id=1），
    02 号用例的 is_admin 断言会明确报出来。
    """
    suffix = uuid.uuid4().hex[:8]
    state = {
        "suffix": suffix,
        "admin_user": f"smoke_admin_{suffix}",
        "user_b": f"smoke_b_{suffix}",
        "password": PASSWORD,
        "admin_token": "",
        "b_token": "",
        "project_id": None,
    }
    with httpx.Client(base_url=BASE_URL, timeout=_TIMEOUT) as client:
        state["client"] = client
        try:
            yield state
        finally:
            # 无论用例成败，退出前自净（幂等；99 号用例已清过则此处为空跑）
            _cleanup_api(state)
            _cleanup_db(expect_clean=False)


# ---------- 01 健康检查 ----------
def test_01_health(ctx):
    """【清单 1.4 部分：后端服务进程存活】+ 服务根路径。"""
    r = ctx["client"].get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert ctx["client"].get("/").status_code == 200


# ---------- 02 注册 / 登录 ----------
def test_02_register_login(ctx):
    """【清单 4 登录与账号：注册 / 登录 / me（4.1 的 token 复用语义）】。

    admin 必须是全新库第一个注册用户（id=1 = ADMIN_USER_IDS=1），
    断言 is_admin 防止对着旧库跑冒烟时静默走到后面才发现 403。
    """
    c = ctx["client"]
    r = c.post("/api/auth/register", json={
        "username": ctx["admin_user"], "password": PASSWORD})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["token"] and body["user"]["is_admin"] is True, (
        "首个注册用户应为 admin（id=1 = ADMIN_USER_IDS）；"
        "若对着手工启动的旧库跑会出现此失败——请走 run_smoke.bat（全新冒烟库）")
    ctx["admin_token"] = body["token"]

    r = c.post("/api/auth/register", json={
        "username": ctx["user_b"], "password": PASSWORD})
    assert r.status_code == 201, r.text
    ctx["b_token"] = r.json()["token"]
    assert r.json()["user"]["is_admin"] is False

    # 登录走通 + me（登录态保持的 token 语义）
    r = c.post("/api/auth/login", json={
        "username": ctx["user_b"], "password": PASSWORD})
    assert r.status_code == 200, r.text
    assert ctx["user_b"] == r.json()["user"]["username"]
    r = c.get("/api/auth/me", headers=_auth(ctx["admin_token"]))
    assert r.status_code == 200
    assert r.json()["user"]["is_admin"] is True


# ---------- 03 建项目 ----------
def test_03_create_project(ctx):
    """【清单 2.1 部分：创建项目（后端侧；浏览器跳转为前端人肉项）】+ 列表可见。"""
    c = ctx["client"]
    r = c.post("/api/projects", headers=_auth(ctx["admin_token"]),
               json={"title": f"smoke 项目 {ctx['suffix']}", "raw_idea": IDEA})
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["status"] == "diagnosing"
    ctx["project_id"] = p["id"]

    r = c.get("/api/projects", headers=_auth(ctx["admin_token"]))
    assert r.status_code == 200
    assert p["id"] in [i["id"] for i in r.json()["items"]]


# ---------- 04 诊断一轮 SSE（真实 LLM，约 4 分钱） ----------
def test_04_sse_diagnosis_round(ctx):
    """【清单 2.2 追问澄清（先确认需求不甩方案）+ 2.4 SSE 流式 + 2.6 部分：双向落库】。

    信息残缺的想法 → understand 节点判定缺信息 → phase=clarify 追问。
    SSE 事件序列：stage（图节点阶段）→ meta → delta（token 实时）→ done。
    """
    c = ctx["client"]
    pid = ctx["project_id"]
    with c.stream("POST", "/api/chat", headers=_auth(ctx["admin_token"]),
                  json={"project_id": pid, "message": IDEA}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        events = _iter_sse_events(r)

    assert events, "SSE 一个事件都没收到"
    assert events[-1].get("type") == "done", f"流未正常结束: {events[-3:]}"
    assert any(e.get("type") == "stage" for e in events), "缺少图节点阶段事件"
    metas = [e for e in events if e.get("type") == "meta"]
    assert metas, "缺少 meta 事件"
    assert metas[0]["phase"] == "clarify", (
        f"信息残缺的想法首轮应为追问（clarify），实际 {metas[0]['phase']!r}")
    assert metas[0].get("questions"), "追问 meta 应带问题清单"
    deltas = "".join(e.get("content", "") for e in events if e.get("type") == "delta")
    assert len(deltas) >= 20, f"流式正文过短: {deltas[:50]!r}"

    # 回复落库（2.6 的数据层）：本轮 user + assistant 两条消息
    r = c.get(f"/api/project/{pid}", headers=_auth(ctx["admin_token"]))
    assert r.status_code == 200
    roles = [m["role"] for m in r.json()["messages"]]
    assert roles[-2:] == ["user", "assistant"], roles


# ---------- 05 消息校验 ----------
def test_05_message_validation(ctx):
    """【清单 3.5 部分：空消息拒绝（不触发流程图卡死）】。超长截断属 LLM 输入侧行为，人肉。"""
    c = ctx["client"]
    for msg in ["", "   "]:
        r = c.post("/api/chat", headers=_auth(ctx["admin_token"]),
                   json={"project_id": ctx["project_id"], "message": msg})
        assert r.status_code == 422, (msg, r.status_code, r.text)


# ---------- 06 admin 运营后台全 200 ----------
def test_06_admin_endpoints(ctx):
    """运营后台五个核心口全 200 + 普通用户 403（v2.0 后台项，清单无编号）。

    【清单 8.3 辅助：后端日志由 run_smoke.bat 落盘 logs/smoke_server.log】。
    """
    c = ctx["client"]
    admin = _auth(ctx["admin_token"])
    for path in ["/api/admin/stats", "/api/admin/traces", "/api/admin/leads",
                 "/api/admin/cases", "/api/admin/worksheets"]:
        r = c.get(path, headers=admin)
        assert r.status_code == 200, (path, r.status_code, r.text[:200])

    # 普通用户进不了运营后台（403，区别于 401 未登录）
    r = c.get("/api/admin/stats", headers=_auth(ctx["b_token"]))
    assert r.status_code == 403, r.status_code


# ---------- 07 未登录 401 ----------
def test_07_auth_required(ctx):
    """【清单 6.2：鉴权覆盖项目接口——未登录访问被拒】。"""
    c = ctx["client"]
    assert c.get("/api/projects").status_code == 401
    assert c.get("/api/projects", headers={"Authorization": "Bearer not-a-token"}).status_code == 401
    assert c.get(f"/api/project/{ctx['project_id']}").status_code == 401


# ---------- 08 账号隔离 / 404 防枚举 ----------
def test_08_isolation_and_404(ctx):
    """【清单 4.2 账号隔离 + 4.3 404 防枚举】：B 看不到 admin 的项目，且返回 404 不泄露存在性。"""
    c = ctx["client"]
    pid = ctx["project_id"]
    for method, path in [("GET", f"/api/project/{pid}"),
                         ("GET", f"/api/projects/{pid}"),
                         ("DELETE", f"/api/projects/{pid}")]:
        r = c.request(method, path, headers=_auth(ctx["b_token"]))
        assert r.status_code == 404, (method, r.status_code)
    # 完全不存在的 id 同样 404（响应与上面不可区分 = 防枚举）
    assert c.get("/api/project/999999999",
                 headers=_auth(ctx["b_token"])).status_code == 404


# ---------- 09 方案分享 ----------
def test_09_share_link(ctx):
    """【清单 2.5 部分：方案数据可公开获取（页面视觉完整性人肉）】。"""
    c = ctx["client"]
    r = c.post(f"/api/projects/{ctx['project_id']}/share",
               headers=_auth(ctx["admin_token"]))
    assert r.status_code == 200, r.text
    token = r.json()["share_token"]

    # 公开只读（无需登录）
    r = c.get(f"/api/share/{token}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "smoke" in body["title"] or ctx["suffix"] in body["title"]
    assert "raw_idea" not in body and "messages" not in body  # 对话隐私不外泄


# ---------- 10 限流 429 真触发 ----------
def test_10_rate_limit_429(ctx):
    """限流真触发（W9 B 项 + 清单 6 稳定性）：注册 10 次/小时/IP 打满 → 第 11 次 429。

    选注册口而非诊断口触发：注册不烧 LLM（诊断每用户每分钟 5 次的语义
    已由 tests/test_security.py 快速档覆盖），冒烟不重复花真金白银。
    """
    c = ctx["client"]
    seen_429 = False
    for i in range(30):  # 正常 10/hour，已用 2（admin+B），8 次内必超；30 为异常兜底
        r = c.post("/api/auth/register", json={
            "username": f"smoke_junk_{ctx['suffix']}_{i}", "password": PASSWORD})
        if r.status_code == 429:
            assert "Retry-After" in r.headers, r.headers
            assert r.json()["detail"], "429 应带人话文案"
            seen_429 = True
            break
        assert r.status_code == 201, (r.status_code, r.text[:200])
    assert seen_429, "注册 30 次仍未触发限流（RATE_LIMIT_ENABLED 或阈值异常）"


# ---------- 11 登出 → 权限回收 ----------
def test_11_logout_revocation(ctx):
    """【清单 4.1 部分：登出后权限回收】——token 服务端失效，非仅前端丢弃。"""
    c = ctx["client"]
    old_token = ctx["admin_token"]
    r = c.post("/api/auth/logout", headers=_auth(old_token))
    assert r.status_code == 200, r.text
    # 旧 token 立即失效
    assert c.get("/api/projects", headers=_auth(old_token)).status_code == 401
    # 幂等：重复登出仍 200（不泄漏 token 有效性）
    assert c.post("/api/auth/logout", headers=_auth(old_token)).status_code == 200
    # 重新登录恢复
    r = c.post("/api/auth/login", json={
        "username": ctx["admin_user"], "password": PASSWORD})
    assert r.status_code == 200, r.text
    ctx["admin_token"] = r.json()["token"]
    assert c.get("/api/auth/me", headers=_auth(ctx["admin_token"])).status_code == 200


# ---------- 99 自净 ----------
def test_99_cleanup(ctx):
    """套件自净：清掉自己造的全部 smoke_ 数据（不污染主库 / 可重复跑）。

    项目走 API 删除（service 级联 conversations/leads/worksheets），验证 404 后
    再 DB 直清 smoke_ 用户与会话行（无用户删除 API），末尾断言零残留。
    注意顺序：删用户即删会话（token 全失效），所有带 token 的验证必须在前。
    """
    _cleanup_api(ctx)
    # 项目已删：详情 404（此时 admin token 仍有效）
    r = ctx["client"].get(f"/api/projects/{ctx['project_id']}",
                          headers=_auth(ctx["admin_token"]))
    assert r.status_code == 404, r.status_code
    # 用户/会话行清干净（此后所有 smoke token 失效）
    _cleanup_db(expect_clean=True)
