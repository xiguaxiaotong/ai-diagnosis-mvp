"""generate 节点输出异常分级容错（T-2 回归）——stub LLM 零真钱。

修复前行为（复现脚本 scripts/t2_generate_repro.py）：
- required（必填缺失）/ invalid（非 JSON）→ generate 无重试直接 error，
  plan 缺失 → budget/feasibility 连锁失败 → output 兜底话术，整链无方案。
修复后（app/agent/nodes/generate.py 分级策略）：
- 可选字段缺失 → pydantic 默认值补齐 + warning 留痕，主流程继续；
- 必填缺失 / 非法 JSON → 点名问题重试一次，仍失败才 error 兜底（文案记明）。
"""

import json
import logging

import pytest

from app.agent.nodes.generate import generate_node
from app.agent.schemas import SolutionPlan

REQ = {
    "project_title": "进销存管理系统",
    "business_type": "零售/批发",
    "core_features": ["商品管理", "采购进货", "销售出货"],
    "target_users": ["老板", "仓管"],
    "mentioned_budget": "3万",
    "mentioned_deadline": "两个月",
    "missing_info": [],
    "summary": "3万做进销存，两人用，电脑网页。",
}

GOOD_PLAN = {
    "project_name": "进销存管理系统",
    "one_liner": "把进货卖货库存放到电脑上管。",
    "business_summary": "3万预算内的轻量进销存。",
    "core_business_modules": [
        {"name": "商品管理", "description": "商品档案登记", "priority": "P0"},
        {"name": "采购进货", "description": "进货单录入", "priority": "P0"},
        {"name": "销售出货", "description": "销售开单", "priority": "P0"},
    ],
    "tech_architecture": "网页 + FastAPI + MySQL。",
    "tech_stack": [
        {"layer": "前端", "choice": "Vue", "reason": "轻量"},
        {"layer": "后端", "choice": "FastAPI", "reason": "快"},
    ],
    "glossary": [],
    "implementation_phases": ["一期：商品+进销闭环"],
    "key_risks": ["数据迁移"],
}


@pytest.fixture
def generate_llm(monkeypatch):
    """可控 generate stub：queue 依次出队（空了出完好方案）。

    返回 {"prompts": 收到的 prompt 列表, "queue": 坏输出队列}。
    只关心 generate 路由（prompt 含 core_business_modules）。
    """
    from app.infra import model_client

    state = {"prompts": [], "queue": []}

    def stub_chat(messages, **kwargs):
        prompt = messages[0]["content"] if messages else ""
        state["prompts"].append(prompt)
        if "core_business_modules" in prompt:
            return (state["queue"].pop(0) if state["queue"]
                    else json.dumps(GOOD_PLAN, ensure_ascii=False))
        return json.dumps(GOOD_PLAN, ensure_ascii=False)

    monkeypatch.setattr(model_client.chat_client, "chat", stub_chat)
    return state


def _drop_optional() -> str:
    plan = json.loads(json.dumps(GOOD_PLAN))
    plan.pop("one_liner")
    plan.pop("glossary")
    for m in plan["core_business_modules"]:
        m.pop("example", None)  # GOOD_PLAN 本不带 example，确保此键确实缺失
    return json.dumps(plan, ensure_ascii=False)


def _drop_priority() -> str:
    plan = json.loads(json.dumps(GOOD_PLAN))
    for m in plan["core_business_modules"]:
        m.pop("priority")  # T-1 定位时真实触发的缺字段
    return json.dumps(plan, ensure_ascii=False)


# ---------- 可选字段缺失：默认值补齐，主流程继续 ----------

def test_optional_missing_fills_defaults(generate_llm, caplog):
    generate_llm["queue"] = [_drop_optional()]
    with caplog.at_level(logging.WARNING):
        delta = generate_node({"requirements": REQ})

    assert not delta.get("error"), f"可选缺失不得报错: {delta.get('error')}"
    plan = SolutionPlan.model_validate(delta["plan"])
    assert plan.one_liner == "", "one_liner 应补默认空串"
    assert plan.glossary == [], "glossary 应补默认空列表"
    assert len(generate_llm["prompts"]) == 1, "可选缺失不触发重试"
    # 注：caplog 能抓到 app.* 日志的前提是 alembic env.py 用
    # disable_existing_loggers=False（旧默认 True 会禁用收集期注册的 logger）
    assert any("已按默认值补齐" in r.getMessage() for r in caplog.records), "补齐行为应留 warning 痕"


# ---------- 必填字段缺失：点名重试一次 ----------

def test_required_missing_retries_once(generate_llm):
    generate_llm["queue"] = [_drop_priority()]
    delta = generate_node({"requirements": REQ})

    assert not delta.get("error"), f"重试后应恢复: {delta.get('error')}"
    SolutionPlan.model_validate(delta["plan"])
    assert len(generate_llm["prompts"]) == 2, "应恰好重试一次"
    retry_prompt = generate_llm["prompts"][1]
    assert "core_business_modules[].priority" in retry_prompt, "重试 prompt 必须点名缺失字段"


def test_required_missing_retry_also_fails(generate_llm):
    generate_llm["queue"] = [_drop_priority(), _drop_priority()]
    delta = generate_node({"requirements": REQ})

    assert delta.get("error"), "两次都缺必填应走 error 兜底"
    assert "重试后仍缺" in delta["error"], f"文案应记明重试后仍缺: {delta['error']}"
    assert "priority" in delta["error"], "缺失字段名要在文案里"
    assert len(generate_llm["prompts"]) == 2, "不无限重试"


# ---------- 非法 JSON：同路重试一次 ----------

def test_invalid_json_retries_once(generate_llm):
    generate_llm["queue"] = ["抱歉，我还需要更多信息……这里不是 JSON"]
    delta = generate_node({"requirements": REQ})

    assert not delta.get("error"), f"非法 JSON 重试后应恢复: {delta.get('error')}"
    SolutionPlan.model_validate(delta["plan"])
    assert len(generate_llm["prompts"]) == 2
    assert "不是合法 JSON" in generate_llm["prompts"][1], "重试 prompt 应点名 JSON 问题"


def test_invalid_json_retry_also_fails(generate_llm):
    generate_llm["queue"] = ["完全不是 JSON", "还是不是 JSON"]
    delta = generate_node({"requirements": REQ})

    assert delta.get("error"), "两次非法 JSON 应走 error 兜底"
    assert "不是合法 JSON" in delta["error"], f"文案应记明 JSON 问题: {delta['error']}"


# ---------- 正常路径不受影响（回归保护） ----------

def test_good_plan_unchanged(generate_llm):
    delta = generate_node({"requirements": REQ})

    assert not delta.get("error")
    plan = SolutionPlan.model_validate(delta["plan"])
    assert len(generate_llm["prompts"]) == 1, "合格输出不重试"
    assert plan.project_name == "进销存管理系统"
