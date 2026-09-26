"""W8 Day1：节点级 Trace 中间层。

设计约束（对应验收标准）：
- 挂载方式是「包装函数」（traced），不改任何现有节点函数签名、不改图结构；
  graph.py 里只是把 add_node 的第二参从裸函数换成 traced(名字, 函数)
- LLM 层单独记录：hook 在 model_client.chat / stream_chat 里（全项目 LLM
  调用都收敛这两个方法），每次调用记一条 llm 记录，并把 token 累加到
  「当前正在执行的节点」上（节点记录里带 llm_calls / tokens 汇总）
- thread_id 传递：包装函数签名是 (state, config)，LangGraph 检测到 config
  形参会自动注入 RunnableConfig，从 configurable.thread_id 取；LLM 调用
  发生在节点执行线程内，用 threading.local 把 thread_id / 当前节点带给
  LLM hook（chat_turn_stream 的图跑在子线程，thread-local 天然隔离）
- 写入失败绝不影响主流程：_append 全体 try/except，只 logger.warning

落盘格式（logs/trace.jsonl，一行一条 JSON，追加写）：
- 节点记录：{"type": "node", "thread_id", "node", "start", "duration_ms",
             "input_summary", "output_summary", "llm_calls",
             "tokens": {"prompt", "completion"}, ["error"]}
- LLM 记录：{"type": "llm", "thread_id", "node", "model", "duration_ms",
             "prompt_tokens", "completion_tokens", "input_summary",
             "output_summary"}
"""

import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.config import TRACE_PATH

logger = logging.getLogger(__name__)

# 摘要截断长度：trace 是排障用的，不是全文存档
_SUMMARY_LIMIT = 200

# 线程内上下文：{thread_id, node, llm_calls, tokens}（图在同一线程内执行节点，
# chat_turn_stream 的子线程也各自独立，不串会话）
_tl = threading.local()


def _summary(text: Any, limit: int = _SUMMARY_LIMIT) -> str:
    """任意对象 → 截断的纯文本摘要（None → 空串）。"""
    if text is None:
        return ""
    if not isinstance(text, str):
        try:
            text = json.dumps(text, ensure_ascii=False, default=str)
        except Exception:
            text = str(text)
    text = text.replace("\n", " ").strip()
    return str(text)[:limit]


def _node_input_summary(state: Any) -> str:
    """节点输入摘要：取最后一条用户消息 + raw_idea 兜底。"""
    try:
        if isinstance(state, dict):
            msgs = state.get("messages") or []
            for m in reversed(msgs):
                if isinstance(m, dict) and m.get("content"):
                    return _summary(m["content"], 120)
            return _summary(state.get("raw_idea"), 120)
    except Exception:
        pass
    return _summary(state, 120)


def llm_input_summary(messages: Any) -> str:
    """LLM 输入摘要：消息条数 + 最后一条消息内容截断。"""
    try:
        if isinstance(messages, list) and messages:
            last = messages[-1]
            content = last.get("content", "") if isinstance(last, dict) else str(last)
            return _summary(f"[{len(messages)}条] {content}", 160)
    except Exception:
        pass
    return _summary(messages, 160)


def _append(record: dict[str, Any]) -> None:
    """追加写一条 trace。任何失败只打日志，绝不向上抛。"""
    try:
        record["ts"] = datetime.now(UTC).isoformat()
        TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(TRACE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception:
        logger.warning("[trace] 写入失败（主流程不受影响）: %s",
                       str(TRACE_PATH), exc_info=True)


def traced(node_name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
    """节点包装器：记录 {thread_id, 节点名, 开始/耗时, 输入/输出摘要, token}。

    注意不能用 functools.wraps：LangGraph 用 inspect.signature 决定是否
    注入 config，wraps 会让签名穿透回原函数的 (state) —— config 就拿不到了。
    """

    def wrapper(state: Any, config: RunnableConfig | None = None, *args: Any, **kwargs: Any) -> Any:
        thread_id = None
        try:
            thread_id = ((config or {}).get("configurable") or {}).get("thread_id")
        except Exception:
            pass

        _tl.thread_id = thread_id
        _tl.node = node_name
        _tl.llm_calls = 0
        _tl.tokens = {"prompt": 0, "completion": 0}

        start = time.perf_counter()          # 耗时基准（单调钟，跨零点/校时安全）
        start_at = datetime.now(UTC)  # 开始时刻（epoch 钟；perf_counter 不是
        #                                      epoch，拿它换算会得到 1970+开机时长）
        error = None
        interrupted = False
        result = None
        try:
            result = fn(state, *args, **kwargs)
            return result
        except BaseException as e:
            # interrupt() 是 LangGraph 的正常暂停机制（wait_input / wait_confirmation），
            # 不算错误；其余异常照实记录再原样上抛（主流程语义不变）
            try:
                from langgraph.errors import GraphInterrupt
                interrupted = isinstance(e, GraphInterrupt)
            except Exception:
                interrupted = False
            if not interrupted:
                error = repr(e)[:200]
            raise
        finally:
            record = {
                "type": "node",
                "thread_id": thread_id,
                "node": node_name,
                "start": start_at.isoformat(),
                "duration_ms": round((time.perf_counter() - start) * 1000),
                "input_summary": _node_input_summary(state),
                "output_summary": _summary(result),
                "llm_calls": getattr(_tl, "llm_calls", 0),
                "tokens": dict(getattr(_tl, "tokens", {"prompt": 0, "completion": 0})),
            }
            if interrupted:
                record["interrupted"] = True
            if error:
                record["error"] = error
            _append(record)
            # 清理本线程上下文（防泄漏到下一次非图执行期的 LLM 记录）
            _tl.thread_id = None
            _tl.node = None

    return wrapper


def record_llm(
    model: str,
    duration_ms: float,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    input_summary: str,
    output_summary: str,
) -> None:
    """LLM 调用记录（model_client.chat / stream_chat 结束时调用）。

    同时把 token 累加到当前节点（若正在节点执行线程内），节点记录
    汇总 token 就是这里攒的。任何失败只打日志。
    """
    try:
        thread_id = getattr(_tl, "thread_id", None)
        node = getattr(_tl, "node", None)
        if node is not None:
            _tl.llm_calls = getattr(_tl, "llm_calls", 0) + 1
            tokens = getattr(_tl, "tokens", None) or {"prompt": 0, "completion": 0}
            tokens["prompt"] += prompt_tokens or 0
            tokens["completion"] += completion_tokens or 0
            _tl.tokens = tokens
        _append({
            "type": "llm",
            "thread_id": thread_id,
            "node": node,
            "model": model,
            "duration_ms": round(duration_ms),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "input_summary": input_summary,
            "output_summary": output_summary,
        })
    except Exception:
        logger.warning("[trace] LLM 记录失败（主流程不受影响）", exc_info=True)


def read_trace(thread_id: str) -> list[dict[str, Any]]:
    """读某会话的完整调用链（时间序 = 追加序）。

    thread_id 支持两种写法：图内完整键（project-<uuid>）或裸 uuid，
    裸 uuid 自动补 project- 前缀再匹配一次（admin 页面拿到的通常后者）。
    """
    wanted = {thread_id}
    if not thread_id.startswith("project-"):
        wanted.add(f"project-{thread_id}")
    out: list[dict[str, Any]] = []
    try:
        if not TRACE_PATH.exists():
            return out
        with open(TRACE_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue  # 坏行跳过，不让一行脏数据废掉整个接口
                if rec.get("thread_id") in wanted:
                    out.append(rec)
    except Exception:
        logger.warning("[trace] 读取失败: %s", str(TRACE_PATH), exc_info=True)
    return out


def aggregate_traces() -> dict[str, dict[str, Any]]:
    """W8 Day2：按 thread_id 聚合全量 trace（单遍流式读，内存只留聚合结果）。

    每会话：{thread_id, started_at, last_active_at, node_count, llm_count,
            prompt_tokens, completion_tokens, total_duration_ms}。

    口径：
    - started_at / last_active_at 用记录 ts（node/llm 都有）的 min/max
    - token 只从 llm 记录取（source of truth；node.tokens 是同一份的累加）
    - total_duration_ms 只累加 node 的 duration_ms（node 耗时已含其 LLM
      调用，llm.duration_ms 再加会双计）
    坏行/无 thread_id 行跳过。返回 {thread_id: 聚合行}。
    """
    sessions: dict[str, dict[str, Any]] = {}
    try:
        if not TRACE_PATH.exists():
            return sessions
        with open(TRACE_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                tid = rec.get("thread_id")
                if not tid:
                    continue
                s = sessions.get(tid)
                if s is None:
                    s = {
                        "thread_id": tid,
                        "started_at": None,
                        "last_active_at": None,
                        "node_count": 0,
                        "llm_count": 0,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_duration_ms": 0,
                    }
                    sessions[tid] = s
                ts = rec.get("ts")
                if ts:
                    if s["started_at"] is None or ts < s["started_at"]:
                        s["started_at"] = ts
                    if s["last_active_at"] is None or ts > s["last_active_at"]:
                        s["last_active_at"] = ts
                if rec.get("type") == "node":
                    s["node_count"] += 1
                    s["total_duration_ms"] += rec.get("duration_ms") or 0
                elif rec.get("type") == "llm":
                    s["llm_count"] += 1
                    s["prompt_tokens"] += rec.get("prompt_tokens") or 0
                    s["completion_tokens"] += rec.get("completion_tokens") or 0
    except Exception:
        logger.warning("[trace] 聚合读取失败: %s", str(TRACE_PATH), exc_info=True)
    return sessions
