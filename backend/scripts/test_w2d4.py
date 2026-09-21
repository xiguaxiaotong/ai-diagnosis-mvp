"""Week2 Day4 测试：generate 方案生成节点。

流程：模糊需求 → 追问 → 用户回答（最多 MAX_CLARIFY_ROUNDS 轮）
    → needs_clarify=False → generate 节点 → 校验 SolutionPlan JSON 结构

用法（在 backend/ 目录下运行，需要 DEEPSEEK_API_KEY）：
    python scripts/test_w2d4.py
"""

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.types import Command

from app.agent.graph import diagnosis_graph
from app.agent.nodes.check import MAX_CLARIFY_ROUNDS
from app.config import DEEPSEEK_API_KEY


def main() -> None:
    if not DEEPSEEK_API_KEY or "你的" in DEEPSEEK_API_KEY:
        print("❌ 请先在 .env 中配置 DEEPSEEK_API_KEY")
        sys.exit(1)

    cfg = {"configurable": {"thread_id": "test-w2d4"}}

    # ---------- 追问循环 ----------
    state = {
        "raw_idea": "我想做个点单小程序",
        "messages": [{"role": "user", "content": "我想做个点单小程序"}],
    }
    print("--- 输入模糊需求 ---")
    s = diagnosis_graph.invoke(state, cfg)
    assert s.get("error") is None, f"节点报错: {s.get('error')}"
    assert s["needs_clarify"] is True, "模糊需求应触发追问"
    print("AI 追问：")
    print(s["messages"][-1]["content"])

    answers = [
        ("三家门店，每家店一天大概 200 单；要做微信小程序；"
         "需要对接店里现有的收银系统；预算两三万，希望一个月内上线"),
        ("补充：不需要会员系统，主要是扫码点单和后厨出单；"
         "给顾客和店员用，安卓平板点单"),
        ("再补充：不用对接外卖平台，数据存自己服务器；"
         "主要给三家连锁店总部看报表"),
        ("就这些了，你们看着安排"),
        ("真的没有了，快点出方案吧"),
    ]
    for i, answer in enumerate(answers):
        if not s["needs_clarify"]:
            break
        print(f"\n--- 第 {i + 1} 次回答（当前轮次 {s['clarify_round']}）---")
        s = diagnosis_graph.invoke(Command(resume=answer), cfg)
        assert s.get("error") is None, f"节点报错: {s.get('error')}"

    assert s["needs_clarify"] is False, f"多轮后仍未补全: {s['clarify_questions']}"
    assert s.get("plan"), "需求补全后应已生成方案"

    # ---------- 校验 SolutionPlan 结构 ----------
    plan = s["plan"]
    print("\n✅ 方案 JSON 已生成，结构校验：")
    print(f"   project_name: {plan['project_name']}")
    print(f"   business_summary: {plan['business_summary']}")
    modules = plan["core_business_modules"]
    assert 3 <= len(modules) <= 8, f"业务模块数应在 3-8，实际 {len(modules)}"
    assert all(m["priority"] in ("P0", "P1", "P2") for m in modules), "优先级必须是 P0/P1/P2"
    assert any(m["priority"] == "P0" for m in modules), "必须至少有一个 P0 核心模块"
    print(f"   业务模块({len(modules)}): " + "、".join(
        f"{m['name']}[{m['priority']}]" for m in modules
    ))
    print(f"   技术架构: {plan['tech_architecture']}")
    stack = plan["tech_stack"]
    assert 4 <= len(stack) <= 6, f"技术选型应 4-6 层，实际 {len(stack)}"
    for t in stack:
        print(f"   - {t['layer']}: {t['choice']}（{t['reason']}）")
    phases = plan["implementation_phases"]
    assert 2 <= len(phases) <= 3, f"实施期数应 2-3，实际 {len(phases)}"
    for i, p in enumerate(phases, 1):
        print(f"   第{i}期: {p}")
    risks = plan["key_risks"]
    assert 2 <= len(risks) <= 4, f"风险应 2-4 条，实际 {len(risks)}"
    print(f"   风险提示({len(risks)}): {risks}")

    print("\n" + "=" * 50)
    print("✅ Week2 Day4 全部测试通过（需求补全 → 方案 JSON）")


if __name__ == "__main__":
    main()
