"""W8 Day1 验收：节点级 Trace 中间层。

⚠️ 测试隔离：env 覆盖五路径（四路径 + TRACE_PATH），独立临时库，不碰主库、
不碰主 trace 文件。

stub 策略：与旧测试直接换 chat_client.chat 不同，这里 stub 挂在
OpenAI client 层（chat_client._client = FakeOpenAI()），让真实的
chat() / stream_chat() 执行——trace 的 LLM 层 hook 在这两个方法内部，
必须走真路径才能验收「LLM 调用单独记录」这层。

验证点：
- [1] 跑一次完整诊断（→确认收尾）：trace.jsonl 生成，thread_id 正确
- [2] 节点记录覆盖全程全部节点（route_intent→understand→retrieve→
      generate→budget→feasibility→output→wait_confirmation→finalize）
- [3] 每条节点记录字段完整：开始/耗时/输入摘要/输出摘要/llm_calls/tokens
- [4] LLM 层记录：模型名/prompt tokens/completion tokens/耗时/输入输出摘要，
      且 token 累加进了对应节点记录（understand/generate/feasibility ≥1 次调用）
- [5] interrupt（wait_input/wait_confirmation）不算错误，标记 interrupted
- [6] trace 写入失败不影响主流程：TRACE_PATH 指向非法路径后再跑一轮，
      诊断照常出结果
- [7] admin 接口 GET /api/admin/trace/{thread_id}：返回完整链（node/llm 计数），
      裸 uuid 与 project- 前缀两种写法等价；非 admin 403

用法（在 backend/ 下，零真 LLM token）：
    python scripts/test_w8d1_trace.py
"""
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

# ---------- 测试隔离：env 必须在 import app 之前设置 ----------
_TMP = Path(tempfile.mkdtemp(prefix="w8d1_trace_"))
os.environ["SQLITE_PATH"] = str(_TMP / "sqlite.db")
os.environ["CHROMA_DIR"] = str(_TMP / "chroma")
os.environ["CASES_DIR"] = str(_TMP / "cases")
os.environ["CHECKPOINTS_PATH"] = str(_TMP / "checkpoints.sqlite")
os.environ["TRACE_PATH"] = str(_TMP / "trace.jsonl")
os.environ["ADMIN_USER_IDS"] = "1"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.infra import model_client  # noqa: E402

UNDERSTAND_JSON = {
    "project_title": "团购小程序", "business_type": "社区零售",
    "core_features": ["接龙", "订单"], "target_users": ["团长"],
    "mentioned_budget": "10万", "mentioned_deadline": "2个月",
    "missing_info": [], "summary": "社区团购",
}
GENERATE_JSON = {
    "project_name": "团购小程序", "business_summary": "社区团购接龙",
    "core_business_modules": [
        {"name": "接龙", "description": "发起与参与接龙", "priority": "P0"},
        {"name": "订单", "description": "订单管理", "priority": "P0"},
    ],
    "tech_architecture": "小程序+后端",
    "tech_stack": [{"layer": "前端", "choice": "微信小程序", "reason": "用户习惯"}],
    "implementation_phases": ["一期核心"], "key_risks": ["需求变更"],
}
FEASIBILITY_JSON = {
    "overall": "可行", "risk_level": "低", "tech_assessment": "常规方案成熟",
    "schedule_assessment": "2个月可交付", "budget_assessment": "预算充足",
    "suggestions": ["先做核心模块"],
}


def _fake_reply(messages):
    """按 prompt 关键词返回 stub 回复（对齐旧测试的 fake_chat 分支）。"""
    prompt = messages[0]["content"] if messages else ""
    if "可行性评估" in prompt:
        return json.dumps(FEASIBILITY_JSON, ensure_ascii=False)
    if "P0=没有就没法上线" in prompt:
        return json.dumps(GENERATE_JSON, ensure_ascii=False)
    return json.dumps(UNDERSTAND_JSON, ensure_ascii=False)


class FakeCompletions:
    """OpenAI chat.completions 替身：非流式返回整体回复 + usage；流式切 3 段。"""

    def create(self, model, messages, temperature=None, stream=False, **kwargs):
        content = _fake_reply(messages)
        if not stream:
            usage = SimpleNamespace(prompt_tokens=120, completion_tokens=60)
            return SimpleNamespace(
                usage=usage,
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            )
        # 流式：3 个内容事件 + 1 个收尾 usage 事件（对齐 include_usage 协议）
        parts = [content[i:i + max(1, len(content) // 3)] for i in
                 range(0, len(content), max(1, len(content) // 3))][:3]
        events = [
            SimpleNamespace(usage=None,
                            choices=[SimpleNamespace(delta=SimpleNamespace(content=p))])
            for p in parts
        ]
        events.append(SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=120, completion_tokens=60),
            choices=[SimpleNamespace(delta=SimpleNamespace(content=""))],
        ))
        return iter(events)


# stub 挂 client 层：真实 chat()/stream_chat() 照跑（trace LLM 层才会触发）
model_client.chat_client._client = SimpleNamespace(
    chat=SimpleNamespace(completions=FakeCompletions()))

from fastapi.testclient import TestClient  # noqa: E402

from app.agent import trace as trace_mod  # noqa: E402
from app.config import TRACE_PATH  # noqa: E402
from app.db.database import SessionLocal, init_db  # noqa: E402
from app.db.models import Project  # noqa: E402
from app.main import app  # noqa: E402
from app.services import project_service  # noqa: E402
from app.services.diagnosis_service import chat_turn  # noqa: E402

PASS, FAIL = 0, 0


def check(name: str, ok: bool, detail: str = ""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}  {detail}")


def _load_trace() -> list[dict]:
    with open(TRACE_PATH, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _thread_of(project_id: int) -> str:
    """项目 → thread uuid（图内键 = project-<uuid>）。"""
    db = SessionLocal()
    try:
        return db.get(Project, project_id).thread_id
    finally:
        db.close()


def main():
    init_db()

    # ---- [1] 完整诊断：出方案 → 确认 ----
    print("[1] 跑完整诊断（stub 挂 OpenAI client 层，真 chat() 执行）")
    db = SessionLocal()
    p = project_service.create_project(db, title="trace 验证", raw_idea="占位")
    pid = p.id
    db.close()

    r1 = chat_turn(pid, "我想做个社区团购接龙小程序，预算10万，2个月上线")
    assert r1["phase"] == "confirm_wait", f"应到确认环节: {r1['phase']}"
    r2 = chat_turn(pid, "确认，就这样")
    assert r2["phase"] == "done", f"确认后应结束: {r2['phase']}"

    db = SessionLocal()
    thread_uuid = db.get(Project, pid).thread_id
    db.close()
    thread_key = f"project-{thread_uuid}"

    check("诊断跑通（出方案 + 确认）", True)
    check("trace.jsonl 已生成", TRACE_PATH.exists())

    records = _load_trace()
    node_recs = [r for r in records if r["type"] == "node"]
    llm_recs = [r for r in records if r["type"] == "llm"]
    check("thread_id 全部正确", all(r["thread_id"] == thread_key for r in records),
          f"期望 {thread_key}")

    # ---- [2] 节点覆盖 ----
    print("\n[2] 节点覆盖")
    covered = {r["node"] for r in node_recs}
    # 直确认路径全部节点（确认 → ROUTE_CONFIRMED → END，不经过 finalize）
    must_cover = {"route_intent", "understand", "retrieve", "generate", "budget",
                  "feasibility", "output", "wait_confirmation"}
    missing = must_cover - covered
    check(f"直确认路径节点全覆盖（缺: {missing or '无'}）", not missing,
          f"实际覆盖 {sorted(covered)}")
    order = [r["node"] for r in node_recs]
    check("首节点 route_intent", order[0] == "route_intent", str(order[:3]))

    # ---- [2b] 满轮路径：修改 3 轮 → finalize 强制收尾 ----
    print("\n[2b] 满轮路径（覆盖 revise + finalize）")
    pid3 = project_service.create_project(
        SessionLocal(), title="trace 满轮验证", raw_idea="占位3").id
    r = chat_turn(pid3, "我想做个社区团购接龙小程序，预算10万，2个月上线")
    assert r["phase"] == "confirm_wait"
    for i in range(3):
        r = chat_turn(pid3, "再改改，把订单模块简化一下")
        assert r["phase"] == "confirm_wait", f"第{i+1}轮修改后应仍在确认: {r['phase']}"
    r = chat_turn(pid3, "还想再改")
    assert r["phase"] == "done", f"满轮后应强制收尾: {r['phase']}"
    records = _load_trace()
    covered3 = {rec["node"] for rec in records
                if rec["type"] == "node" and rec["thread_id"] == f"project-{_thread_of(pid3)}"}
    check("满轮路径覆盖 revise + finalize",
          {"revise", "finalize"} <= covered3, f"实际 {sorted(covered3)}")
    fin = next(rec for rec in records
               if rec["type"] == "node" and rec["node"] == "finalize"
               and rec["thread_id"] == f"project-{_thread_of(pid3)}")
    check("[finalize] 字段完整且无错误", "error" not in fin and fin["llm_calls"] >= 0)

    # ---- [3] 节点记录字段 ----
    print("\n[3] 节点记录字段")
    for r in node_recs:
        start_ok = False
        try:  # start 必须是真实 epoch 时刻（曾错用 perf_counter 得 1970+开机时长）
            start_ok = datetime.fromisoformat(r.get("start", "")).year > 2020
        except Exception:
            pass
        check(f"[{r['node']}] 字段完整", all([
            isinstance(r.get("duration_ms"), int) and r["duration_ms"] >= 0,
            isinstance(r.get("input_summary"), str),
            isinstance(r.get("output_summary"), str),
            start_ok,
            "ts" in r,
            isinstance(r.get("llm_calls"), int),
            isinstance(r.get("tokens"), dict),
        ]), json.dumps(r, ensure_ascii=False)[:160])
        if r.get("error"):
            check(f"[{r['node']}] 无错误标记", False, r["error"])

    # ---- [4] LLM 层记录 ----
    print("\n[4] LLM 层记录")
    check("存在 llm 记录", len(llm_recs) > 0)
    check("llm 记录带模型名", all(r.get("model") for r in llm_recs))
    check("llm 记录带 prompt/completion tokens",
          all(r.get("prompt_tokens") and r.get("completion_tokens") for r in llm_recs),
          json.dumps(llm_recs[0], ensure_ascii=False)[:200] if llm_recs else "无")
    check("llm 记录带耗时/输入/输出摘要",
          all(r.get("duration_ms") >= 0 and r.get("input_summary")
              and r.get("output_summary") for r in llm_recs))
    check("llm 记录挂了所属节点", all(r.get("node") for r in llm_recs))
    # token 累加进节点汇总（understand/generate/feasibility 走真 chat()）
    for node_name in ("understand", "generate", "feasibility"):
        rec = next(r for r in node_recs if r["node"] == node_name)
        check(f"[{node_name}] llm_calls ≥1 且 tokens>0",
              rec["llm_calls"] >= 1 and rec["tokens"]["prompt"] > 0,
              json.dumps(rec["tokens"]))
    budget_rec = next(r for r in node_recs if r["node"] == "budget")
    check("[budget] 纯计算节点 0 次 LLM（token 归属正确）",
          budget_rec["llm_calls"] == 0, str(budget_rec["llm_calls"]))

    # ---- [5] interrupt 不算错误 ----
    print("\n[5] interrupt 标记")
    wc = [r for r in node_recs if r["node"] == "wait_confirmation"]
    check("wait_confirmation 有 interrupted 标记且无 error",
          any(r.get("interrupted") for r in wc)
          and all(not r.get("error") for r in wc), str(wc)[:200])

    # ---- [6] 写入失败不影响主流程 ----
    print("\n[6] trace 写入失败兜底")
    blocker = _TMP / "blocker.txt"
    blocker.write_text("x", encoding="utf-8")
    saved = trace_mod.TRACE_PATH
    trace_mod.TRACE_PATH = blocker / "trace.jsonl"  # 父路径是文件 → mkdir 必败
    try:
        pid2 = project_service.create_project(
            SessionLocal(), title="写入失败兜底", raw_idea="占位2").id
        r3 = chat_turn(pid2, "我想做个社区团购接龙小程序，预算10万，2个月上线")
        check("trace 挂了诊断照常出方案", r3["phase"] == "confirm_wait",
              f"实际 {r3['phase']}")
    finally:
        trace_mod.TRACE_PATH = saved

    # ---- [7] admin 接口 ----
    print("\n[7] admin 查询接口")
    client = TestClient(app)
    r = client.post("/api/auth/register", json={
        "username": "trace_admin", "password": "tracepass123"})
    assert r.status_code == 201, r.text
    r = client.post("/api/auth/login", json={
        "username": "trace_admin", "password": "tracepass123"})
    admin_h = {"Authorization": "Bearer " + r.json()["token"]}
    r = client.post("/api/auth/register", json={
        "username": "trace_user", "password": "tracepass456"})
    r = client.post("/api/auth/login", json={
        "username": "trace_user", "password": "tracepass456"})
    user_h = {"Authorization": "Bearer " + r.json()["token"]}

    r = client.get(f"/api/admin/trace/{thread_key}", headers=admin_h)
    check("GET /api/admin/trace/{thread_key} 200", r.status_code == 200, r.text[:200])
    s = r.json()
    # 注意口径：接口查的是会话 1（thread_key），文件里还有满轮场景的记录，
    # 必须按 thread_id 过滤后比对
    s1_records = [r_ for r_ in records if r_["thread_id"] == thread_key]
    check("返回本会话全部记录", s["count"] == len(s1_records),
          f"接口 {s['count']} vs 文件(该会话) {len(s1_records)}")
    check("node/llm 计数正确",
          s["node_count"] == sum(1 for r_ in s1_records if r_["type"] == "node")
          and s["llm_count"] == sum(1 for r_ in s1_records if r_["type"] == "llm"))
    check("裸 uuid 等价（自动补 project- 前缀）",
          client.get(f"/api/admin/trace/{thread_uuid}", headers=admin_h
                     ).json()["count"] == len(s1_records))
    r = client.get(f"/api/admin/trace/{thread_uuid}", headers=user_h)
    check("非 admin 403", r.status_code == 403, f"实际 {r.status_code}")
    r = client.get(f"/api/admin/trace/{thread_uuid}")
    check("未登录 401/403", r.status_code in (401, 403), f"实际 {r.status_code}")

    # 时序完整性：记录 ts 单调（追加序 = 时间序）
    ts_list = [r["ts"] for r in records]
    check("记录时间序单调", ts_list == sorted(ts_list))

    # 清理测试项目（临时库，留着也无害，但保持整洁）
    db = SessionLocal()
    db.query(Project).filter(Project.id.in_([pid, pid2, pid3])).delete(
        synchronize_session=False)
    db.commit()
    db.close()

    print(f"\n{'='*50}\n结果：{PASS} 通过 / {FAIL} 失败 · 测试库：{_TMP}")
    print(f"trace 样本：{TRACE_PATH}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
