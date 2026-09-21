"""Prompt 模板加载器。

Prompt 全部放在 app/agent/prompts/*.txt，与代码解耦（方便评审和迭代）。
占位符写法：{{field_name}}，用 render() 填充。
不用 str.format，因为 Prompt 里常有 JSON 示例的花括号。
"""

from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """读取并缓存 Prompt 模板。name 不带扩展名，如 "understand"。"""
    path = PROMPTS_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt 模板不存在: {path}")
    return path.read_text(encoding="utf-8")


def render(name: str, **fields: str) -> str:
    """加载模板并填充占位符（{{field}} → 值）。未提供的占位符替换为空串。"""
    text = load_prompt(name)
    for key, value in fields.items():
        text = text.replace("{{" + key + "}}", value)
    # 兜底：清掉没填的占位符
    while "{{" in text:
        start = text.index("{{")
        end = text.index("}}", start)
        text = text[:start] + text[end + 2:]
    return text
