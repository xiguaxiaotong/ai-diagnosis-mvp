"""P2 向量库：numpy + JSON 持久化实现。

为什么不用 Chroma：Chroma 0.4.x / 0.5.x 依赖 chroma-hnswlib（C++ 编译），
在 2C4G 服务器上 pip install 会因同时编译 100+ 依赖包而失败。
1.x 又拖 kubernetes / opentelemetry / grpcio 等大量 MVP 用不到的 deps。

MVP 案例量级 < 500，512 维向量点乘检索全量不到 1ms，HNSW 索引无意义，
直接用 numpy 余弦即可。持久化：vectors.npy (N×512 float32) + items.json。

Embedding 由 app.infra.model_client.embedding_client 提供（bge-small，512 维）。
用法与原 Chroma 实现完全兼容，调用方（retriever / loader / case_service）零改动。
"""

import json
import logging
import threading
from pathlib import Path
from typing import Any, Optional

import numpy as np

from app.config import CHROMA_DIR
from app.infra.model_client import embedding_client

logger = logging.getLogger(__name__)

COLLECTION_NAME = "cases"
DEFAULT_TOP_K = 5
# 相似度分数阈值（cosine score < 视为不相关，bge-small 中文经验值）
MIN_SCORE = 0.0


class VectorStore:
    """numpy 持久化向量库（cases 集合，cosine 相似度）。"""

    def __init__(self, path: Optional[str] = None, collection_name: str = COLLECTION_NAME):
        base = Path(path or CHROMA_DIR)
        base.mkdir(parents=True, exist_ok=True)
        self._dir = base / collection_name
        self._dir.mkdir(parents=True, exist_ok=True)
        self._vec_path = self._dir / "vectors.npy"
        self._meta_path = self._dir / "items.json"

        # 内存数据：self._items 与 self._matrix 一一对应（按 list 顺序）
        self._items: list[dict[str, Any]] = []  # [{id, text, metadata}]
        self._matrix: Optional[np.ndarray] = None  # (N, 512) float32
        self._id_to_idx: dict[str, int] = {}  # id → list index（O(1) 查询）
        self._lock = threading.RLock()

        self._load()

        logger.info("VectorStore 就绪: dir=%s, n=%d", self._dir, len(self._items))

    # ---------- 持久化 ----------

    def _load(self) -> None:
        """启动时一次性 load 到内存（500 条 / 1MB，启动毫秒级）。"""
        if self._vec_path.exists() and self._meta_path.exists():
            try:
                self._matrix = np.load(self._vec_path)
                with self._meta_path.open("r", encoding="utf-8") as f:
                    self._items = json.load(f)
                if len(self._items) != len(self._matrix):
                    logger.warning("向量与元数据条数不一致（%d vs %d），丢弃并重建",
                                   len(self._items), len(self._matrix))
                    self._items = []
                    self._matrix = None
            except Exception:
                logger.exception("VectorStore 持久化文件损坏，从空库启动")
                self._items = []
                self._matrix = None
        self._rebuild_index()

    def _save(self) -> None:
        """落盘（粗粒度，500 条 1MB，写入毫秒级；后续可加 WAL 优化）。"""
        if self._matrix is None or len(self._matrix) == 0:
            # 空库清空文件
            self._vec_path.unlink(missing_ok=True)
            self._meta_path.write_text("[]", encoding="utf-8")
            return
        np.save(self._vec_path, self._matrix)
        with self._meta_path.open("w", encoding="utf-8") as f:
            json.dump(self._items, f, ensure_ascii=False, indent=None)

    def _rebuild_index(self) -> None:
        """重建 id→idx 索引。upsert / delete 时局部更新也可，这里全量简单可靠。"""
        self._id_to_idx = {it["id"]: i for i, it in enumerate(self._items)}

    # ---------- 写 ----------

    def upsert(self, docs: list[dict[str, Any]]) -> int:
        """插入/覆盖文档。每个 doc: {"id", "text", "metadata"(可选)}。返回写入条数。"""
        if not docs:
            return 0
        texts = [d["text"] for d in docs]
        embeddings = embedding_client.embed_documents(texts)
        embeddings_np = np.asarray(embeddings, dtype=np.float32)
        # 归一化（点积 = 余弦）；bge-small 输出未严格归一化，显式 normalize
        norms = np.linalg.norm(embeddings_np, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        embeddings_np = embeddings_np / norms

        with self._lock:
            for i, d in enumerate(docs):
                item = {"id": d["id"], "text": d["text"],
                        "metadata": d.get("metadata") or {}}
                vec = embeddings_np[i]
                idx = self._id_to_idx.get(item["id"])
                if idx is not None:
                    # 覆盖：原地更新
                    self._items[idx] = item
                    self._matrix[idx] = vec
                else:
                    self._items.append(item)
                    if self._matrix is None:
                        self._matrix = vec.reshape(1, -1)
                    else:
                        self._matrix = np.vstack([self._matrix, vec])
            self._rebuild_index()
            self._save()
        logger.info("upsert %d docs → %s", len(docs), COLLECTION_NAME)
        return len(docs)

    def add_text(self, doc_id: str, text: str, metadata: Optional[dict] = None) -> None:
        """单条插入的便捷方法。"""
        self.upsert([{"id": doc_id, "text": text, "metadata": metadata}])

    def delete(self, ids: list[str]) -> None:
        """按 id 删除。"""
        if not ids:
            return
        with self._lock:
            keep_mask = np.ones(len(self._items), dtype=bool)
            for _id in ids:
                idx = self._id_to_idx.get(_id)
                if idx is not None:
                    keep_mask[idx] = False
            if not keep_mask.all():
                self._items = [it for it, k in zip(self._items, keep_mask) if k]
                if self._matrix is not None and len(self._items) > 0:
                    self._matrix = self._matrix[keep_mask]
                else:
                    self._matrix = None
                self._rebuild_index()
                self._save()

    def delete_by_doc(self, doc_id: str) -> int:
        """按 doc_id 元数据删除一个文档的全部 chunk，返回删除数。"""
        with self._lock:
            keep_idx = [i for i, it in enumerate(self._items)
                        if (it.get("metadata") or {}).get("doc_id") != doc_id]
            n = len(self._items) - len(keep_idx)
            if n == 0:
                return 0
            self._items = [self._items[i] for i in keep_idx]
            if self._matrix is not None and len(self._items) > 0:
                self._matrix = self._matrix[keep_idx]
            else:
                self._matrix = None
            self._rebuild_index()
            self._save()
            return n

    def clear(self) -> None:
        """清空集合。"""
        with self._lock:
            self._items = []
            self._matrix = None
            self._id_to_idx = {}
            self._save()

    # ---------- 读 ----------

    def search(self, query: str, top_k: int = DEFAULT_TOP_K,
               where: Optional[dict] = None) -> list[dict[str, Any]]:
        """按相似度检索。返回按相似度降序的 hits，score = cosine sim。

        注：MVP 无 where 过滤（retriever 只用纯相似度检索），接口保留以兼容。
        """
        if self._matrix is None or len(self._items) == 0:
            return []
        q = np.asarray(embedding_client.embed_query(query), dtype=np.float32)
        q_norm = np.linalg.norm(q)
        if q_norm > 0:
            q = q / q_norm
        # 余弦 = 已归一化矩阵 × q（点积）
        scores = self._matrix @ q  # (N,)
        k = min(top_k, len(self._items))
        # argpartition 取 top_k 索引，再按分数降序
        top_idx = np.argpartition(-scores, k - 1)[:k] if k < len(self._items) \
            else np.arange(len(self._items))
        top_idx = top_idx[np.argsort(-scores[top_idx])]
        hits: list[dict[str, Any]] = []
        for i in top_idx:
            hits.append({
                "id": self._items[i]["id"],
                "text": self._items[i]["text"],
                "metadata": self._items[i]["metadata"] or {},
                "score": round(float(scores[i]), 4),
            })
        return hits

    def get(self, doc_id: str) -> Optional[dict[str, Any]]:
        """按 id 取单条（不走向量）。"""
        idx = self._id_to_idx.get(doc_id)
        if idx is None:
            return None
        return dict(self._items[idx])

    def count(self) -> int:
        return len(self._items)


# 模块级单例（懒加载：首次调用才建库/加载模型）
_store: Optional[VectorStore] = None
_lock = threading.Lock()


def get_vector_store() -> VectorStore:
    global _store
    with _lock:
        if _store is None:
            _store = VectorStore()
        return _store