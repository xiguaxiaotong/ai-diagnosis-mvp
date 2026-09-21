"""P2 向量库：Chroma 持久化封装（增删查），Embedding 用 bge-small 本地模型。

职责边界：
- 向量化交给 app.infra.model_client.embedding_client（bge-small，512 维）
- 本模块只管 Chroma 的生命周期：建库、插入、按相似度检索、删除

用法示例：
    from app.retrieval.vector_store import get_vector_store

    store = get_vector_store()
    store.upsert([{"id": "case-1", "text": "扫码点单小程序…",
                   "metadata": {"industry": "餐饮"}}])
    hits = store.search("我想做个点单小程序", top_k=3)
    # [{"id": "case-1", "text": "...", "metadata": {...}, "score": 0.83}]
"""

import logging
import threading
from typing import Any, Optional

import chromadb

from app.config import CHROMA_DIR
from app.infra.model_client import embedding_client

logger = logging.getLogger(__name__)

COLLECTION_NAME = "cases"

# 相似度分数阈值以下的结果丢弃（cosine distance > 1 - 阈值 即不相关）
DEFAULT_TOP_K = 5


class VectorStore:
    """Chroma 持久化向量库封装（cases 集合，cosine 相似度）。"""

    def __init__(self, path: Optional[str] = None, collection_name: str = COLLECTION_NAME):
        self._client = chromadb.PersistentClient(path=str(path or CHROMA_DIR))
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            # cosine 空间：distance = 1 - cos_sim；向量已归一化，与 bge 官方建议一致
            metadata={"hnsw:space": "cosine"},
        )
        self._collection_name = collection_name
        logger.info("VectorStore 就绪: path=%s, collection=%s, n=%d",
                    path or CHROMA_DIR, collection_name, self._collection.count())

    # ---------- 写 ----------

    def upsert(self, docs: list[dict[str, Any]]) -> int:
        """插入/覆盖文档。每个 doc: {"id", "text", "metadata"(可选)}。返回写入条数。"""
        if not docs:
            return 0
        ids = [d["id"] for d in docs]
        texts = [d["text"] for d in docs]
        metadatas = [d.get("metadata") or {} for d in docs]
        embeddings = embedding_client.embed_documents(texts)
        self._collection.upsert(ids=ids, documents=texts,
                                metadatas=metadatas, embeddings=embeddings)
        logger.info("upsert %d docs → %s", len(docs), self._collection_name)
        return len(docs)

    def add_text(self, doc_id: str, text: str, metadata: Optional[dict] = None) -> None:
        """单条插入的便捷方法。"""
        self.upsert([{"id": doc_id, "text": text, "metadata": metadata}])

    def delete(self, ids: list[str]) -> None:
        """按 id 删除。"""
        if ids:
            self._collection.delete(ids=ids)

    def clear(self) -> None:
        """清空集合（重建）。"""
        self._client.delete_collection(self._collection_name)
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name, metadata={"hnsw:space": "cosine"})

    # ---------- 读 ----------

    def search(self, query: str, top_k: int = DEFAULT_TOP_K,
               where: Optional[dict] = None) -> list[dict[str, Any]]:
        """按相似度检索。返回按相似度降序的 hits，score = 1 - cosine distance。"""
        if self._collection.count() == 0:
            return []
        query_embedding = embedding_client.embed_query(query)
        result = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, self._collection.count()),
            where=where,
        )
        hits: list[dict[str, Any]] = []
        for i, doc_id in enumerate(result["ids"][0]):
            distance = result["distances"][0][i]
            hits.append({
                "id": doc_id,
                "text": result["documents"][0][i],
                "metadata": (result["metadatas"][0][i] or {}),
                "score": round(1.0 - distance, 4),
            })
        return hits

    def get(self, doc_id: str) -> Optional[dict[str, Any]]:
        """按 id 取单条（不走向量）。"""
        result = self._collection.get(ids=[doc_id])
        if not result["ids"]:
            return None
        return {"id": result["ids"][0], "text": result["documents"][0],
                "metadata": (result["metadatas"][0] or {})}

    def count(self) -> int:
        return self._collection.count()


# 模块级单例（懒加载：首次调用才建库/加载模型）
_store: Optional[VectorStore] = None
_lock = threading.Lock()


def get_vector_store() -> VectorStore:
    global _store
    with _lock:
        if _store is None:
            _store = VectorStore()
        return _store
