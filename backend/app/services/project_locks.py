"""项目级并发锁。

设计要点：
- 按 project_id 粒度加锁，不影响其他用户的其他项目。
- 锁带 10 分钟 TTL：防止持有者（线程）崩溃/卡死后锁被永久占有。
- 双重锁：_meta_lock 保护 _project_locks 字典本身的并发访问。
- acquire 用 non-blocking：第二次请求直接拿到锁的当前状态 + 409。
- release 后 touch 更新 TTL 时间戳，避免正常完成的请求被强夺。

为什么必须：LangGraph MemorySaver 是 in-memory dict，按 thread_id 存 checkpoint。
同 thread_id 两个并发请求同时 invoke + update state 会互相覆盖（state.messages 累积双份、
clarify_round 只算一次、requirements 互相覆盖等），后果是用户消息重复 + 追问轮次错乱 +
最终方案不可信。前端 busyRef 是异步 state 兜不住，必须服务端项目级锁兜底。
"""
import logging
import threading
import time
from typing import Dict, Tuple

logger = logging.getLogger(__name__)

# 10 分钟无活动 → 锁过期（持有者被认为已崩溃/卡死，下一个请求强夺）
_LOCK_TTL_SECONDS = 600

# project_id -> (lock, last_active_ts)
_project_locks: Dict[int, Tuple[threading.Lock, float]] = {}
_meta_lock = threading.Lock()  # 保护字典本身的并发读写


def get_project_lock(project_id: int) -> threading.Lock:
    """获取项目级普通锁（注意必须同线程 acquire+release）。

    为什么不用 RLock：FastAPI 把 SSE 生成器跑到 worker thread，端点在主线程。
    RLock 跨线程 release 抛「cannot release un-acquired lock」。
    解决方案：acquire 和 release 都在 generator 内（同线程）。

    带 10 分钟 TTL：防止持有者崩溃后锁被永久占有，下一个请求 10 分钟后强夺。
    """
    now = time.time()
    with _meta_lock:
        if project_id in _project_locks:
            lock, ts = _project_locks[project_id]
            if now - ts > _LOCK_TTL_SECONDS:
                # 锁已过期 → 强夺（旧的持有者应该已死或 stuck 超过 10 分钟）
                logger.warning(
                    "[project_lock] 项目 %s 锁已过期（%.0fs > %s TTL），强夺",
                    project_id, now - ts, _LOCK_TTL_SECONDS,
                )
                del _project_locks[project_id]
            else:
                return lock
        lock = threading.Lock()
        _project_locks[project_id] = (lock, now)
        return lock


def touch_project_lock(project_id: int) -> None:
    """更新锁的活跃时间戳（在每次 release 前调用，防正常请求被强夺）。"""
    now = time.time()
    with _meta_lock:
        if project_id in _project_locks:
            lock, _ = _project_locks[project_id]
            _project_locks[project_id] = (lock, now)


def force_release_project_lock(project_id: int) -> None:
    """手动释放某个项目的锁（用于测试/调试，生产环境一般用不到）。"""
    with _meta_lock:
        _project_locks.pop(project_id, None)