"""Week3 Day1 验收：budget 预算测算节点（规则引擎）。

验收标准：给定方案能算出预算 JSON。
全部离线，不需要 LLM key，也无需网络——规则引擎的确定性正好可以精确断言。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # Windows GBK 控制台兼容

from app.agent.nodes.budget import estimate_budget  # noqa: E402


def make_plan() -> dict:
    """固定测试方案：3 个 P0 + 2 个 P1 + 1 个 P2，含收银对接 + 小程序。"""
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


def main() -> None:
    print("=" * 60)
    print("Week3 Day1：budget 预算测算节点（规则引擎）")
    print("=" * 60)

    plan = make_plan()

    # ---------- 1. 基础测算 ----------
    b1 = estimate_budget(plan, {"mentioned_budget": None})
    assert b1["currency"] == "CNY"
    assert b1["total_min"] < b1["total_max"], "区间下限必须小于上限"
    assert b1["total_min"] >= 20_000, f"低于兜底线: {b1['total_min']}"
    assert len(b1["line_items"]) >= 6, "明细应覆盖全部 6 个模块"
    print(f"\n[1] 基础测算: {b1['total_min']} - {b1['total_max']} 元，{len(b1['line_items'])} 项明细")
    for it in b1["line_items"]:
        print(f"    {it['item']}: {it['min_amount']}-{it['max_amount']} 元")

    # ---------- 2. 模块单价按优先级区分 ----------
    p0 = next(i for i in b1["line_items"] if "扫码点单" in i["item"])
    p2 = next(i for i in b1["line_items"] if "营销活动" in i["item"])
    assert p0["min_amount"] > p2["max_amount"], "P0 单价应高于 P2"
    print(f"\n[2] 优先级单价: P0({p0['min_amount']}) > P2({p2['max_amount']}) ✓")

    # ---------- 3. 对接加价 ----------
    plan_with_pos = make_plan()
    plan_with_pos["core_business_modules"][1]["description"] = "店员处理订单，需对接现有收银系统"
    b2 = estimate_budget(plan_with_pos, None)
    integration = [i for i in b2["line_items"] if i["item"].startswith("系统集成")]
    assert integration, "收银对接应触发系统集成加价"
    assert b2["total_min"] > b1["total_min"], "有对接时下限应更高"
    print(f"\n[3] 对接加价: {[i['item'] for i in integration]}")

    # ---------- 4. 多端加价 ----------
    plan_app = make_plan()
    plan_app["tech_stack"][0]["choice"] = "原生 App（iOS + 安卓）"
    b3 = estimate_budget(plan_app, None)
    assert any("多端" in i["item"] for i in b3["line_items"]), "App 应触发多端加价"
    print(f"[4] 多端加价: 触发 ✓")

    # ---------- 5. 加急上浮 ----------
    b4 = estimate_budget(plan, {"mentioned_budget": None, "mentioned_deadline": "一个月内上线"})
    assert any("加急" in i["item"] for i in b4["line_items"]), "加急工期应触发上浮"
    print(f"[5] 加急上浮: 触发 ✓")

    # ---------- 6. 预算对比 ----------
    b5 = estimate_budget(plan, {"mentioned_budget": "两三万"})
    assert "两三万" in b5["budget_match"], "应回显用户提及的预算"
    b6 = estimate_budget(plan, None)
    assert b6["budget_match"] == "用户未提及预算"
    print(f"[6] 预算对比: 「{b5['budget_match'][:30]}...」 ✓")

    # ---------- 7. 确定性：同输入同输出 ----------
    assert estimate_budget(plan, {"mentioned_budget": None}) == b1, "规则引擎必须确定性"
    print("[7] 确定性: 两次调用结果完全一致 ✓")

    print("\n" + "=" * 60)
    print("✅ Week3 Day1 预算测算节点通过（规则引擎 OK）")
    print("=" * 60)


if __name__ == "__main__":
    main()
