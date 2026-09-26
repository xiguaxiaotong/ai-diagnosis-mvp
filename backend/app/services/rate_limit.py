"""W7 Day2 横切：滑动窗口限流（内存实现，无新依赖）。W9 收尾 B 项扩展。

设计：
- 单进程 MVP：内存字典够用；云上多 worker 需切 Redis（迁移 0.5 天）。
- 按 client IP 限流，X-Forwarded-For 优先（云上 Nginx/反代会塞它）。
- 滑动窗口：deque + 时间戳，避免固定窗口的「末尾爆发」问题。
- W9 B 项：
  * 总开关 settings.RATE_LIMIT_ENABLED（False = 全部接口直通，
    测试环境默认关，防测试套件自身触发限流）
  * 原语拆分——check_rate（查超限不记账）/ record_rate（只记账），
    供「登录失败才计数」语义组合；check_rate_limit 保持查+记账原子
  * 阈值全部走 config（settings.RATE_*）

调用：
    from app.services.rate_limit import check_rate_limit, client_ip

    @router.post("/login")
    def login(request: Request, ...):
        check_rate_limit(client_ip(request), limit=5, window_sec=60, scope="login")
        ...
    # 失败才计数（登录）：
    check_rate(key, limit, window_sec, scope="login")   # 先查（当前失败数）
    ... 失败路径 ...
    record_rate(key, window_sec)                        # 失败才记账
"""
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from app.config import settings

# key+scope → 时间戳队列（单调时钟）
_attempts: dict[str, deque[float]] = defaultdict(deque)

# scope → 人话文案（429 detail；未列出的用通用文案）
_MESSAGES = {
    "diagnosis": "您发起的咨询有点频繁，请先休息一下，{retry} 秒后再试",
    "register": "注册请求太频繁了，请一小时后再试",
    "login": "密码错误次数太多，请一小时后再试，或先用邮箱重置密码",
}
_DEFAULT_MSG = "请求过于频繁，请 {retry} 秒后再试"


def client_ip(request: Request) -> str:
    """优先取 X-Forwarded-For 第一段（云上 Nginx 反代会塞它），否则 client.host。"""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _pruned(key: str, window_sec: int) -> deque[float]:
    """返回弹掉窗口外过期时间戳后的队列（不清空空 key，保持 defaultdict 语义）。"""
    dq = _attempts[key]
    now = time.monotonic()
    while dq and now - dq[0] > window_sec:
        dq.popleft()
    return dq


def _raise_429(key: str, scope: str, window_sec: int, dq: deque[float]) -> None:
    now = time.monotonic()
    retry = max(1, int(window_sec - (now - dq[0])))
    msg = _MESSAGES.get(scope, _DEFAULT_MSG).format(retry=retry)
    raise HTTPException(
        status_code=429,
        detail=msg,
        headers={"Retry-After": str(retry)},
    )


def check_rate(*, key: str, limit: int, window_sec: int, scope: str = "") -> None:
    """只查是否超限（不记账）。超限 → 429 + Retry-After + 人话文案。

    与 record_rate 组合实现「失败才计数」；一般场景直接用 check_rate_limit。
    """
    if not settings.RATE_LIMIT_ENABLED:
        return
    dq = _pruned(key, window_sec)
    if len(dq) >= limit:
        _raise_429(key, scope, window_sec, dq)


def record_rate(*, key: str, window_sec: int) -> None:
    """只记账一次（不过限）。与 check_rate 组合用。"""
    if not settings.RATE_LIMIT_ENABLED:
        return
    _attempts[key].append(time.monotonic())


def check_rate_limit(*, key: str, limit: int, window_sec: int, scope: str = "") -> None:
    """查 + 记账（原子）。超限 → 429 + Retry-After。

    key 一般 = `client_ip(request) + ':' + scope`，scope 区分接口（防一处爆满牵连全站）。
    """
    if not settings.RATE_LIMIT_ENABLED:
        return
    dq = _pruned(key, window_sec)
    if len(dq) >= limit:
        _raise_429(key, scope, window_sec, dq)
    dq.append(time.monotonic())


def reset_rate_limits() -> None:
    """测试用：清空全部记账。"""
    _attempts.clear()
