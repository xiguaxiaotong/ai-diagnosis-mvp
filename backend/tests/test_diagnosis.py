"""诊断图核心链路 —— 收编自 test_w2d1~w2d5 / test_w3d2 / test_w3d3(在线) /
test_w5d3 / test_w5d4 / test_confirm_fix。

全部 stub LLM（见 conftest.stub_llm），零 token、确定性。
图直调用 new_thread fixture（thread_id 唯一，checkpoint 天然隔离）；
服务层流程用 chat_turn（走全局图，CHECKPOINTS_PATH 已指临时文件）。
"""

import json

from langgraph.types import Command

from app.agent.graph import diagnosis_graph
from app.agent.schemas import ProjectRequirements, SolutionPlan
from app.services.diagnosis_service import chat_turn

IDEA = "我想给奶茶店做扫码点单小程序"
ANSWER = "预算8万，两个月上线，堂食为主"


def _invoke_idea(cfg, idea: str = IDEA):
    return diagnosis_graph.invoke(
        {"raw_idea": idea, "messages": [{"role": "user", "content": idea}]}, cfg)


# ---------- w2d1：understand 节点输出结构 ----------

def test_understand_node_missing(stub_llm):
    from app.agent.nodes.understand import understand_node

    stub_llm["understand"] = "missing"
    delta = understand_node({"raw_idea": IDEA,
                             "messages": [{"role": "user", "content": IDEA}],
                             "clarify_round": 0})
    req = ProjectRequirements.model_validate(delta["requirements"])
    assert delta["needs_clarify"] is True
    assert delta["clarify_questions"] == req.missing_info[:3]
    assert delta["clarify_round"] == 1


def test_understand_node_full(stub_llm):
    from app.agent.nodes.understand import understand_node

    stub_llm["understand"] = "full"
    delta = understand_node({"raw_idea": IDEA,
                             "messages": [{"role": "user", "content": IDEA}],
                             "clarify_round": 0})
    ProjectRequirements.model_validate(delta["requirements"])
    assert delta["needs_clarify"] is False
    assert delta["clarify_questions"] == []


# ---------- w2d2：interrupt 追问 → resume → 补全出方案 ----------

def test_clarify_interrupt_and_resume(stub_llm, new_thread):
    stub_llm["understand"] = "missing_then_full"

    state = _invoke_idea(new_thread)
    snap = diagnosis_graph.get_state(new_thread)
    assert "wait_input" in snap.next, f"应停在追问等待: {snap.next}"
    assert state["needs_clarify"] is True
    assert state["clarify_questions"], "追问问题非空"
    assert state["messages"][-1]["role"] == "assistant"

    state = diagnosis_graph.invoke(Command(resume=ANSWER), new_thread)
    snap2 = diagnosis_graph.get_state(new_thread)
    assert "wait_confirmation" in snap2.next, f"信息补全后应出方案: {snap2.next}"
    assert state["needs_clarify"] is False
    assert state["requirements"]["core_features"], "抽取的核心功能非空"
    assert state.get("plan"), "应已生成方案"


# ---------- w2d3：追问循环上限（5 轮强制结束） ----------

def test_max_clarify_rounds_force_finish(stub_llm, new_thread):
    stub_llm["understand"] = "missing"

    _invoke_idea(new_thread)
    for i in range(4):  # 共 5 轮 understand
        diagnosis_graph.invoke(Command(resume=f"第{i + 2}轮补充：还是缺信息"), new_thread)
    snap = diagnosis_graph.get_state(new_thread)
    v = snap.values
    assert v["clarify_round"] == 5, f"应到最大轮次: {v['clarify_round']}"
    assert v.get("clarify_exhausted") is True, "应标记强制结束"
    assert "wait_confirmation" in snap.next, "强制路径应照样出方案（初步方案）"
    assert v.get("plan"), "force_finish 后必须仍走 generate 出方案"


# ---------- w2d4/w2d5：方案结构校验 ----------

def test_plan_structure(stub_llm, new_thread):
    stub_llm["understand"] = "full"
    _invoke_idea(new_thread)
    v = diagnosis_graph.get_state(new_thread).values
    plan = SolutionPlan.model_validate(v["plan"])
    assert plan.core_business_modules, "业务模块非空"
    priorities = {m.priority for m in plan.core_business_modules}
    assert priorities <= {"P0", "P1", "P2"}
    assert "P0" in priorities, "必须有 P0 核心模块"
    assert plan.tech_stack, "技术选型非空"


# ---------- w3d2：full_solution 五键 + 可行性枚举 + DB 持久化 ----------

def test_full_solution_and_persistence(stub_llm, make_project):
    from app.db.database import SessionLocal
    from app.db.models import Project

    stub_llm["understand"] = "missing_then_full"
    pid = make_project()

    r1 = chat_turn(pid, IDEA)
    assert r1["phase"] == "clarify", r1["phase"]
    r2 = chat_turn(pid, ANSWER)
    assert r2["phase"] == "confirm_wait", r2["phase"]

    sol = r2["solution"]
    for key in ("requirements", "plan", "budget", "feasibility", "final_output"):
        assert key in sol, f"full_solution 缺 {key}"
    feas = sol["feasibility"]
    assert feas["overall"] in ("可行", "有条件可行", "风险较高")
    assert feas["risk_level"] in ("低", "中", "高")

    db = SessionLocal()
    try:
        p = db.get(Project, pid)
        assert p.status == Project.STATUS_PLAN_GENERATED
        plan_db = json.loads(p.plan)
        # p.plan 存的是 full_solution（requirements/plan/budget/feasibility 全量）
        assert "core_business_modules" in plan_db["plan"]
        assert p.budget_min > 0 and p.budget_max >= p.budget_min
    finally:
        db.close()


# ---------- confirm_fix：thread_id / 修改轮次 / 满轮收尾 / 主动确认 ----------

def _run_to_plan(stub_llm, pid: int) -> None:
    stub_llm["understand"] = "missing_then_full"
    r = chat_turn(pid, IDEA)
    assert r["phase"] == "clarify", r["phase"]
    r = chat_turn(pid, ANSWER)
    assert r["phase"] == "confirm_wait", r["phase"]
    assert "（已按您的要求修改" not in r["reply"], "首轮方案不应带修改轮次后缀"


def test_thread_id_is_uuid(stub_llm, make_project):
    from app.db.database import SessionLocal
    from app.db.models import Project

    pid = make_project()
    chat_turn(pid, IDEA)  # 触发 _config 懒初始化 thread_id
    db = SessionLocal()
    try:
        tid = db.get(Project, pid).thread_id
    finally:
        db.close()
    # uuid4 hex（32 位十六进制）——不能用「不含 pid 字符串」判法（干净库 pid=1
    # 与 uuid 字符冲突，旧断言必误报；见 Day7 commit 对照）
    assert tid and len(tid) == 32 and all(c in "0123456789abcdef" for c in tid), tid


def test_revision_rounds_and_maxed_finalize(stub_llm, make_project):
    pid = make_project()
    _run_to_plan(stub_llm, pid)

    for i in range(1, 4):
        r = chat_turn(pid, f"第{i}次修改：去掉会员储值")
        assert r["phase"] == "confirm_wait", f"第{i}轮修改后仍应等确认: {r['phase']}"
        assert f"第 {i}/3 轮" in r["reply"], f"第{i}轮后缀缺失: {r['reply'][-40:]}"

    r = chat_turn(pid, "第4次修改：再砍点功能")
    assert r["phase"] == "done", "满轮后应强制收尾"
    assert "已经按您的意见修改了" in r["reply"], "满轮收尾话术错误"
    assert "方案已确认" not in r["reply"], "满轮收尾不得冒充用户确认"


def test_confirm_reply_and_status(stub_llm, make_project):
    from app.db.database import SessionLocal
    from app.db.models import Project

    pid = make_project()
    _run_to_plan(stub_llm, pid)
    r = chat_turn(pid, "确认，就这样")
    assert r["phase"] == "done", r["phase"]
    assert "方案已确认" in r["reply"]
    assert len(r["reply"]) < 200, "确认话术应短（不重复整段方案）"

    db = SessionLocal()
    try:
        assert db.get(Project, pid).status == Project.STATUS_CONFIRMED
    finally:
        db.close()
