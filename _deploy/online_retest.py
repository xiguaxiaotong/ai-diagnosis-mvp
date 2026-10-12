# -*- coding: utf-8 -*-
"""W11D4 线上复测：客户报 bug 的同一对话流（修复部署后验证）。

流程：注册 → 建项目 → SSE 第 1 轮（拿追问）→ 答题卡回答（含「还没定」）
→ SSE 第 2 轮 → 断言靶子问题不再被问 → 清理项目。
"""
import json
import sys
import time

import requests

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://134.175.137.41"
SUFFIX = time.strftime("%H%M%S")
USER = f"smoke_reask_{SUFFIX}"
PASS = "smoke_pass_1"
IDEA = ("我想给我的奶茶店做个扫码点单小程序，客人扫码自己点单自己付款。"
        "要不要接美团外卖我还没定，先看看怎么做、要多少钱")


def sse_chat(token: str, pid: int, message: str) -> dict:
    """跑一轮 SSE，返回 {phase, questions, reply(=delta 拼接)}。"""
    r = requests.post(
        f"{BASE}/api/chat",
        json={"project_id": pid, "message": message},
        headers={"Authorization": f"Bearer {token}"},
        stream=True,
        timeout=300,
    )
    r.raise_for_status()
    meta = {}
    reply = ""
    for line in r.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        try:
            evt = json.loads(line[6:])
        except json.JSONDecodeError:
            continue
        if evt.get("type") == "meta":
            meta = evt
        elif evt.get("type") == "delta":
            reply += evt.get("content", "")
    meta["reply"] = reply
    return meta


# 注册 + 建项目
tok = requests.post(f"{BASE}/api/auth/register",
                    json={"username": USER, "password": PASS}, timeout=15).json()["token"]
H = {"Authorization": f"Bearer {tok}"}
pid = requests.post(f"{BASE}/api/projects",
                    json={"title": f"[线上复测]重复追问 {SUFFIX}", "raw_idea": IDEA},
                    headers=H, timeout=15).json()["id"]
print(f"user={USER} project_id={pid}")

print("\n===== 线上第 1 轮 =====")
print("用户> " + IDEA)
r1 = sse_chat(tok, pid, IDEA)
print(f"AI> {r1['reply'][:400]}")
print(f"[phase={r1['phase']} 追问={r1.get('questions')}]")
qs = r1.get("questions") or []
assert qs, "第 1 轮应有追问"

target = next((q for q in qs if "对接" in q or "外卖" in q or "系统" in q), qs[0])
lines = []
for q in qs:
    if q == target:
        lines.append(f"{q}：还没定")
    elif "预算" in q:
        lines.append(f"{q}：几千块")
    elif any(k in q for k in ("时间", "上线", "多久", "急")):
        lines.append(f"{q}：1个月内")
    elif any(k in q for k in ("多少", "规模", "量")):
        lines.append(f"{q}：每天几百笔")
    else:
        lines.append(f"{q}：就我自己用")
answer = "\n".join(lines)

print("\n===== 线上第 2 轮（靶子问题答「还没定」） =====")
print("用户> " + answer.replace("\n", " / "))
r2 = sse_chat(tok, pid, answer)
print(f"AI> {r2['reply'][:400]}")
print(f"[phase={r2['phase']} 追问={r2.get('questions')}]")

ok = all(not (q == target or target in q or (q and q in target)) for q in (r2.get("questions") or []))
print("\n===== 线上复测结论 =====")
if r2["phase"] == "confirm_wait":
    print("✅ 「还没定」视为有效回答 → 直接出方案，零重复追问（客户场景修复确认）")
elif ok:
    print("✅ 新问题允许问，靶子问题未被重复追问")
else:
    print("❌ 线上仍重复追问靶子问题——修复未生效")
    sys.exit(1)

# 清理：删验证项目（用户行与 verify 同口径留给 cleanup_smoke.py）
d = requests.delete(f"{BASE}/api/projects/{pid}", headers=H, timeout=15).json()
print(f"清理：删除验证项目 → {d}")
