"""P2 文本切分：RecursiveCharacterTextSplitter（中文分隔符优先）。

长文档不能整篇入库——embedding 有输入长度限制，且整篇检索粒度太粗。
递归切分策略：优先按大段落切开，超长再逐级用更细的分隔符（段落 → 句 → 逗号 → 字符），
尽量保住语义完整的块。
"""

from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

# 中文文档的分隔符优先级：段落 > 换行 > 句号 > 分号 > 逗号 > 空格 > 任意字符
_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]

# chunk 参数：500 字左右一个块（bge-small 的最佳区间），重叠 80 字防止语义被切断
CHUNK_SIZE = 500
CHUNK_OVERLAP = 80

_splitter: RecursiveCharacterTextSplitter | None = None


def _get_splitter() -> RecursiveCharacterTextSplitter:
    global _splitter
    if _splitter is None:
        _splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            separators=_SEPARATORS,
            # 中文按字符数计长（默认 tiktoken 按英文 token，对中文不划算）
            length_function=len,
        )
    return _splitter


def split_text(text: str, chunk_size: int = CHUNK_SIZE) -> list[str]:
    """把长文本切成语义块，返回非空 chunk 列表。"""
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    chunks = _get_splitter().split_text(text)
    return [c.strip() for c in chunks if c.strip()]


def split_with_meta(text: str, base_metadata: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """切分并附带元数据。返回 [{"text", "metadata"}]，metadata 含 chunk_index/总数。"""
    base = dict(base_metadata or {})
    return [
        {"text": chunk, "metadata": {**base, "chunk_index": i}}
        for i, chunk in enumerate(split_text(text))
    ]
