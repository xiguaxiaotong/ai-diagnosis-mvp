"""Week2 Day1 测试：需求理解节点输出结构化 JSON。

用法（在 backend/ 目录下运行，需要 .env 里的 DEEPSEEK_API_KEY）：
    python scripts/test_w2d1.py
"""

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import DEEPSEEK_API_KEY
from app.agent.prompt_loader import load_prompt
from app.agent.nodes.understand import understand_node
from app.agent.schemas import ProjectRequirements


def main() -> None:
    # 1. Prompt 独立文件检查
    text = load_prompt("understand")
    assert "raw_idea" in text and "missing_info" in text
    print(f"✅ Prompt 独立文件: prompts/understand.txt ({len(text)} 字)")

    if not DEEPSEEK_API_KEY or "你的" in DEEPSEEK_API_KEY:
        print("❌ 请先在 .env 中配置 DEEPSEEK_API_KEY")
        sys.exit(1)

    # 2. 真实 LLM 调用：口语化、信息不完整的输入
    state = {
        "raw_idea": "我开了三家奶茶店，想让顾客自己在手机上点单，不用排队，"
                    "最好还能发优惠券把回头客拉回来，预算大概两三万",
    }
    result = understand_node(state)
    assert result.get("error") is None, f"节点报错: {result.get('error')}"

    # 3. 结构化校验（ProjectRequirements Pydantic 模型已在节点内部校验过）
    req = ProjectRequirements.model_validate(result["requirements"])
    print(f"✅ LLM 输出结构化 JSON 并通过 Pydantic 校验")
    print(f"   项目名称: {req.project_title}")
    print(f"   行业类型: {req.business_type}")
    print(f"   核心功能: {req.core_features}")
    print(f"   目标用户: {req.target_users}")
    print(f"   提到预算: {req.mentioned_budget}")
    print(f"   缺失信息: {req.missing_info}")
    print(f"   理解复述: {req.summary}")

    # 4. 追问触发检查
    assert result["needs_clarify"] == (len(req.missing_info) > 0)
    print(f"✅ 追问判断: needs_clarify={result['needs_clarify']}, "
          f"questions={result['clarify_questions']}")

    print("\n" + "=" * 50)
    print("✅ Week2 Day1 全部测试通过")


if __name__ == "__main__":
    main()
