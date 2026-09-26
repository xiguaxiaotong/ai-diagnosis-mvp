"""日志/耗时回调工具。

提供：
- setup_logging: 统一日志初始化（控制台输出，含手机号脱敏 filter）
- log_duration: 同步函数耗时日志装饰器
- timer: 上下文管理器，手动记录任意代码块耗时（含流式首 token 场景）
- log_usage: 模型调用 token 用量日志
- PhoneMaskingFilter: 把日志中所有 11 位手机号替换为 138****0001
"""

import functools
import logging
import re
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TypeVar

logger = logging.getLogger("app.infra")

F = TypeVar("F", bound=Callable)


class PhoneMaskingFilter(logging.Filter):
    """W7 Day6：日志手机号脱敏 filter。

    为什么要脱敏：admin 看 leads 完整手机号（他要打电话/加微信）。
    代码里随时可能 print / log 出来（如「admin X 改了 lead 11 的 status」→
    若 admin 把手机号写进 note 也会进日志 / exception traceback）。
    一旦日志泄露到 ELK / 文件 / 钉钉机器人，泄漏即发生。
    所以在源头（formatter 前）脱敏。

    匹配规则：11 位中国大陆手机号（1[3-9]xxxxxxxxx），
    上下文不接续数字（避免误命中 13 位 / 12 位）
    替换为 138****0001（不泄漏具体号但保留「这是个手机号」语义）
    """
    # (?<!\d) / (?!\d) 是反向 lookahead/lookbehind，防命中长数字串里的 11 位
    PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
    MASK = "138****0001"

    def filter(self, record: logging.LogRecord) -> bool:
        # 只脱敏 user 写的字符串：msg 模板 + args
        # 不动 exc_info / stack_info（traceback 里若出现手机号仍脱敏——
        # 改 msg 的 fmt 不行，但 stack_info 是 str 也可脱）
        try:
            if isinstance(record.msg, str) and self.PATTERN.search(record.msg):
                record.msg = self.PATTERN.sub(self.MASK, record.msg)
            if record.args:
                new_args = []
                changed = False
                for a in record.args:
                    if isinstance(a, str) and self.PATTERN.search(a):
                        new_args.append(self.PATTERN.sub(self.MASK, a))
                        changed = True
                    else:
                        new_args.append(a)
                if changed:
                    record.args = tuple(new_args)
            if record.exc_info:
                # exc_info 在 formatter 时由 Formatter.format() 拼接；
                # 我们改不了已经渲染好的，但 getMessage 不会包含 traceback
                # 所以 traceback 内的手机号不在脱敏范围——靠「不要把手机号打到 traceback」+「日志权限最小化」控制
                pass
        except Exception:
            # filter 不能抛异常，否则 logger 会吞日志
            pass
        return True


def setup_logging(level: int = logging.INFO) -> None:
    """统一日志初始化：控制台输出 + 手机号脱敏，应用入口调用一次即可。

    Day6 起：所有 handler 自动装上 PhoneMaskingFilter，源头脱敏。

    策略：filter 装在 root logger 上 + 给每个 app.* 子 logger 也加一份（双保险）。
    propagate=False 防止子 logger 重复输出到 root（双打印）。
    """
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(fmt)
    handler.addFilter(PhoneMaskingFilter())  # 关键：handler 层 filter

    # root logger 装 filter + handler（propagate=True 让任何 logger 的 log 都过 root filter）
    root = logging.getLogger()
    root.setLevel(level)
    root.addFilter(PhoneMaskingFilter())
    # root 不 addHandler——避免子 logger propagate 后输出 2 次
    # 各 app.* 子 logger 自己挂 handler 输出

    for name in ("app", "app.infra", "app.infra.model_client", "app.services"):
        lg = logging.getLogger(name)
        lg.setLevel(level)
        if not lg.handlers:
            lg.addHandler(handler)
        # 子 logger 也装一份 filter（防某些子 logger 自己 addHandler 时漏装）
        lg.addFilter(PhoneMaskingFilter())
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
