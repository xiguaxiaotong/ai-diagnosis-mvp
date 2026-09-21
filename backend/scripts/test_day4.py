"""Day4 测试脚本：验证每次模型调用控制台输出耗时 + token 日志。

用法（在 backend/ 目录下运行，需要 .env 里的 DEEPSEEK_API_KEY）：
    python scripts/test_day4.py
"""

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import DEEPSEEK_API_KEY
from app.infra.callbacks import setup_logging
from app.infra.model_client import chat_client

# 应用入口统一调用一次即可（main.py 启动时也会调用）
setup_logging()


def main() -> None:
    if not DEEPSEEK_API_KEY or "你的" in DEEPSEEK_API_KEY:
        print("❌ 请先在 .env 中配置 DEEPSEEK_API_KEY")
        sys.exit(1)

    messages = [
        {"role": "system", "content": "你是一个简洁的助手，回答不超过20个字。"},
        {"role": "user", "content": "一句话说明什么是向量检索"},
    ]

    print("--- 测试 1: 非流式调用（观察下方日志）---")
    text = chat_client.chat(messages)
    print(f"回复: {text}\n")

    print("--- 测试 2: 流式调用（观察下方日志）---")
    print("回复: ", end="", flush=True)
    for chunk in chat_client.stream_chat(messages):
        print(chunk, end="", flush=True)
    print("\n")

    print("✅ Day4 测试通过：两次调用的耗时/token 日志见上方 [model] 行")


if __name__ == "__main__":
    main()
