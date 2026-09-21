# -*- coding: utf-8 -*-
"""Week5 Day2 验收：聊天页对接 SSE 流式接口，多轮对话正常。

验收标准：流式输出流畅（多 delta 分块），多轮对话正常（新会话 → 追问 resume）。
前置：后端 :8000 已启动（需 DEEPSEEK_API_KEY 配置）。
用法：python scripts/test_w5d2.py
"""
import json
import sys
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://localhost:8000"


def http_json(method: str, path: str, body: dict | None = None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))


def chat_sse(project_id: int, message: str) -> tuple[str, str, list]:
    """POST /api/chat 并解析 SSE 流，返回 (phase, 完整回复, delta 计数)。"""
    body = json.dumps({"project_id": project_id, "message": message},
                      ensure_ascii=False).encode("utf-8")
    r = urllib.request.Request(BASE + "/api/chat", data=body, method="POST",
                               headers={"Content-Type": "application/json"})
    phase, deltas, reply = None, 0, ""
    with urllib.request.urlopen(r, timeout=300) as resp:
        assert resp.headers["Content-Type"].startswith("text/event-stream"), \
            f"响应不是 SSE: {resp.headers['Content-Type']}"
        buf = ""
        while True:
            chunk = resp.read(256)
            if not chunk:
                break
            buf += chunk.decode("utf-8")
            while "\n\n" in buf:
                event, buf = buf.split("\n\n", 1)
                if not event.startswith("data: "):
                    continue
                evt = json.loads(event[6:])
                if evt["type"] == "meta":
                    phase = evt["phase"]
                elif evt["type"] == "delta":
                    deltas += 1
                    reply += evt["content"]
                elif evt["type"] == "done":
                    return phase, reply, deltas
    raise AssertionError("SSE 流未收到 done 结束事件")


def main() -> None:
    # 0. 前端聊天页可编译渲染
    html = urllib.request.urlopen("http://localhost:3000/chat/1").read().decode("utf-8")
    assert "诊断对话" in html
    print("[0] 前端聊天页渲染 OK（/chat/1 → 200）")

    # 1. 建项目 → 第一轮：SSE 流式返回，应停在 clarify（有追问）
    p = http_json("POST", "/api/projects",
                  {"title": "Day2验收：奶茶店点单", "raw_idea": "x"})
    pid = p["id"]
    try:
        idea = "我想给一家奶茶店做扫码点单小程序，支持会员和优惠券"
        phase1, reply1, n1 = chat_sse(pid, idea)
        assert phase1 == "clarify", f"第一轮 phase={phase1}，预期 clarify"
        assert n1 >= 10, f"delta 分块过少({n1})，流式输出无效"
        assert "确认" in reply1 or "?" in reply1 or "？" in reply1, \
            f"追问轮回复不含问题: {reply1[:120]}"
        print(f"[1] 第一轮 OK：phase=clarify，回复 {len(reply1)} 字，"
              f"SSE 分 {n1} 块推送（流式生效）")

        # 2. 第二轮 resume：回答追问，图应推进到 confirm_wait（方案已出）
        phase2, reply2, n2 = chat_sse(pid, "预算10万以内，三个月上线，主要给堂食客人用，要会员储值功能")
        assert phase2 in ("confirm_wait", "clarify"), \
            f"第二轮 phase={phase2}，多轮推进异常"
        assert n2 >= 10 and reply2, "第二轮流式回复为空"
        detail = http_json("GET", f"/api/projects/{pid}")
        if phase2 == "confirm_wait":
            assert detail["solution"], "confirm_wait 但方案未落库"
            assert detail["status"] == "plan_generated"
        # 每轮双向落库（user + assistant），两轮共 4 条；最后一条应为本轮回复
        assert len(detail["messages"]) >= 4, \
            f"消息落库数异常: {len(detail['messages'])}"
        assert detail["messages"][-1]["content"] == reply2, "最后一落库消息与流式回复不一致"
        print(f"[2] 第二轮 OK：phase={phase2}，回复 {len(reply2)} 字 / {n2} 块，"
              f"消息已落库 {len(detail['messages'])} 条"
              + ("，方案已生成" if phase2 == "confirm_wait" else ""))

        print("\n✅ Week5 Day2 验收通过（SSE 流式 + 多轮对话正常）")
    finally:
        http_json("DELETE", f"/api/projects/{pid}")
        print("\n[cleanup] 测试项目已删除")


if __name__ == "__main__":
    main()
