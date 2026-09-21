"""Week3 Day4 验收：P6 API（SSE /api/chat + GET /api/project/{id} + POST confirm）。

验收标准：curl 能调用，流式返回 token。
- 用 TestClient 走完整 HTTP 流程（不发真实网络请求，但走完整 FastAPI 栈）
- 断言 SSE 事件逐块返回、phase 归一化正确、确认循环三动作可用
- 最后打印 curl 命令供人工验收

用法（在 backend/ 目录下运行，需要 DEEPSEEK_API_KEY）：
    python scripts/test_w3d4.py
"""

import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.config import DEEPSEEK_API_KEY  # noqa: E402

ANSWER_1 = (
    "三家门店，每家店一天大概 200 单；要做微信小程序；"
    "需要对接店里现有的收银系统；预算两三万，希望一个月内上线"
)


def parse_sse(text: str) -> list[dict]:
    """把 SSE 响应体解析成事件列表。"""
    events = []
    for block in text.strip().split("\n\n"):
        if block.startswith("data: "):
            events.append(json.loads(block[len("data: "):]))
    return events


def main() -> None:
    if not DEEPSEEK_API_KEY or "你的" in DEEPSEEK_API_KEY:
        print("❌ 请先在 .env 中配置 DEEPSEEK_API_KEY")
        sys.exit(1)

    with TestClient(app) as client:
        # ========== 0. 健康检查 ==========
        assert client.get("/api/health").json() == {"status": "ok"}

        # ========== 1. 创建项目 ==========
        p = client.post("/api/projects", json={"title": "API 测试项目"}).json()
        pid = p["id"]
        print(f"[1] 项目创建 OK: id={pid}")

        # ========== 2. POST /api/chat：SSE 流式追问 ==========
        resp = client.post(
            "/api/chat", json={"project_id": pid, "message": "我想做个点单小程序"}
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"], "应为 SSE"
        events = parse_sse(resp.text)
        assert events[0]["type"] == "meta" and events[0]["phase"] == "clarify", events[0]
        deltas = [e["content"] for e in events if e["type"] == "delta"]
        assert len(deltas) > 5, f"SSE 块数过少: {len(deltas)}"
        assert events[-1]["type"] == "done"
        reply = "".join(deltas)
        assert "确认" in reply or "问题" in reply, "追问回复内容异常"
        print(f"[2] SSE 追问 OK：{len(events)} 个事件、{len(deltas)} 个增量块、meta→delta…→done")
        print(f"    回复预览: {reply[:60]}...")

        # ========== 3. 回答追问 → 方案确认等待 ==========
        resp = client.post("/api/chat", json={"project_id": pid, "message": ANSWER_1})
        events = parse_sse(resp.text)
        meta = events[0]
        # 需求可能一次补全（confirm_wait）或继续追问（clarify），都合法
        assert meta["phase"] in ("clarify", "confirm_wait"), meta
        print(f"[3] 回答追问 OK：phase={meta['phase']}")

        # 若还在追问，再补一轮到 confirm_wait
        if meta["phase"] == "clarify":
            resp = client.post("/api/chat", json={
                "project_id": pid,
                "message": "补充：主要给顾客和店员用，需要订单管理和核销，数据存自己服务器",
            })
            meta = parse_sse(resp.text)[0]
            assert meta["phase"] == "confirm_wait", meta
        print(f"    → 进入方案确认等待")

        # ========== 4. POST /api/project/{id}/confirm：revise ==========
        r = client.post("/api/project/%d/confirm" % pid, json={
            "action": "revise",
            "feedback": "把会员储值和营销活动去掉，只保留点单核心流程",
        }).json()
        assert r["phase"] == "confirm_wait", r
        assert r["revision_round"] == 1, f"修改轮次应为 1: {r}"
        assert r["solution"], "修改后应返回完整方案对象"
        print(f"[4] confirm.revise OK：round={r['revision_round']}")

        # ========== 5. confirm.confirm → done ==========
        r = client.post("/api/project/%d/confirm" % pid, json={"action": "confirm"}).json()
        assert r["phase"] == "done", r
        print(f"[5] confirm.confirm OK：phase=done")

        # ========== 6. GET /api/project/{id}：详情 + 完整方案 ==========
        detail = client.get(f"/api/project/{pid}").json()
        assert detail["status"] == "plan_generated", detail["status"]
        assert detail["solution"], "solution 未返回"
        sol = detail["solution"]
        for key in ("requirements", "plan", "budget", "feasibility", "final_output"):
            assert sol.get(key), f"solution 缺少 {key}"
        assert detail["budget_min"] > 0 and detail["budget_max"] > 0
        roles = [m["role"] for m in detail["messages"]]
        assert "user" in roles and "assistant" in roles, "对话记录未落库"
        print(f"[6] 项目详情 OK：status={detail['status']}，"
              f"方案字段齐全，对话 {len(detail['messages'])} 条已落库")

        # ========== 打印 curl 验收命令 ==========
        print("\n--- 人工 curl 验收（先启动 uvicorn）---")
        print(f"curl -N -X POST http://localhost:8000/api/chat -H \"Content-Type: application/json\" "
              f"-d '{{\"project_id\": {pid}, \"message\": \"我想做个点单小程序\"}}'")

    print("\n" + "=" * 54)
    print("✅ Week3 Day4 验收通过（P6 API：SSE + 详情 + 确认循环）")
    print("=" * 54)


if __name__ == "__main__":
    main()
