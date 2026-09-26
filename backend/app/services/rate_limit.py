"""W7 Day2 横切：滑动窗口限流（内存实现，无新依赖）。

设计：
- 单进程 MVP：内存字典够用；云上多 worker 需切 Redis（迁移 0.5 天）。
- 按 client IP 限流，X-Forwarded-For 优先（云上 Nginx/反代会塞它）。
- 滑动窗口：deque + 时间戳，避免固定窗口的「末尾爆发」问题。

调用：
    from app.services.rate_limit import check_rate_limit, client_ip

    @router.post("/login")
    def login(request: Request, ...):
        check_rate_limit(client_ip(request), limit=5, window_sec=60, scope="login")
        ...
"""
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

# IP+scope → 时间戳队列（单调时钟）
_attempts: dict[str, deque[float]] = defaultdict(deque)


def client_ip(request: Request) -> str:
    """优先取 X-Forwarded-For 第一段（云上 Nginx 反代会塞它），否则 client.host。"""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(*, key: str, limit: int, window_sec: int) -> None:
    """超出 → 429 + Retry-After（标准 HTTP 语义，前端/CDN 可原样处理）。

    key 一般 = `client_ip(request) + ':' + scope`，scope 区分接口（防一处爆满牵连全站）。
    """
    now = time.monotonic()
    dq = _attempts[key]
    # 弹掉窗口外的过期时间戳
    while dq and now - dq[0] > window_sec:
        dq.popleft()
    if len(dq) >= limit:
        retry = max(1, int(window_sec - (now - dq[0])))
        raise HTTPException(
            status_code=429,
            detail=f"请求过于频繁，请 {retry} 秒后再试",
            headers={"Retry-After": str(retry)},
        )
    dq.append(now)
