# -*- coding: utf-8 -*-
"""W11D4 线上 bug 真机复现脚本（修复后验证版）。

复现线上场景：快捷答题卡答「还没定」→ 同一问题不再被重复追问。
全链路真实：真实 DeepSeek、真实诊断图、真实 SQLite/checkpoint（非 stub）。

跑法（backend/ 下）：python scripts/repro_w11d4_reask.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # backend/

from app.db.database import SessionLocal, init_db
from app.services import project_service
from app.services.diagnosis_service import chat_turn

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

init_db()
db = SessionLocal()
try:
    proj = project_service.create_project(
        db, "[复现]奶茶店点单-重复追问验证",
        "我想给我的奶茶店做个扫码点单小程序，客人扫码自己点单自己付款。"
        "要不要接美团外卖我还没定，先看看怎么做、要多少钱",
    )
finally:
    db.close()
pid = proj.id
print(f"project_id={pid}")

print("\n===== 第 1 轮：用户想法 =====")
r1 = chat_turn(pid, "我想给我的奶茶店做个扫码点单小程序，客人扫码自己点单自己付款。要不要接美团外卖我还没定，先看看怎么做、要多少钱")
print("用户> 我想给奶茶店做扫码点单小程序……要不要接美团外卖我还没定……")
print(f"AI> {r1['reply']}")
print(f"[phase={r1['phase']} 追问={r1['questions']}]")

# 在第一轮问题里选一个做「还没定」靶子；其余问题给明确答案（答题卡逐行格式）
qs = r1["questions"]
assert qs, "第 1 轮应有追问"
target = next((q for q in qs if "对接" in q or "外卖" in q or "系统" in q), qs[0])
lines = []
for q in qs:
    if q == target:
        lines.append(f"{q}：还没定")
    elif "预算" in q:
        lines.append(f"{q}：几千块")
    elif "时间" in q or "上线" in q or "多久" in q or "急" in q:
        lines.append(f"{q}：1个月内")
    elif "多少" in q or "规模" in q or "量" in q:
        lines.append(f"{q}：每天几百笔")
    else:
        lines.append(f"{q}：就我自己用")
answer = "\n".join(lines)

print("\n===== 第 2 轮：答题卡回答（靶子问题答「还没定」） =====")
print("用户> " + answer.replace("\n", " / "))
r2 = chat_turn(pid, answer)
print(f"AI> {r2['reply'][:300]}{'…' if len(r2['reply']) > 300 else ''}")
print(f"[phase={r2['phase']} 追问={r2['questions']}]")

ok = True
for q in r2["questions"]:
    if q == target or (target in q) or (q and q in target):
        ok = False
        print(f"❌ 重复追问靶子问题：{q}")
print("\n===== 结论 =====")
if r2["phase"] == "confirm_wait":
    print("✅ 全部答完（含搁置型「还没定」视为有效回答）→ 直接出方案，无重复追问")
elif ok:
    print("✅ 仍有新问题但靶子问题未被重复追问（新问题允许问）")
else:
    print("❌ 靶子问题被重复追问——bug 未修复")
    sys.exit(1)
