"""Week2 Day3 测试：追问循环（最多 5 轮）+ interrupt 机制。

场景 A（强制结束）：用户连续打太极「不知道，你看着办」
    → 状态正确累积（clarify_round 递增、messages 增长）
    → 第 5 轮触发 force_finish 强制结束
场景 B（正常补全）：第一轮追问后用户认真回答
    → Command(resume=...) 恢复 → needs_clarify=False，正常结束

用法（在 backend/ 目录下运行，需要 DEEPSEEK_API_KEY）：
    python scripts/test_w2d3.py
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


def _cfg(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def scenario_a() -> None:
    """场景 A：用户一直含糊其辞，验证 5 轮强制结束 + 状态累积。"""
    print("=" * 20, "场景 A：多轮打太极 → 第 5 轮强制结束", "=" * 20)
    cfg = _cfg("test-a-force")

    state = {
        "raw_idea": "我想做个点单小程序",
        "messages": [{"role": "user", "content": "我想做个点单小程序"}],
    }
    s = diagnosis_graph.invoke(state, cfg)
    assert s.get("error") is None, f"节点报错: {s.get('error')}"
    assert s["needs_clarify"] is True, "模糊需求应触发追问"
    assert s["clarify_round"] == 1, f"首轮 clarify_round 应为 1，实际 {s['clarify_round']}"

    # 循环恢复：每次都含糊回答，直到强制结束（防御性上限 10 次防死循环）
    vague_replies = [
        "不知道，你看着办", "都行", "你专业你来定", "没啥要求", "随便",
        "再说吧", "不清楚", "无所谓", "嗯", "哦",
    ]
    i = 0
    while s.get("needs_clarify") and not s.get("clarify_exhausted") and i < 10:
        msg_count = len(s["messages"])
        print(f"--- 恢复第 {i + 1} 次（回答: {vague_replies[i]}），"
              f"当前轮次={s['clarify_round']}，消息数={msg_count} ---")
        s = diagnosis_graph.invoke(Command(resume=vague_replies[i]), cfg)
        assert s.get("error") is None, f"节点报错: {s.get('error')}"
        # 状态累积：消息数必须单调增长
        assert len(s["messages"]) > msg_count, "消息数未增长，状态累积异常"
        i += 1

    assert s.get("clarify_exhausted") is True, "达到 5 轮应触发强制结束"
    assert s["clarify_round"] == MAX_CLARIFY_ROUNDS, (
        f"应恰好执行 {MAX_CLARIFY_ROUNDS} 轮 understand，实际 {s['clarify_round']}"
    )
    assert s["needs_clarify"] is True, "强制结束时需求本身仍不完整（符合预期）"
    last = s["messages"][-1]
    assert last["role"] == "assistant" and "初步方案" in last["content"], (
        "最后一条应是强制结束说明消息"
    )
    # 状态累积校验：初始 1 条 + 4 轮(问+答)*2 + 强制说明 1 条 = 10 条
    assert len(s["messages"]) == 10, f"消息总数应为 10，实际 {len(s['messages'])}"

    print(f"✅ 共 {s['clarify_round']} 轮后强制结束，消息数 {len(s['messages'])}，"
          f"requirements 保留（title={s['requirements']['project_title']}）")


def scenario_b() -> None:
    """场景 B：一轮追问后用户认真回答，正常补全结束。"""
    print("\n" + "=" * 20, "场景 B：正常回答 → 一轮补全", "=" * 20)
    cfg = _cfg("test-b-normal")

    state = {
        "raw_idea": "我想做个点单小程序",
        "messages": [{"role": "user", "content": "我想做个点单小程序"}],
    }
    s = diagnosis_graph.invoke(state, cfg)
    assert s["needs_clarify"] is True and s["clarify_round"] == 1
    print("AI 追问：")
    print(s["messages"][-1]["content"])

    answer = (
        "三家门店，每家店一天大概 200 单；要做微信小程序；"
        "需要对接店里现有的收银系统；预算两三万，希望一个月内上线"
    )
    s = diagnosis_graph.invoke(Command(resume=answer), cfg)
    assert s.get("error") is None, f"节点报错: {s.get('error')}"
    assert s["needs_clarify"] is False, "信息补全后不应再追问"
    assert not s.get("clarify_exhausted"), "正常结束不应有强制标记"
    assert s["requirements"]["core_features"], "核心功能不应为空"

    print(f"✅ 第 {s['clarify_round']} 轮补全，消息数 {len(s['messages'])}，"
          f"title={s['requirements']['project_title']}")


def main() -> None:
    if not DEEPSEEK_API_KEY or "你的" in DEEPSEEK_API_KEY:
        print("❌ 请先在 .env 中配置 DEEPSEEK_API_KEY")
        sys.exit(1)

    scenario_a()
    scenario_b()
    print("\n" + "=" * 50)
    print("✅ Week2 Day3 全部测试通过（追问循环 + interrupt + 5 轮强制结束）")


if __name__ == "__main__":
    main()
