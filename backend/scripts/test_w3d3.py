"""Week3 Day3 验收：用户确认循环（确认/修改/拒绝，修改最多 3 轮）+ 完整 graph。

验收标准：端到端跑通全流程，含修改循环。
- 离线部分：意图分类 + 满轮路由单测（不调 LLM）
- 在线部分：真实跑「修改一轮 → 再确认」与「直接拒绝」两条完整链路

用法（在 backend/ 目录下运行，需要 DEEPSEEK_API_KEY）：
    python scripts/test_w3d3.py
"""

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.types import Command  # noqa: E402

from app.agent.graph import diagnosis_graph  # noqa: E402
from app.agent.nodes.confirm import (  # noqa: E402
    MAX_REVISION_ROUNDS,
    classify_decision,
    review_router,
)
from app.config import DEEPSEEK_API_KEY  # noqa: E402

ANSWER_1 = (
    "三家门店，每家店一天大概 200 单；要做微信小程序；"
    "需要对接店里现有的收银系统；预算两三万，希望一个月内上线"
)
ANSWER_2 = (
    "补充：系统主要给顾客和店员用，需要基础的订单管理和核销；"
    "不用对接外卖平台，数据存自己服务器"
)


# ============================ 离线单测 ============================


def test_offline() -> None:
    # 意图分类：拒绝优先 > 确认 > 其余视为修改
    assert classify_decision("确认，就这样") == "confirmed"
    assert classify_decision("OK 没问题") == "confirmed"
    assert classify_decision("算了，不要了") == "rejected"
    assert classify_decision("不要会员模块了") == "revised"  # 「不要模块」≠「不要项目」
    assert classify_decision("预算太高了，帮我砍砍") == "revised"
    assert classify_decision("能不能加个配送功能") == "revised"

    # 满轮路由：修改满 3 轮强制收尾
    assert review_router({"decision": "revised", "revision_round": 2}) == "revised"
    assert review_router({"decision": "revised", "revision_round": 3}) == "maxed"
    assert review_router({"decision": "confirmed"}) == "confirmed"
    assert review_router({"decision": "rejected", "revision_round": 9}) == "rejected"
    assert MAX_REVISION_ROUNDS == 3
    print("✅ 离线单测通过（意图分类 + 满轮路由）")


# ============================ 在线全流程 ============================


def run_to_plan(thread_id: str, idea: str = "我想做个点单小程序") -> dict:
    """跑完追问循环直到方案生成（停在 wait_confirmation interrupt）。"""
    cfg = {"configurable": {"thread_id": thread_id}}
    s = diagnosis_graph.invoke(
        {"raw_idea": idea, "messages": [{"role": "user", "content": idea}]}, cfg
    )
    assert s.get("error") is None, f"节点报错: {s.get('error')}"
    for answer in (ANSWER_1, ANSWER_2):
        if not s.get("needs_clarify"):
            break
        s = diagnosis_graph.invoke(Command(resume=answer), cfg)
        assert s.get("error") is None, f"节点报错: {s.get('error')}"
    assert s.get("full_solution"), "方案未生成"
    return s


def main() -> None:
    if not DEEPSEEK_API_KEY or "你的" in DEEPSEEK_API_KEY:
        print("❌ 请先在 .env 中配置 DEEPSEEK_API_KEY")
        sys.exit(1)

    test_offline()

    # ========== 流程 A：修改一轮 → 再确认 ==========
    print("\n--- 流程 A：修改一轮 → 再确认 ---")
    s = run_to_plan("test-w3d3-revise")
    v1 = s["full_solution"]["budget"]["total_min"]
    print(f"初版方案预算下限: {v1} 元")

    feedback = "预算有点高，把会员储值和营销活动去掉，只保留点单核心流程"
    s = diagnosis_graph.invoke(Command(resume=feedback), cfg := {"configurable": {"thread_id": "test-w3d3-revise"}})
    assert s.get("error") is None, f"节点报错: {s.get('error')}"
    assert s["decision"] == "revised", f"意图分类错误: {s['decision']}"
    assert s["revision_round"] == 1, f"修改轮次应为 1: {s['revision_round']}"
    v2 = s["full_solution"]["budget"]["total_min"]
    print(f"修改后预算下限: {v2} 元（round={s['revision_round']}）")
    assert s["full_solution"]["feasibility"], "修改后可行性评估缺失"
    assert s["full_solution"]["budget"]["total_min"] > 0, "修改后预算缺失"

    s = diagnosis_graph.invoke(Command(resume="确认，就这样"), cfg)
    assert s.get("error") is None, f"节点报错: {s.get('error')}"
    assert s["decision"] == "confirmed", f"确认后 decision 错误: {s['decision']}"
    assert "保留" not in s["messages"][-1]["content"], "确认流程不应走拒绝话术"
    print(f"✅ 流程 A 通过：修改 1 轮后确认（共 {len(s['messages'])} 条消息）")

    # ========== 流程 B：直接拒绝 ==========
    print("\n--- 流程 B：直接拒绝 ---")
    s = run_to_plan("test-w3d3-reject")
    s = diagnosis_graph.invoke(
        Command(resume="算了，不要了"), {"configurable": {"thread_id": "test-w3d3-reject"}}
    )
    assert s.get("error") is None, f"节点报错: {s.get('error')}"
    assert s["decision"] == "rejected", f"拒绝意图分类错误: {s['decision']}"
    assert "保留" in s["messages"][-1]["content"], "拒绝后应有保留方案话术"
    print("✅ 流程 B 通过：礼貌收尾，方案保留")

    print("\n" + "=" * 54)
    print("✅ Week3 Day3 验收通过（确认循环 + 完整 graph 编译）")
    print("=" * 54)


if __name__ == "__main__":
    main()
