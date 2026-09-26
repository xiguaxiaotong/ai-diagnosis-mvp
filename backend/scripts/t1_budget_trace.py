"""T-1 定位用（W9）：真跑一条带明确预算的诊断，回放 trace 找预算丢失/变形点。

场景：「预算3万做个进销存」（金额明确、规模典型、无其他干扰信息）。
驱动方式与生产 API 相同：invoke 初唤 → wait_input interrupt 后
Command(resume=回答) 逐轮续跑 → wait_confirmation 后 resume「确认」收尾。

预算保真观察点（每轮打印）：
- understand 抽取的 requirements.mentioned_budget（原话是否保留「3万」）
- classify_budget 得到的 budget_tier（tier/amount）
- budget 节点产出的 budget（区间 + budget_match 是否以用户口径说话）

追问自动作答规则：预算类问题（预算/多少钱/投入）一律答「预算3万」
——防止示例选项改口污染定位；其余问题取 LLM 给的示例选项第一条。

隔离：TRACE_PATH / CHECKPOINTS_PATH 指向临时目录（真实库不落脏数据）；
案例库/向量库用真实数据（retrieve 需要真实检索）。

用法（backend/ 下，真实 DeepSeek，约几分钱）：
    python scripts/t1_budget_trace.py
"""

import os
import sys
import tempfile
import uuid
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="t1_budget_"))
os.environ["TRACE_PATH"] = str(_TMP / "trace.jsonl")
os.environ["CHECKPOINTS_PATH"] = str(_TMP / "checkpoints.sqlite")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # backend/

from langgraph.types import Command  # noqa: E402

from app.agent.graph import build_graph  # noqa: E402
from app.agent.trace import read_trace  # noqa: E402

IDEA = "预算3万做个进销存"
BUDGET_Q_KW = ("预算", "多少钱", "投入", "花")

graph = build_graph()
thread_id = f"t1-budget-{uuid.uuid4().hex[:8]}"
cfg = {"configurable": {"thread_id": thread_id}}

print(f"=== T-1 预算保真定位 | thread={thread_id} | 输入：{IDEA!r} ===")
result = graph.invoke({"raw_idea": IDEA,
                       "messages": [{"role": "user", "content": IDEA}]}, cfg)

round_no = 0
while True:
    snap = graph.get_state(cfg)
    if not snap.next:
        break
    interrupted_at = ",".join(snap.next)
    if "wait_confirmation" in snap.next:
        print(f"\n--- [interrupt@{interrupted_at}] 方案已出，回复「确认」收尾 ---")
        result = graph.invoke(Command(resume="确认"), cfg)
        continue
    if "wait_input" not in snap.next:
        print(f"\n!!! 未预期的 interrupt 位点：{snap.next}，停")
        break

    round_no += 1
    vals = snap.values
    req = vals.get("requirements") or {}
    tier = vals.get("budget_tier") or {}
    print(f"\n--- 第 {round_no} 轮追问（interrupt@wait_input）---")
    print(f"  mentioned_budget = {req.get('mentioned_budget')!r}")
    print(f"  budget_tier      = tier={tier.get('tier')!r} amount={tier.get('amount')!r}"
          f" mentioned={tier.get('mentioned')!r}")
    details = vals.get("question_details") or []
    answers = []
    for d in details:
        q = d.get("question", "")
        if any(k in q for k in BUDGET_Q_KW):
            answers.append("预算3万")
        else:
            exs = d.get("examples") or []
            answers.append(exs[0]["label"] if exs else "按你专业建议来")
    reply = "；".join(f"{i}. {a}" for i, a in enumerate(answers, 1)) if answers else "没有补充"
    print(f"  questions = {[d.get('question') for d in details]}")
    print(f"  auto-reply = {reply!r}")
    result = graph.invoke(Command(resume=reply), cfg)
    if round_no >= 8:
        print("!! 轮次保护触发")
        break

vals = graph.get_state(cfg).values
print("\n=== 终态预算链路 ===")
req = vals.get("requirements") or {}
print(f"mentioned_budget   = {req.get('mentioned_budget')!r}")
tier = vals.get("budget_tier") or {}
print(f"budget_tier        = {tier.get('tier')!r} / amount={tier.get('amount')!r}")
plan = vals.get("plan") or {}
print(f"plan.modules       = {[(m.get('name'), m.get('priority')) for m in plan.get('core_business_modules', [])]}")
budget = vals.get("budget")
if budget:
    print(f"budget.total       = {budget['total_min']}-{budget['total_max']}")
    print(f"budget.budget_match= {budget['budget_match']!r}")
    print(f"budget.assumptions = {budget['assumptions']}")
    print(f"budget.tier(透传)  = {budget.get('tier')}")
else:
    print(f"budget             = {budget!r}")

print("\n=== trace 回放（节点序）===")
for rec in read_trace(thread_id):
    if rec["type"] == "node":
        flags = []
        if rec.get("interrupted"):
            flags.append("interrupted")
        if rec.get("error"):
            flags.append(f"error={rec['error'][:60]}")
        if rec.get("state_errors"):
            flags.append(f"state_errors={rec['state_errors']}")
        print(f"  [{rec['node']:<18}] {rec['duration_ms']:>6}ms llm={rec['llm_calls']} "
              f"tokens={rec['tokens']['prompt']}+{rec['tokens']['completion']} "
              f"{' '.join(flags)}")
        print(f"      out: {rec['output_summary'][:160]}")
print(f"\ntrace 文件：{_TMP / 'trace.jsonl'}（隔离，可直查）")
