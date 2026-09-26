"""咨询分流 —— 收编自 test_consult_graph.py / test_consult_confirm_stage.py。

核心回归：咨询（问价/闲聊）不得触发重新生成方案（曾因误判答非所问+烧钱修复），
确认环节的咨询不得消耗修改轮次。
"""

from app.agent.graph import diagnosis_graph
from app.services.diagnosis_service import _config, chat_turn


def _state(pid: int) -> dict:
    return diagnosis_graph.get_state(_config(pid)).values


# ---------- consult_graph：追问阶段咨询不消耗轮次 ----------

def test_consult_first_message(stub_llm, make_project):
    """首条消息就是咨询 → 走 consult，不推进追问轮次。"""
    pid = make_project()
    r1 = chat_turn(pid, "你们是怎么收费的？")
    assert r1["phase"] == "clarify", r1["phase"]
    assert "内部核算" in r1["reply"], r1["reply"][:80]
    st = _state(pid)
    assert st.get("clarify_round", 0) == 0, "咨询不该消耗追问轮次"
    assert st.get("intent") == "consult"


def test_requirement_after_consult(stub_llm, make_project):
    """咨询后给需求 → 正常进 understand。"""
    stub_llm["understand"] = "missing"
    pid = make_project()
    chat_turn(pid, "你们是怎么收费的？")
    r2 = chat_turn(pid, "我想给小区做个团购接龙小程序，300人用")
    st2 = _state(pid)
    assert r2["phase"] == "clarify" and st2.get("clarify_round") == 1
    assert st2.get("intent") == "requirement"


def test_consult_mid_clarify(stub_llm, make_project):
    """追问中夹咨询 → 仍走 consult，轮次不变。"""
    stub_llm["understand"] = "missing"
    pid = make_project()
    chat_turn(pid, "我想给小区做个团购接龙小程序，300人用")
    r3 = chat_turn(pid, "为什么你们比别家贵")
    st3 = _state(pid)
    assert "内部核算" in r3["reply"] and st3.get("clarify_round") == 1


# ---------- consult_confirm_stage：确认环节咨询不打断确认循环 ----------

def test_consult_during_confirm(stub_llm, make_project):
    """方案出来后问报价构成 → 走 consult，不触发 revise。"""
    stub_llm["understand"] = "full"
    pid = make_project()
    r1 = chat_turn(pid, "我想做个社区团购接龙小程序，预算10万，2个月上线")
    assert r1["phase"] == "confirm_wait", r1["phase"]

    r2 = chat_turn(pid, "具体是怎么组成报价的")
    assert r2["phase"] == "confirm_wait", "咨询后应仍停在确认环节"
    assert "商业机密" in r2["reply"] or "人工审核" in r2["reply"], r2["reply"][:80]
    st = _state(pid)
    assert st.get("revision_round", 0) == 0, "咨询不该消耗修改轮次"
    assert st.get("decision") == "consult"


def test_confirm_after_consult(stub_llm, make_project):
    """咨询后继续正常确认 → 流程不受影响。"""
    stub_llm["understand"] = "full"
    pid = make_project()
    chat_turn(pid, "我想做个社区团购接龙小程序，预算10万，2个月上线")
    chat_turn(pid, "具体是怎么组成报价的")
    r3 = chat_turn(pid, "确认，就这样")
    assert _state(pid).get("decision") == "confirmed"
    assert r3["phase"] == "done"
