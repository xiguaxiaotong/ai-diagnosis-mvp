"""Week2 Day5 端到端串联测试：understand → ask/wait_input（追问循环）→ generate。

验收标准：命令行测试——输入想法 → 追问 2 轮 → 输出方案 JSON。

模拟用户分 2 轮补充信息（每轮回答后仍允许 LLM 判断信息是否齐全，
最终必须在 MAX_CLARIFY_ROUNDS 内补全），最后完整打印方案 JSON。

用法（在 backend/ 目录下运行，需要 DEEPSEEK_API_KEY）：
    python scripts/test_w2d5.py            # 自动模拟 2 轮回答
    python scripts/test_w2d5.py --idea "你的想法"   # 自定义想法
"""

import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.types import Command

from app.agent.graph import diagnosis_graph
from app.agent.nodes.check import MAX_CLARIFY_ROUNDS
from app.config import DEEPSEEK_API_KEY

# 预设的用户回答：模拟真实用户分两轮把信息说全
PRESET_ANSWERS = [
    "三家门店，每家店一天大概 200 单；要做微信小程序；"
    "需要对接店里现有的收银系统；预算两三万，希望一个月内上线",
    "补充：不需要会员系统，主要是扫码点单和后厨出单；"
    "给顾客和店员用，安卓平板点单；不用对接外卖平台，数据存自己服务器",
]


def validate_plan(plan: dict) -> None:
    """校验方案 JSON 结构（与 SolutionPlan 模型对应的断言）。"""
    assert plan["project_name"], "project_name 不能为空"
    assert plan["business_summary"], "business_summary 不能为空"
    modules = plan["core_business_modules"]
    assert 3 <= len(modules) <= 8, f"业务模块数应在 3-8，实际 {len(modules)}"
    assert all(m["priority"] in ("P0", "P1", "P2") for m in modules), "优先级必须 P0/P1/P2"
    assert any(m["priority"] == "P0" for m in modules), "必须至少有一个 P0 模块"
    assert 4 <= len(plan["tech_stack"]) <= 6, "技术选型应 4-6 层"
    assert 2 <= len(plan["implementation_phases"]) <= 3, "实施期数应 2-3"
    assert 2 <= len(plan["key_risks"]) <= 4, "风险应 2-4 条"


def main() -> None:
    if not DEEPSEEK_API_KEY or "你的" in DEEPSEEK_API_KEY:
        print("❌ 请先在 .env 中配置 DEEPSEEK_API_KEY")
        sys.exit(1)

    idea = "我想做个点单小程序"
    if "--idea" in sys.argv:
        idea = sys.argv[sys.argv.index("--idea") + 1]

    cfg = {"configurable": {"thread_id": "test-w2d5-e2e"}}

    # ========== 第 1 步：输入想法 → understand → ask（interrupt） ==========
    print(f"【用户】{idea}")
    s = diagnosis_graph.invoke(
        {"raw_idea": idea, "messages": [{"role": "user", "content": idea}]}, cfg
    )
    assert s.get("error") is None, f"节点报错: {s.get('error')}"

    # ========== 第 2 步：追问循环（用户分 2 轮补充） ==========
    for i, answer in enumerate(PRESET_ANSWERS, 1):
        if not s.get("needs_clarify"):
            break
        assert s["clarify_questions"], f"第 {i} 轮追问问题列表为空"
        print(f"\n【顾问·第 {s['clarify_round']} 轮追问】")
        print(s["messages"][-1]["content"])
        s = diagnosis_graph.invoke(Command(resume=answer), cfg)
        assert s.get("error") is None, f"节点报错: {s.get('error')}"
        print(f"【用户】{answer}")

    # ========== 第 3 步：结果校验 ==========
    assert s["clarify_round"] <= MAX_CLARIFY_ROUNDS, "追问轮次超限"
    assert s["needs_clarify"] is False, f"两轮补充后仍未补全: {s.get('clarify_questions')}"
    assert s.get("plan"), "方案未生成"
    assert not s.get("clarify_exhausted"), "正常流程不应触发强制结束"

    validate_plan(s["plan"])

    print(f"\n✅ 串联完成：追问 {s['clarify_round'] - 1} 轮后补全，"
          f"共 {len(s['messages'])} 条消息")
    print("\n" + "=" * 20, "最终方案 JSON", "=" * 20)
    print(json.dumps(s["plan"], ensure_ascii=False, indent=2))
    print("=" * 54)
    print("✅ Week2 Day5 端到端串联测试通过（M1-P1 核心链路 OK）")


if __name__ == "__main__":
    main()
