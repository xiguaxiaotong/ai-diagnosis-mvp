"""pytest 公共基建（W8 Day4 收编）。

铁律：env 隔离必须在任何 app.* import 之前生效——conftest 顶部第一件事
就是设 env，pytest 收集阶段 import 本文件先于所有测试模块，天然满足。

隔离范围（session 级单临时目录，全部测试共享一个干净库）：
    SQLITE_PATH / CHROMA_DIR / CASES_DIR / CHECKPOINTS_PATH / TRACE_PATH
主库、主 trace、主 checkpoint 文件全程零接触。

ADMIN_USER_IDS="1"：临时库首个注册用户（pytest_admin，见 client fixture）
即 admin——conftest 保证它第一个注册。
"""

import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

# ---------- env 隔离（必须在任何 app import 之前！） ----------
_TMP = Path(tempfile.mkdtemp(prefix="pytest_app_"))
os.environ["SQLITE_PATH"] = str(_TMP / "sqlite.db")
os.environ["CHROMA_DIR"] = str(_TMP / "chroma")
os.environ["CASES_DIR"] = str(_TMP / "cases")
os.environ["CHECKPOINTS_PATH"] = str(_TMP / "checkpoints.sqlite")
os.environ["TRACE_PATH"] = str(_TMP / "trace.jsonl")
os.environ["ADMIN_USER_IDS"] = "1"
# W9 B 项：限流默认关——套件自身会高频打 chat/register/login（TestClient 同 IP
# 同用户），开了会 429 撞自己。限流逻辑由 tests/test_security.py 单独开覆盖。
os.environ["RATE_LIMIT_ENABLED"] = "false"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # backend/

import pytest  # noqa: E402

# ---------- stub LLM 固定回复（多测试文件共用，禁止各文件复制粘贴） ----------
REQ_FIRST = {
    "project_title": "奶茶店点单小程序",
    "business_type": "餐饮",
    "core_features": ["扫码点单", "会员储值"],
    "target_users": ["顾客", "店员"],
    "mentioned_budget": None,
    "mentioned_deadline": None,
    "missing_info": ["预算范围？", "期望上线时间？"],
    "summary": "为奶茶店做扫码点单小程序，含会员储值。",
}
REQ_FULL = dict(REQ_FIRST, mentioned_budget="8万", mentioned_deadline="两个月",
                missing_info=[])
PLAN = {
    "project_name": "奶茶店点单小程序",
    "business_summary": "为奶茶店提供扫码点单与会员运营能力。",
    "core_business_modules": [
        {"name": "扫码点单", "description": "顾客扫码自助下单", "priority": "P0"},
    ],
    "tech_architecture": "小程序前端 + 云端 API + MySQL。",
    "tech_stack": [
        {"layer": "前端", "choice": "微信小程序", "reason": "免安装"},
        {"layer": "后端", "choice": "Python FastAPI", "reason": "开发快"},
        {"layer": "数据库", "choice": "MySQL", "reason": "事务可靠"},
    ],
    "implementation_phases": ["一期：点单闭环"],
    "key_risks": ["高峰并发"],
}
FEAS = {
    "overall": "可行",
    "risk_level": "低",
    "tech_assessment": "技术栈成熟。",
    "schedule_assessment": "工期可行。",
    "budget_assessment": "预算匹配。",
    "suggestions": ["先上线点单闭环"],
}
# consult 话术同时满足两条旧断言（内部核算 / 商业机密 / 人工审核）
CONSULT_REPLY = (
    "报价构成涉及公司内部核算，属于商业机密，不便透露明细。"
    "可以留下联系方式，专人人工审核后为您解释。"
)


@pytest.fixture(scope="session", autouse=True)
def _init_db():
    """库初始化（autouse：任何测试子集单独跑也保证建表；幂等）。"""
    from app.db.database import init_db

    init_db()
    yield


@pytest.fixture(scope="session", autouse=True)
def _warm_embedding():
    """bge 模型预热（session 一次；快速档含真向量用例，如 test_admin）。

    flaky 根因（2026-09-26 连跑复现定位）：高负载时 SentenceTransformer
    首次懒加载可能失败（OOM/资源饥饿），vectorize_case 按 W9 契约容错
    吞掉（vector_id=None）→ 第一个用 bge 的用例报「assert None」难定位；
    同次跑后续用例重新加载成功全过——纯时机赌博。预热 + 有限重试把
    加载挪到套件启动：失败时报明确错误，成功后进程内无懒加载竞态。
    """
    import time

    from app.infra.model_client import embedding_client

    last: Exception | None = None
    for _ in range(3):
        try:
            embedding_client.embed_query("预热")
            return
        except Exception as e:  # noqa: BLE001 —— 重试后统一报
            last = e
            time.sleep(2)
    raise AssertionError(f"bge embedding 预热失败（重试 3 次均失败）: {last}")


@pytest.fixture(autouse=True)
def _isolate_rate_limits():
    """限流桶状态用例级隔离（W9 收尾防 flaky 防线，autouse 全套件生效）。

    背景：限流记账（内存滑动窗口，带 60s/1h 时间窗）若有用例忘记清，会按
    时间窗泄漏给后续用例——「跑得快就红、跑得慢就绿」的时间赌博。无论
    用例自己写没写清理（rl_on fixture 等），这里前后各清一次兜底。
    """
    from app.services import rate_limit

    rate_limit.reset_rate_limits()
    yield
    rate_limit.reset_rate_limits()


@pytest.fixture(scope="session")
def client():
    """TestClient + 首个用户注册（id=1 = admin，与 ADMIN_USER_IDS 对齐）。"""
    from fastapi.testclient import TestClient

    from app.db.database import init_db
    from app.main import app

    init_db()
    c = TestClient(app)
    r = c.post("/api/auth/register", json={
        "username": "pytest_admin", "password": "pytest_admin_1"})
    assert r.status_code == 201, r.text  # 干净临时库，首个用户必 id=1
    return c


@pytest.fixture(scope="session")
def admin_headers(client):
    """admin（user.id=1）登录态。"""
    r = client.post("/api/auth/login", json={
        "username": "pytest_admin", "password": "pytest_admin_1"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def stub_llm(monkeypatch):
    """stub 掉 chat_client.chat / stream_chat（零 token、确定性）。

    返回可变 state 控制 understand 行为：
        state["understand"] = "full"             一直返回 REQ_FULL（信息齐全）
                              "missing"          一直返回 REQ_FIRST（缺信息）
                              "missing_then_full" 首轮缺、之后全（追问→补全闭环）
    prompt 路由关键词与生产 prompt 文本一一对应（改 prompt 模板需同步这里）：
        understand  「资深的 AI 产品顾问」（understand.txt 独有角色标记；
                     注意必须先于 consult 判断——consult.txt 的「方案顾问」
                     是它的子串）
        feasibility 「可行性评估」
        generate    「core_business_modules」（generate.txt 的 schema 说明）
        consult     「方案顾问」/「商业机密」（consult.txt 指导话术关键词）
    """
    from app.infra import model_client

    state = {"understand": "full"}
    seen = {"n": 0}

    def stub_chat(messages, **kwargs):
        prompt = messages[0]["content"] if messages else ""
        if "资深的 AI 产品顾问" in prompt:
            mode = state["understand"]
            if mode == "missing":
                return json.dumps(REQ_FIRST, ensure_ascii=False)
            if mode == "missing_then_full":
                seen["n"] += 1
                data = REQ_FIRST if seen["n"] == 1 else REQ_FULL
                return json.dumps(data, ensure_ascii=False)
            return json.dumps(REQ_FULL, ensure_ascii=False)
        if "可行性评估" in prompt:
            return json.dumps(FEAS, ensure_ascii=False)
        if "core_business_modules" in prompt:
            return json.dumps(PLAN, ensure_ascii=False)
        if "方案顾问" in prompt or "商业机密" in prompt:
            return CONSULT_REPLY
        return json.dumps(PLAN, ensure_ascii=False)

    def stub_stream(messages, **kwargs):
        # consult_node 走流式；测试关心内容而非分块粒度
        return iter([stub_chat(messages, **kwargs)])

    monkeypatch.setattr(model_client.chat_client, "chat", stub_chat)
    monkeypatch.setattr(model_client.chat_client, "stream_chat", stub_stream)
    return state


@pytest.fixture
def new_thread():
    """直接 invoke 图用的隔离会话配置（thread_id 唯一，不复用 checkpoint）。"""
    return {"configurable": {"thread_id": f"pytest-{uuid.uuid4().hex}"}}


@pytest.fixture
def make_project():
    """工厂：service 层造项目（user_id=None，service 层调用不校验归属）。"""
    from app.db.database import SessionLocal
    from app.services import project_service

    def _make(title: str = "pytest 项目",
              raw_idea: str = "我想给奶茶店做扫码点单小程序，预算8万，两个月上线") -> int:
        db = SessionLocal()
        try:
            return project_service.create_project(db, title, raw_idea).id
        finally:
            db.close()

    return _make
