"""预算测算（规则引擎）—— 收编自 scripts/test_w3d1.py + test_budget_constraint.py。

全部纯函数，零 LLM 零 DB。T-1（budget_constraint 场景4 xfail）已于 W9 关闭：
根因 = budget 节点 corpus 全量扫 requirements.values()，把交互脚手架
（question_details 未选中的示例选项/问题原文）、summary 否定句、产品域词
「进销存」当成计价信号，虚增集成加价；8e759df 话术断言未同步只是表因。
定位/修复/验证全程见 scripts/t1_budget_trace.py 与 backend/docs/TODO.md T-1。
"""

import pytest

from app.agent.nodes.budget import estimate_budget, parse_budget


def make_plan() -> dict:
    """固定测试方案：3 P0 + 2 P1 + 1 P2，含收银对接 + 小程序。"""
    return {
        "project_name": "连锁点单小程序",
        "business_summary": "为连锁餐饮提供扫码点单与订单管理",
        "core_business_modules": [
            {"name": "扫码点单", "description": "顾客扫码下单", "priority": "P0"},
            {"name": "订单管理", "description": "店员处理订单", "priority": "P0"},
            {"name": "核销管理", "description": "到店核销", "priority": "P0"},
            {"name": "会员储值", "description": "储值与会员权益", "priority": "P1"},
            {"name": "经营报表", "description": "基础营业统计", "priority": "P1"},
            {"name": "营销活动", "description": "优惠券活动", "priority": "P2"},
        ],
        "tech_architecture": "小程序 + FastAPI + MySQL",
        "tech_stack": [
            {"layer": "前端", "choice": "微信小程序", "reason": "餐饮场景标准选择"},
            {"layer": "后端", "choice": "FastAPI", "reason": "开发效率高"},
            {"layer": "数据库", "choice": "MySQL", "reason": "事务可靠"},
            {"layer": "部署", "choice": "云服务器", "reason": "成本可控"},
        ],
        "implementation_phases": ["一期：点单与订单", "二期：会员与营销"],
        "key_risks": ["收银系统对接兼容性"],
    }


# ---------- w3d1：estimate_budget 规则引擎 ----------

def test_basic_estimate():
    b = estimate_budget(make_plan(), {"mentioned_budget": None})
    assert b["currency"] == "CNY"
    assert b["total_min"] < b["total_max"]
    assert b["total_min"] >= 20_000, "低于兜底线"
    assert len(b["line_items"]) >= 6, "明细应覆盖全部 6 个模块"


def test_priority_price_difference():
    b = estimate_budget(make_plan(), {"mentioned_budget": None})
    p0 = next(i for i in b["line_items"] if "扫码点单" in i["item"])
    p2 = next(i for i in b["line_items"] if "营销活动" in i["item"])
    assert p0["min_amount"] > p2["max_amount"], "P0 单价应高于 P2"


def test_integration_markup():
    plan = make_plan()
    plan["core_business_modules"][1]["description"] = "店员处理订单，需对接现有收银系统"
    b = estimate_budget(plan, None)
    assert any(i["item"].startswith("系统集成") for i in b["line_items"]), "收银对接应触发系统集成加价"
    b1 = estimate_budget(make_plan(), {"mentioned_budget": None})
    assert b["total_min"] > b1["total_min"], "有对接时下限应更高"


def test_multi_client_markup():
    plan = make_plan()
    plan["tech_stack"][0]["choice"] = "原生 App（iOS + 安卓）"
    b = estimate_budget(plan, None)
    assert any("多端" in i["item"] for i in b["line_items"]), "App 应触发多端加价"


def test_rush_deadline_markup():
    b = estimate_budget(make_plan(), {
        "mentioned_budget": None, "mentioned_deadline": "一个月内上线"})
    assert any("加急" in i["item"] for i in b["line_items"]), "加急工期应触发上浮"


def test_budget_echo_and_default():
    b = estimate_budget(make_plan(), {"mentioned_budget": "两三万"})
    assert "两三万" in b["budget_match"], "应回显用户提及的预算"
    b6 = estimate_budget(make_plan(), None)
    assert b6["budget_match"] == "用户未提及预算"


def test_determinism():
    b1 = estimate_budget(make_plan(), {"mentioned_budget": None})
    b2 = estimate_budget(make_plan(), {"mentioned_budget": None})
    assert b1 == b2, "规则引擎必须确定性"


# ---------- budget_constraint：parse_budget + 硬约束收敛 ----------

@pytest.mark.parametrize("text,expected", [
    ("10万", 100_000), ("10w", 100_000), ("100000", 100_000),
    ("100000元", 100_000), ("1000块钱", 1_000), ("预算 5-8 万", 80_000),
    ("2万以内", 20_000), ("一个月内", None), ("两个月", None), (None, None), ("", None),
])
def test_parse_budget(text, expected):
    assert parse_budget(text) == expected


def _constraint_plan() -> dict:
    return {
        "core_business_modules": [
            {"name": "A", "description": "模块A", "priority": "P0"},
            {"name": "B", "description": "模块B", "priority": "P0"},
            {"name": "C", "description": "模块C", "priority": "P1"},
            {"name": "D", "description": "模块D", "priority": "P1"},
        ],
        "tech_stack": [{"layer": "前端", "choice": "小程序"}],
    }


def test_no_budget_keeps_estimate():
    b = estimate_budget(_constraint_plan(), {})
    assert b["total_max"] == 40_000 and "未提及" in b["budget_match"]


def test_high_budget_caps_at_double_floor():
    # 用户改口「预算提高到10万」→ min(10万, max(测算4万, 底价*2)=5.2万) 防虚高
    b = estimate_budget(_constraint_plan(), {"mentioned_budget": "10万"})
    assert b["total_max"] == 52_000, f"上限防虚高: {b['total_max']}"
    assert "预算" in b["budget_match"]


def test_low_budget_converges():
    # 预算 2 万（低于测算 4 万但 ≥ MIN_TOTAL）→ 收敛到 1.2-2 万 + 收敛说明
    b = estimate_budget(_constraint_plan(), {"mentioned_budget": "2万"})
    assert b["total_max"] == 20_000 and b["total_min"] == 12_000
    assert any("收敛" in a for a in b["assumptions"])


def test_budget_below_floor_warns():
    # 预算 1000（< MIN_TOTAL）→ 保持现实成本区间 + 明确警示。
    # 话术口径以 8e759df（P8 档位改造）为准：不再承诺「无法交付」，
    # 而是提示低于该规模方案的最低可行成本、需协商缩减需求范围。
    # （T-1 已关闭：旧断言 assert "无法交付" 是话术改造前的过期断言）
    b = estimate_budget(_constraint_plan(), {"mentioned_budget": "1000块钱"})
    assert b["total_min"] == 26_000 and b["total_max"] == 40_000, "预算过低不收敛、保持现实成本"
    assert "低于该规模方案的最低可行成本" in b["budget_match"]
    assert "协商" in b["budget_match"]


# ---------- T-1 修复回归：corpus 只扫语义字段，脚手架/否定句/产品域词不虚增加价 ----------

def test_question_details_do_not_inflate_price():
    # 根因①：question_details 带着「未被用户选中的示例选项」（对接收银机）和
    # 问题原文（需要和现有系统打通吗）——曾全量 values() 扫进 corpus，
    # 用户明确拒绝对接仍被收 3 类集成加价（真实诊断定位，见 t1_budget_trace.py）
    req = {
        "mentioned_budget": None,
        "question_details": [
            {"question": "需要和现有系统打通吗？",
             "examples": [{"label": "对接收银机", "note": "和门店收银数据打通"},
                          {"label": "对接财务/电商", "note": "和财务软件同步"}]},
        ],
        "missing_info": ["是否需要对接现有系统（如收银机、财务软件）"],
    }
    b = estimate_budget(_constraint_plan(), req)
    b0 = estimate_budget(_constraint_plan(), {"mentioned_budget": None})
    assert b["line_items"] == b0["line_items"], "脚手架字段不得触发任何加价"
    assert b["total_max"] == b0["total_max"]


def test_negated_summary_not_integration():
    # 根因①同源：summary 常含否定句（「不用对接收银机，独立使用」），
    # 关键词引擎无否定语义，扫进 corpus 会把拒绝当需求
    req = {"mentioned_budget": None, "summary": "不用对接收银机或财务软件，独立使用。"}
    b = estimate_budget(_constraint_plan(), req)
    assert not any(i["item"].startswith("系统集成") for i in b["line_items"]), "否定句不得触发集成加价"


def test_product_domain_word_not_integration():
    # 根因②：「进销存」是产品域词——用户要做的系统本身就是进销存，
    # 不是要对接现有进销存（曾虚增一类 3k-6k 加价）
    req = {"project_title": "进销存管理系统", "business_type": "零售/批发", "mentioned_budget": None}
    b = estimate_budget(_constraint_plan(), req)
    assert not any("ERP" in i["item"] for i in b["line_items"]), "产品域词不得触发 ERP 对接加价"


def test_real_integration_still_charged():
    # 修复不误伤：模块描述里的真实对接需求照常计价（test_integration_markup 的
    # 对偶面——requirements 语义字段里明确说了要对接，也必须计价）
    req = {"core_features": ["收银对接", "库存管理"], "mentioned_budget": None}
    b = estimate_budget(_constraint_plan(), req)
    assert any("收银/POS" in i["item"] for i in b["line_items"]), "真实对接需求仍应加价"
