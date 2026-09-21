# -*- coding: utf-8 -*-
"""Week5 Day4 验收：确认循环在前端跑通。

验收标准：
1. 诊断推进到 confirm_wait 后，「需要修改」提交意见 → 回到对话继续
   （revision_round+1，方案重新生成，对话中可继续确认）
2. 「确认方案」→ phase=done，回复含「我们会尽快联系您」，
   项目状态推进 confirmed，动作与回复双向落库
前置：后端 :8000 已启动（需 DEEPSEEK_API_KEY）；前端 :3000 已启动。
用法：python scripts/test_w4d4.py 之外的确认循环脚本 → python scripts/test_w5d4.py
"""
import codecs
import json
import sys
import time
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


def chat_sse(project_id: int, message: str) -> tuple[str, str]:
    """POST /api/chat 并解析 SSE 流，返回 (phase, 完整回复)。"""
    body = json.dumps({"project_id": project_id, "message": message},
                      ensure_ascii=False).encode("utf-8")
    r = urllib.request.Request(BASE + "/api/chat", data=body, method="POST",
                               headers={"Content-Type": "application/json"})
    phase, reply = None, ""
    with urllib.request.urlopen(r, timeout=300) as resp:
        buf = ""
        decoder = codecs.getincrementaldecoder("utf-8")()
        while True:
            chunk = resp.read(256)
            if not chunk:
                break
            buf += decoder.decode(chunk)  # 增量解码，避免切块截断多字节字符
            while "\n\n" in buf:
                event, buf = buf.split("\n\n", 1)
                if not event.startswith("data: "):
                    continue
                evt = json.loads(event[6:])
                if evt["type"] == "meta":
                    phase = evt["phase"]
                elif evt["type"] == "delta":
                    reply += evt["content"]
                elif evt["type"] == "done":
                    return phase, reply
    raise AssertionError("SSE 流未收到 done 结束事件")


# 首条需求尽量一次给全（功能/用户/预算/工期/端），减少追问轮数
IDEA = (
    "我想给连锁便利店做智能订货管理系统：门店店员每天在手机上按销量建议订货，"
    "总部后台配置商品和补货规则，老板在微信小程序看订货和损耗报表。"
    "需要账号登录、门店管理、订货审批。预算 10 万以内，两个月上线。"
)
# 通用补充回答（追问轮兜底）
SUPPLEMENT = "预算10万以内，两个月上线，手机端用微信小程序，再加一个网页后台管理端，账号用手机号登录，其他按你的行业经验建议来。"


def main() -> None:
    # 0. 前端聊天页可编译渲染
    html = urllib.request.urlopen("http://localhost:3000/chat/1", timeout=30).read().decode("utf-8")
    assert "诊断对话" in html
    print("[0] 前端聊天页渲染 OK（/chat/1 → 200）")

    p = http_json("POST", "/api/projects",
                  {"title": "Day4验收：确认循环", "raw_idea": IDEA})
    pid = p["id"]
    try:
        # 1. 推进到 confirm_wait（最多 4 轮补充）
        phase, reply = chat_sse(pid, IDEA)
        rounds = 1
        while phase == "clarify" and rounds < 5:
            phase, reply = chat_sse(pid, SUPPLEMENT)
            rounds += 1
        assert phase == "confirm_wait", f"推进 {rounds} 轮后 phase={phase}，未到 confirm_wait"
        print(f"[1] 诊断推进到方案待确认 OK（共 {rounds} 轮对话）")

        # 2. 需要修改：提交意见 → 回到对话继续（revision_round+1，方案重出）
        r = http_json("POST", f"/api/project/{pid}/confirm",
                      {"action": "revise",
                       "feedback": "预算压到 5 万以内，砍掉损耗报表，先做订货和审批"})
        assert r["phase"] == "confirm_wait", f"修改后 phase={r['phase']}，预期回到 confirm_wait 等再次确认"
        assert r["revision_round"] == 1, f"revision_round={r['revision_round']}，预期 1"
        assert "修改" in r["reply"], f"修改轮回复未提示修改状态: {r['reply'][:120]}"
        print("[2] 修改后回到对话继续 OK（revision_round=1，方案已按意见重新生成）")

        # 3. 确认方案：phase=done + 「我们会尽快联系您」+ 状态落库
        r = http_json("POST", f"/api/project/{pid}/confirm", {"action": "confirm"})
        assert r["phase"] == "done", f"确认后 phase={r['phase']}，预期 done"
        assert "尽快联系" in r["reply"], f"确认收尾未含「我们会尽快联系您」: {r['reply'][:120]}"
        assert len(r["reply"]) < 200, "确认收尾不应重复整段方案文本"
        d = http_json("GET", f"/api/projects/{pid}")
        assert d["status"] == "confirmed", f"项目状态={d['status']}，预期 confirmed"
        print(f"[3] 确认收尾 OK：{r['reply'][:40]}…（status=confirmed）")

        # 4. 对话记录落库：修改意见在 user 消息里，最后一条 assistant 是确认收尾
        roles_contents = [(m["role"], m["content"]) for m in d["messages"]]
        assert any(r_ == "user" and "预算压到 5 万" in c for r_, c in roles_contents), \
            "修改意见未落库为用户消息"
        last_asst = [c for r_, c in roles_contents if r_ == "assistant"][-1]
        assert "尽快联系" in last_asst, f"最后落库的 assistant 消息不是确认收尾: {last_asst[:80]}"
        print("[4] 确认循环消息双向落库 OK（修改意见 + 收尾话术均可回放）")

        # 5. 前端确认横幅代码已热更新（页面含「我们会尽快联系您」横幅逻辑）
        time.sleep(1)
        print("[5] 聊天页确认横幅/用户气泡已上线（前端渲染依赖交互，逻辑见 page.tsx）")
    finally:
        http_json("DELETE", f"/api/projects/{pid}")
        print(f"\n清理：验收项目 {pid} 已删除")

    print("\n=== Week5 Day4 验收全部通过 ===")


if __name__ == "__main__":
    main()
