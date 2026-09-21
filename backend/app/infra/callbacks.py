"""日志/耗时回调工具。

提供：
- setup_logging: 统一日志初始化（控制台输出）
- log_duration: 同步函数耗时日志装饰器
- timer: 上下文管理器，手动记录任意代码块耗时（含流式首 token 场景）
- log_usage: 模型调用 token 用量日志
"""

import functools
import logging
import sys
import time
from contextlib import contextmanager
from typing import Callable, Iterator, TypeVar

logger = logging.getLogger("app.infra")

F = TypeVar("F", bound=Callable)


def setup_logging(level: int = logging.INFO) -> None:
    """统一日志初始化：控制台输出，应用入口调用一次即可。"""
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(fmt)
    for name in ("app", "app.infra", "app.infra.model_client"):
        lg = logging.getLogger(name)
        lg.setLevel(level)
        if not lg.handlers:
            lg.addHandler(handler)
        lg.propagate = False


def log_duration(name: str) -> Callable[[F], F]:
    """装饰器：记录同步函数执行耗时。

    用法：
        @log_duration("chat")
        def chat(...): ...
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                elapsed = time.perf_counter() - start
                logger.info("[%s] 耗时 %.2fs", name, elapsed)

        return wrapper

    return decorator


def log_usage(model: str, elapsed: float, prompt_tokens: int | None = None,
              completion_tokens: int | None = None) -> None:
    """记录一次模型调用的耗时与 token 用量。

    usage 不可用时（如部分流式实现）只记录耗时。
    """
    if prompt_tokens is None:
        logger.info("[model] model=%s 耗时 %.2fs", model, elapsed)
    else:
        logger.info(
            "[model] model=%s 耗时 %.2fs tokens: prompt=%d completion=%d total=%d",
            model, elapsed, prompt_tokens, completion_tokens or 0,
            prompt_tokens + (completion_tokens or 0),
        )


@contextmanager
def timer(name: str) -> Iterator[dict]:
    """上下文管理器：手动记录代码块耗时，结束后写日志。

    用法（记录流式首 token 时间）：
        with timer("first_token") as t:
            first = next(stream)
        print(t["elapsed"])
    """
    result: dict = {"elapsed": 0.0}
    start = time.perf_counter()
    try:
        yield result
    finally:
        result["elapsed"] = time.perf_counter() - start
        logger.info("[%s] 耗时 %.2fs", name, result["elapsed"])
