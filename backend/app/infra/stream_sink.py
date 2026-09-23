"""LLM 流式输出通道：节点内产生的文本 token 实时推给 SSE 层。

机制：
- chat_turn_stream 跑图前，在执行线程 set_sink(queue)；
- 节点内（consult 的 LLM 回复、output 的方案文案）调用 emit(token) 把文本
  实时 put 进队列；
- chat_turn_stream 的主循环 drain 队列，逐 token yield 给 API 层转 SSE delta。
- ContextVar 保证 sink 只在当前线程链可见（图节点与 set_sink 同线程执行），
  多项目并发时互不干扰。

节点不感知 SSE，只调 emit；没设 sink（如脚本/测试直跑图）时 emit 是 no-op。
"""

from contextvars import ContextVar
from queue import Queue

_sink: ContextVar = ContextVar("llm_stream_sink", default=None)


def set_sink(q: Queue) -> None:
    """在当前执行线程绑定 token 输出队列。"""
    _sink.set(q)


def emit(text: str) -> None:
    """节点内发出一段文本（token 或整段），实时流向 SSE。"""
    q = _sink.get()
    if q is not None and text:
        q.put(("token", text))


def reset() -> None:
    """通知前端清空已流出内容（如 consult 机密兜底替换话术时）。"""
    q = _sink.get()
    if q is not None:
        q.put(("reset", None))
