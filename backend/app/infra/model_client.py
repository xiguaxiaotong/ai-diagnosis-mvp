"""P5 统一模型客户端：对话（DeepSeek，支持流式）+ Embedding（bge-small 本地加载）。

用法示例：
    from app.infra.model_client import chat_client, embedding_client

    # 流式对话
    for chunk in chat_client.stream_chat([{"role": "user", "content": "你好"}]):
        print(chunk, end="", flush=True)

    # Embedding 转向量
    vec = embedding_client.embed_query("我想做一个客户管理系统")
"""

import logging
import os
import threading
import time
from pathlib import Path
from typing import Iterator, List, Optional

from openai import OpenAI

from app.config import (
    CHAT_MODEL,
    CHAT_TEMPERATURE,
    CHAT_TIMEOUT,
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    EMBEDDING_DEVICE,
    EMBEDDING_MODEL_NAME,
    HF_ENDPOINT,
)
from app.infra.callbacks import log_duration, log_usage

logger = logging.getLogger(__name__)

# bge 检索场景官方建议的查询指令前缀（文档侧不用加）
BGE_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


class ChatClient:
    """DeepSeek 对话客户端（OpenAI 兼容协议）。"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.model = model or CHAT_MODEL
        self._api_key = api_key or DEEPSEEK_API_KEY
        self._base_url = base_url or DEEPSEEK_BASE_URL
        self._client: Optional[OpenAI] = None

    def _ensure_client(self) -> OpenAI:
        """懒加载 OpenAI 客户端（导入模块时不需要 key）。"""
        if self._client is None:
            if not self._api_key:
                raise RuntimeError(
                    "未配置 DEEPSEEK_API_KEY，请在项目根目录 .env 中填入后重试"
                )
            self._client = OpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=CHAT_TIMEOUT,
            )
        return self._client

    @log_duration("chat")
    def chat(self, messages: List[dict], temperature: float = CHAT_TEMPERATURE, **kwargs) -> str:
        """非流式对话，返回完整回复文本。自动记录耗时与 token 用量。"""
        start = time.perf_counter()
        resp = self._ensure_client().chat.completions.create(
            model=self.model, messages=messages, temperature=temperature, **kwargs
        )
        usage = resp.usage
        log_usage(
            self.model,
            time.perf_counter() - start,
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
        )
        return resp.choices[0].message.content or ""

    def stream_chat(
        self, messages: List[dict], temperature: float = CHAT_TEMPERATURE, **kwargs
    ) -> Iterator[str]:
        """流式对话，逐段 yield 文本片段。结束时记录耗时与 token 用量。

        注意：不用 log_duration 装饰器——生成器惰性执行，装饰器只会
        测到生成器创建时间；真实耗时在流结束后由 log_usage 记录。
        """
        start = time.perf_counter()
        # DeepSeek 支持 stream_options.include_usage：最后一个事件携带 usage
        if "stream_options" not in kwargs:
            kwargs["stream_options"] = {"include_usage": True}
        stream = self._ensure_client().chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            stream=True,
            **kwargs,
        )
        usage = None
        for event in stream:
            if event.usage is not None:
                usage = event.usage
            if event.choices and event.choices[0].delta.content:
                yield event.choices[0].delta.content
        log_usage(
            self.model,
            time.perf_counter() - start,
            prompt_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
            completion_tokens=getattr(usage, "completion_tokens", None) if usage else None,
        )


class EmbeddingClient:
    """bge-small 本地 Embedding 客户端（单例懒加载，无需 API key）。

    模型：BAAI/bge-small-zh-v1.5，输出 512 维向量，模型文件约 100MB，
    首次使用会自动从 HF_ENDPOINT（默认 hf-mirror.com）下载并缓存到本地。
    """

    _instance: Optional["EmbeddingClient"] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self, model_name: Optional[str] = None, device: Optional[str] = None):
        if self._initialized:
            return
        self.model_name = model_name or EMBEDDING_MODEL_NAME
        self.device = device or EMBEDDING_DEVICE
        self._model = None
        self._initialized = True

    def _ensure_loaded(self):
        if self._model is not None:
            return
        # 国内网络走镜像站下载
        os.environ.setdefault("HF_ENDPOINT", HF_ENDPOINT)
        # 模型已缓存时强制走离线模式，跳过 HF Hub 版本 HEAD 检查
        # （否则每个 config 文件 HEAD 5 次，每次 1+2+4+8+8 = 23 秒 × 3 个 config ≈ 70 秒白等）
        # 用直接赋值不用 setdefault：setdefault 不会覆盖已经存在的值
        cache_dir = Path(os.getenv(
            "HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
        if (cache_dir / f"models--{self.model_name.replace('/', '--')}").exists():
            os.environ["HF_HUB_OFFLINE"] = "1"
            # transformers 库认这个，不认 HF_HUB_OFFLINE
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            # 关掉版本检查带来的额外 HEAD 请求
            os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
            logger.info("模型已缓存，启用离线加载: %s", cache_dir)
        else:
            logger.info("模型未缓存，将从 %s 首次下载", HF_ENDPOINT)
        from sentence_transformers import SentenceTransformer

        logger.info("加载 Embedding 模型: %s (device=%s)", self.model_name, self.device)
        self._model = SentenceTransformer(self.model_name, device=self.device)

    @log_duration("embed")
    def embed(self, texts: List[str], is_query: bool = False) -> List[List[float]]:
        """批量文本转向量。is_query=True 时加检索指令前缀（bge 官方建议）。"""
        self._ensure_loaded()
        if is_query:
            texts = [BGE_QUERY_INSTRUCTION + t for t in texts]
        vectors = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [v.tolist() for v in vectors]

    def embed_query(self, text: str) -> List[float]:
        """单条查询转向量（加检索指令前缀）。"""
        return self.embed([text], is_query=True)[0]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """文档入库转向量（不加指令前缀）。"""
        return self.embed(texts, is_query=False)


# 模块级单例，业务代码直接 import 使用
chat_client = ChatClient()
embedding_client = EmbeddingClient()
