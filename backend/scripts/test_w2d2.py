"""Week2 Day2 测试：LangGraph invoke 验证 追问 → 回答 → 补全 闭环。

（Day3 图升级为 interrupt 机制后，本测试同步改用 Command(resume=...) 恢复。）

流程（模拟真实对话）：
  1. 第一次 invoke：输入模糊需求 → interrupt 暂停在追问
  2. Command(resume=用户回答) 恢复 → 信息补全 → needs_clarify=False

用法（在 backend/ 目录下运行，需要 DEEPSEEK_API_KEY）：
    python scripts/test_w2d2.py
"""

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.types import Command

from app.config import DEEPSEEK_API_KEY
from app.agent.graph import diagnosis_graph


def main() -> None:
    if not DEEPSEEK_API_KEY or "你的" in DEEPSEEK_API_KEY:
        print("❌ 请先在 .env 中配置 DEEPSEEK_API_KEY")
        sys.exit(1)

    cfg = {"configurable": {"thread_id": "test-w2d2"}}

    # ---------- 第一次 invoke：模糊需求 → 暂停在追问 ----------
    state = {
        "raw_idea": "我想做个点单小程序",
        "messages": [{"role": "user", "content": "我想做个点单小程序"}],
    }
    print("--- 第一次 invoke：输入模糊需求 ---")
    s1 = diagnosis_graph.invoke(state, cfg)
    assert s1.get("error") is None, f"节点报错: {s1.get('error')}"
    assert s1["needs_clarify"] is True, "模糊需求应触发追问"
    assert s1["clarify_questions"], "追问问题列表不应为空"
    last_msg = s1["messages"][-1]
    assert last_msg["role"] == "assistant"
    print("AI 追问：")
    print(last_msg["content"])

    # ---------- 用户回答 → Command 恢复 → 最多 MAX_CLARIFY_ROUNDS 轮补全 ----------
    answers = [
        ("三家门店，每家店一天大概 200 单；要做微信小程序；"
         "需要对接店里现有的收银系统；预算两三万，希望一个月内上线"),
        ("补充：不需要会员系统，主要是扫码点单和后厨出单；"
         "给顾客和店员用，安卓平板点单"),
        ("再补充：不用对接外卖平台，数据存自己服务器；"
         "主要给三家连锁店总部看报表"),
    ]
    print("\n--- Command(resume) 恢复：用户回答 ---")
    s2 = None
    for i in range(len(answers)):
        s2 = diagnosis_graph.invoke(Command(resume=answers[i]), cfg)
        assert s2.get("error") is None, f"节点报错: {s2.get('error')}"
        if not s2["needs_clarify"]:
            break
        print(f"（第 {i + 1} 轮后仍缺: {s2['clarify_questions']}，继续补充）")
    assert s2["needs_clarify"] is False, f"多轮补充后仍未补全: {s2['clarify_questions']}"
    assert s2["requirements"]["core_features"], "核心功能不应为空"

    req = s2["requirements"]
    print("✅ 需求已补全:")
    print(f"   项目名称: {req['project_title']}")
    print(f"   核心功能: {req['core_features']}")
    print(f"   提到预算: {req['mentioned_budget']}")
    print(f"   缺失信息: {req['missing_info']}")
    print(f"   对话轮次: {len(s2['messages'])} 条消息")

    print("\n" + "=" * 50)
    print("✅ Week2 Day2 全部测试通过（追问闭环跑通）")


if __name__ == "__main__":
    main()
