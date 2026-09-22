"""离线单测：用户预算硬约束（parse_budget + estimate_budget 收敛）。"""

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.nodes.budget import estimate_budget, parse_budget

# ---- parse_budget ----
cases = {
    "10万": 100_000, "10w": 100_000, "100000": 100_000, "100000元": 100_000,
    "1000块钱": 1_000, "预算 5-8 万": 80_000, "2万以内": 20_000,
    "一个月内": None,  # 不是金额
    "两个月": None, None: None, "": None,
}
for text, want in cases.items():
    got = parse_budget(text)
    assert got == want, f"parse_budget({text!r}) = {got}, want {want}"
print("✅ parse_budget 全通过")

PLAN = {
    "core_business_modules": [
        {"name": "A", "description": "模块A", "priority": "P0"},
        {"name": "B", "description": "模块B", "priority": "P0"},
        {"name": "C", "description": "模块C", "priority": "P1"},
        {"name": "D", "description": "模块D", "priority": "P1"},
    ],
    "tech_stack": [{"layer": "前端", "choice": "小程序"}],
}

# 场景1：无预算 → 现状（4 模块 26k-40k + 兜底）
b = estimate_budget(PLAN, {})
print(f"无预算: {b['total_min']}-{b['total_max']}")
assert b["total_max"] == 40_000 and "未提及" in b["budget_match"]

# 场景2：用户改口「预算提高到10万」→ 上限贴预算但防虚高：min(10万, max(40k, 26k*2))=52k
b = estimate_budget(PLAN, {"mentioned_budget": "10万"})
print(f"预算10万: {b['total_min']}-{b['total_max']}")
assert b["total_max"] == 52_000, f"上限应取 min(预算, max(测算, 底价*2)) 防虚高: {b['total_max']}"
assert "预算" in b["budget_match"]

# 场景3：预算 2 万（低于测算 4 万但 ≥ MIN_TOTAL）→ 收敛到 1.2-2 万 + 裁剪提示
b = estimate_budget(PLAN, {"mentioned_budget": "2万"})
print(f"预算2万: {b['total_min']}-{b['total_max']}")
assert b["total_max"] == 20_000 and b["total_min"] == 12_000
assert any("裁剪" not in a and "收敛" in a for a in b["assumptions"])

# 场景4：预算 1000（< MIN_TOTAL）→ 保持现实成本 + 明确警示
b = estimate_budget(PLAN, {"mentioned_budget": "1000块钱"})
print(f"预算1000: {b['total_min']}-{b['total_max']}")
assert b["total_max"] == 40_000
assert "无法交付" in b["budget_match"]

print("\n✅ 预算约束全通过")
