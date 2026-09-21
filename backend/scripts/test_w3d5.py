"""Week3 Day5 验收：真实联调（uvicorn 子进程 + httpx 流式读 SSE）。

与 Day4 的区别：Day4 走 TestClient（进程内调用），本脚本
- 真实启动 uvicorn 子进程（独立进程、真实 TCP 端口）
- 用 httpx 以流式方式逐事件读取 SSE（模拟前端消费方式）
- 验证「发消息 → 流式回复 → 获取方案 → 确认」完整闭环

用法（在 backend/ 目录下运行，需要 DEEPSEEK_API_KEY）：
    python scripts/test_w3d5.py
"""

import json
import subprocess
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.config import DEEPSEEK_API_KEY  # noqa: E402

PORT = 8017
BASE = f"http://127.0.0.1:{PORT}"
ANSWER_1 = (
    "三家门店，每家店一天大概 200 单；要做微信小程序；"
    "需要对接店里现有的收银系统；预算两三万，希望一个月内上线"
)


def wait_server(timeout: float = 30.0) -> None:
    """轮询健康检查直到服务就绪。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(f"{BASE}/api/health", timeout=2)
            if r.status_code == 200 and r.json() == {"status": "ok"}:
                print(f"[0] uvicorn 已就绪（端口 {PORT}）")
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError("uvicorn 启动超时")


def sse_events(message: str, project_id: int) -> tuple[str, list[dict]]:
    """流式调用 /api/chat，逐事件接收并解析 SSE。返回 (phase, events)。"""
    events: list[dict] = []
    with httpx.stream(
        "POST", f"{BASE}/api/chat", timeout=120,
        json={"project_id": project_id, "message": message},
    ) as resp:
        assert resp.status_code == 200, resp.status_code
        assert "text/event-stream" in resp.headers["content-type"], "应为 SSE"
        buffer = ""
        for chunk in resp.iter_text():
            buffer += chunk
            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                if block.startswith("data: "):
                    events.append(json.loads(block[len("data: "):]))
    phase = events[0]["phase"]
    assert events[-1]["type"] == "done", "SSE 应以 done 结束"
    return phase, events


def main() -> None:
    if not DEEPSEEK_API_KEY or "你的" in DEEPSEEK_API_KEY:
        print("❌ 请先在 .env 中配置 DEEPSEEK_API_KEY")
        sys.exit(1)

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", f"--port", str(PORT),
         "--log-level", "warning"],
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    try:
        wait_server()

        # ========== 1. 创建项目 ==========
        pid = httpx.post(f"{BASE}/api/projects",
                         json={"title": "Day5 真实联调"}, timeout=30).json()["id"]
        print(f"[1] 项目创建 OK: id={pid}")

        # ========== 2. 发消息 → 流式回复（逐事件到达） ==========
        phase, events = sse_events("我想做个点单小程序", pid)
        assert phase == "clarify", phase
        deltas = [e["content"] for e in events if e["type"] == "delta"]
        assert len(deltas) > 5, f"增量块过少: {len(deltas)}"
        reply = "".join(deltas)
        assert "确认" in reply or "问题" in reply, "追问内容异常"
        print(f"[2] SSE 流式追问 OK：{len(events)} 事件 / {len(deltas)} 增量块（真实 TCP 流）")
        print(f"    回复预览: {reply[:50]}...")

        # ========== 3. 回答追问 → 到方案确认等待 ==========
        phase, _ = sse_events(ANSWER_1, pid)
        if phase == "clarify":
            phase, _ = sse_events(
                "补充：主要给顾客和店员用，需要订单管理和核销，数据存自己服务器", pid)
        assert phase == "confirm_wait", phase
        print(f"[3] 追问补全 OK：phase=confirm_wait")

        # ========== 4. 获取方案详情 ==========
        detail = httpx.get(f"{BASE}/api/project/{pid}", timeout=30).json()
        assert detail["solution"], "方案未生成"
        sol = detail["solution"]
        for key in ("requirements", "plan", "budget", "feasibility", "final_output"):
            assert sol.get(key), f"solution 缺少 {key}"
        print(f"[4] 方案详情 OK：预算 {detail['budget_min']}-{detail['budget_max']} 元，"
              f"对话 {len(detail['messages'])} 条")

        # ========== 5. 确认循环：revise → confirm ==========
        r = httpx.post(f"{BASE}/api/project/{pid}/confirm", json={
            "action": "revise", "feedback": "去掉营销活动，只保留核心点单"},
            timeout=180).json()
        assert r["phase"] == "confirm_wait" and r["revision_round"] == 1, r
        r = httpx.post(f"{BASE}/api/project/{pid}/confirm",
                       json={"action": "confirm"}, timeout=180).json()
        assert r["phase"] == "done", r
        print(f"[5] 确认循环 OK：revise(round=1) → confirm → done")

        # ========== 6. 404 分支 ==========
        assert httpx.get(f"{BASE}/api/project/999999", timeout=10).status_code == 404
        assert httpx.post(f"{BASE}/api/chat",
                          json={"project_id": 999999, "message": "x"}, timeout=10
                          ).status_code == 404
        print(f"[6] 404 分支 OK：不存在的项目返回 404")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        print("\n（uvicorn 子进程已退出）")

    print("\n" + "=" * 54)
    print("✅ Week3 Day5 验收通过（真实联调：uvicorn + httpx 流式 SSE + 确认闭环）")
    print("=" * 54)


if __name__ == "__main__":
    main()
