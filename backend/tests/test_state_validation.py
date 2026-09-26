"""W9 Day1：状态层 pydantic 化（子状态校验）测试。

对照（旧→新）：
- 旧：无状态校验层，节点返回什么就合并什么（大字典裸奔）
- 新：validate_update() 按三个子状态模型校验增量；
  挂在 traced() 包装器（trace.py），校验失败记 trace + 日志不 raise

覆盖：
1. 合法增量（含嵌套 requirements→ProjectRequirements 重验）→ 通过
2. requirements 非法（缺必填）→ [requirement] 分组报错
3. clarify_round 类型错 → [interaction] 分组报错
4. 顶层容器字段（messages 非法）→ [top] 分组报错
5. 未声明键 → 放行（观察期不加新门）
6. traced() 集成：节点输出校验失败 → 主流程照常返回、不 raise
"""

import json

from app.agent.state import validate_update
from app.agent.trace import traced


def _valid_requirements() -> dict:
    return {
        "project_title": "奶茶店点单小程序",
        "business_type": "餐饮",
        "core_features": ["扫码点单"],
        "target_users": ["顾客"],
        "missing_info": [],
        "summary": "为奶茶店做扫码点单小程序。",
    }


def test_valid_update_passes():
    """合法增量：需求 + 交互 + 顶层三组全过（嵌套模型连带重验）。"""
    errs = validate_update({
        "requirements": _valid_requirements(),
        "budget_tier": {"tier": "mid", "label": "轻量生产版",
                        "mentioned": "8千", "amount": 8000,
                        "guidance": "...", "recap": "..."},
        "confirmed_pain_points": ["人工记账麻烦"],
        "clarify_round": 2,
        "needs_clarify": True,
        "decision": "revised",
        "messages": [{"role": "user", "content": "hi"}],
        "project_id": 1,
    })
    assert errs == []


def test_bad_requirements_reports_requirement_group():
    errs = validate_update({"requirements": {"bad": 1}})
    assert len(errs) == 1
    assert errs[0].startswith("[requirement]")
    assert "project_title" in errs[0]


def test_bad_clarify_round_reports_interaction_group():
    errs = validate_update({"clarify_round": "不是数字"})
    assert len(errs) == 1
    assert errs[0].startswith("[interaction]")


def test_bad_messages_reports_top_group():
    errs = validate_update({"messages": "不是列表"})
    assert len(errs) == 1
    assert errs[0].startswith("[top]")


def test_unknown_key_ignored():
    """未声明的键放行（观察期不加新门）。"""
    assert validate_update({"some_future_key": object()}) == []


def test_traced_wrapper_does_not_raise_on_invalid_output(tmp_path, monkeypatch):
    """集成：校验失败只记 trace + 日志，节点输出照常返回主流程。"""
    trace_file = tmp_path / "trace.jsonl"
    monkeypatch.setattr("app.agent.trace.TRACE_PATH", trace_file)

    def bad_node(state):
        return {"clarify_round": "坏数据", "intent": "requirement"}

    wrapped = traced("bad_node", bad_node)
    out = wrapped({"messages": []}, {"configurable": {"thread_id": "pytest-w9d1"}})
    # 主流程不受影响：输出原样返回
    assert out == {"clarify_round": "坏数据", "intent": "requirement"}

    # trace 落盘带 state_errors 字段
    rec = json.loads(trace_file.read_text(encoding="utf-8").strip())
    assert rec["node"] == "bad_node"
    assert rec["thread_id"] == "pytest-w9d1"
    assert any(e.startswith("[interaction]") for e in rec["state_errors"])


def test_traced_wrapper_no_state_errors_on_valid_output(tmp_path, monkeypatch):
    """集成：合法输出 trace 里不带 state_errors 键（不污染正常记录）。"""
    trace_file = tmp_path / "trace.jsonl"
    monkeypatch.setattr("app.agent.trace.TRACE_PATH", trace_file)

    def good_node(state):
        return {"clarify_round": 1}

    wrapped = traced("good_node", good_node)
    out = wrapped({"messages": []}, None)
    assert out == {"clarify_round": 1}

    rec = json.loads(trace_file.read_text(encoding="utf-8").strip())
    assert "state_errors" not in rec
