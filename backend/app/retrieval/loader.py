"""P2 文档加载：PDF / Word(docx) / Markdown / 纯文本 → 纯文本 → 切分入库。

用法示例：
    from app.retrieval.loader import ingest_file
    from app.retrieval.vector_store import get_vector_store

    n = ingest_file("案例-点单小程序.pdf", get_vector_store(),
                    metadata={"industry": "餐饮"})
"""

import logging
from pathlib import Path
from typing import Any

from app.retrieval.splitter import split_with_meta
from app.retrieval.vector_store import VectorStore

logger = logging.getLogger(__name__)

SUPPORTED_EXTS = {".pdf", ".docx", ".md", ".markdown", ".txt"}


def load_text(path: str | Path) -> str:
    """按扩展名分发解析，返回文档全文（各页/各段用换行拼接）。"""
    p = Path(path)
    ext = p.suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise ValueError(f"不支持的文件类型: {ext}（支持 {sorted(SUPPORTED_EXTS)}）")

    if ext == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(p))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages)

    if ext == ".docx":
        import docx

        document = docx.Document(str(p))
        return "\n".join(para.text for para in document.paragraphs if para.text.strip())

    # md / markdown / txt 直接读
    return p.read_text(encoding="utf-8")


def ingest_file(path: str | Path, store: VectorStore,
                metadata: dict[str, Any] | None = None,
                doc_id: str | None = None) -> int:
    """加载单个文档 → 切分 → 入库。返回写入的 chunk 数。

    doc_id 缺省用文件名；chunk id 形如 "文件名#chunk0"，同名重传即覆盖（幂等）。
    """
    p = Path(path)
    text = load_text(p)
    if not text.strip():
        logger.warning("文档为空，跳过入库: %s", p.name)
        return 0

    doc_id = doc_id or p.stem
    base_meta = {"source": p.name, "doc_id": doc_id, **(metadata or {})}
    chunks = split_with_meta(text, base_meta)
    docs = [
        {"id": f"{doc_id}#{i}", "text": c["text"], "metadata": c["metadata"]}
        for i, c in enumerate(chunks)
    ]
    n = store.upsert(docs)
    logger.info("入库 %s: %d chunks", p.name, n)
    return n
