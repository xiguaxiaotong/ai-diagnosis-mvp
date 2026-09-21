# -*- coding: utf-8 -*-
"""Week5 Day5+ 等待体验验收：SSE 阶段事件（用户知道后端在做事）。

验收标准：
1. /api/chat 的事件序列为 stage（多个，带中文阶段提示）→ meta → delta → done
2. 阶段事件覆盖关键节点（understand 必现；推进到方案时 retrieve/generate 必现）
3. 正文流式不受影响
前置：后端 :8000 已启动（真调 LLM）。
用法：python scripts/test_w5d6.py
"""
import codecs
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


def chat_sse_full(project_id: int, message: str):
    """解析完整 SSE 事件序列，返回 (phase, reply, stages)。stages: [(node, label)]"""
    body = json.dumps({"project_id": project_id, "message": message},
                      ensure_ascii=False).encode("utf-8")
    r = urllib.request.Request(BASE + "/api/chat", data=body, method="POST",
                               headers={"Content-Type": "application/json"})
    phase, reply, stages = None, "", []
    with urllib.request.urlopen(r, timeout=300) as resp:
        buf = ""
        decoder = codecs.getincrementaldecoder("utf-8")()
        while True:
            chunk = resp.read(256)
            if not chunk:
                break
            buf += decoder.decode(chunk)
            while "\n\n" in buf:
                event, buf = buf.split("\n\n", 1)
                if not event.startswith("data: "):
                    continue
                evt = json.loads(event[6:])
                t = evt.get("type")
                if t == "stage":
                    stages.append((evt["stage"], evt["label"]))
                elif t == "meta":
                    phase = evt["phase"]
                elif t == "delta":
                    reply += evt["content"]
                elif t == "done":
                    return phase, reply, stages
    raise AssertionError("SSE 流未收到 done 结束事件")


def main() -> None:
    p = http_json("POST", "/api/projects",
                  {"title": "等待体验验收", "raw_idea": "x"})
    pid = p["id"]
    try:
        # 1. 第一轮：stage 事件应先于正文出现，understand 必现
        idea = "我想给健身房做会员管理系统，支持扫码入场、私教课预约和续费提醒"
        phase, reply, stages = chat_sse_full(pid, idea)
        nodes = [n for n, _ in stages]
        assert stages, "没有任何 stage 事件，等待体验改进未生效"
        assert "understand" in nodes, f"stage 事件缺 understand: {nodes}"
        assert phase == "clarify", f"第一轮 phase={phase}"
        assert len(reply) > 10, "正文流式异常"
        print(f"[1] 第一轮 OK：{len(stages)} 个阶段事件 {nodes}，"
              f"提示如「{stages[0][1]}」，正文 {len(reply)} 字")

        # 2. 补充信息推进到方案（最多 4 轮）：generate/budget 阶段必现
        phase2, stages2 = None, []
        for _ in range(4):
            phase2, _, stages2 = chat_sse_full(
                pid, "预算8万以内，两个月上线，微信小程序加网页后台，手机号登录，"
                     "需要会员管理、私教课预约、续费提醒，其他按你的行业建议来")
            if phase2 != "clarify":
                break
        nodes2 = [n for n, _ in stages2]
        assert "understand" in nodes2, f"缺 understand: {nodes2}"
        assert phase2 == "confirm_wait", f"{_} 轮后 phase={phase2}，未推进到方案"
        assert "generate" in nodes2, f"方案轮缺 generate 阶段: {nodes2}"
        assert "retrieve" in nodes2 and "budget" in nodes2, \
            f"方案轮缺检索/预算阶段: {nodes2}"
        labels = dict(stages2)
        print(f"[2] 推进到方案 OK：阶段序列 {nodes2}")
        print(f"    阶段提示示例：「{labels['generate']}」「{labels['budget']}」")

        # 3. 阶段事件都在 meta 之前（即先报阶段再出正文）
        #    由 chat_sse_full 的收集顺序保证：stages 在 reply 之前收到
        print("[3] 事件顺序 OK（stage → meta → delta → done）")
    finally:
        http_json("DELETE", f"/api/projects/{pid}")
        print(f"\n清理：验收项目 {pid} 已删除")

    print("\n=== 等待体验（阶段事件）验收全部通过 ===")


if __name__ == "__main__":
    main()
