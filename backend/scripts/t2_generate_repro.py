"""T-2 复现（W9）：stub generate 的 LLM 三种坏输出，确认当前整链行为。

三种模式（argv[1]，缺省全跑）：
    optional  缺可选字段（one_liner / glossary / 模块 example）
    required  缺必填字段（全部模块 priority，即 T-1 定位时真实触发的场景）
    invalid   返回非 JSON 文本

隔离：env 五路径指临时目录，零真钱；understand/feasibility stub 成功输出，
只有 generate 按模式坏。跑完整图（understand→…→generate→budget→feasibility→output），
打印每种模式的终态：plan/budget 是否存在、error 内容、output 兜底话术。
"""

import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="t2_repro_"))
os.environ["SQLITE_PATH"] = str(_TMP / "sqlite.db")
os.environ["CHROMA_DIR"] = str(_TMP / "chroma")
os.environ["CASES_DIR"] = str(_TMP / "cases")
os.environ["CHECKPOINTS_PATH"] = str(_TMP / "checkpoints.sqlite")
os.environ["TRACE_PATH"] = str(_TMP / "trace.jsonl")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # backend/

# ---- stub 数据：信息齐全的需求 + 完好方案（坏输出按模式生成）----

REQ_FULL = {
    "project_title": "进销存管理系统",
    "business_type": "零售/批发",
    "core_features": ["商品管理", "采购进货", "销售出货", "库存管理"],
    "target_users": ["老板", "仓管"],
    "mentioned_budget": "3万",
    "mentioned_deadline": "两个月",
    "missing_info": [],
    "question_details": [],
    "pain_points": ["手工记账容易错"],
    "summary": "3万做进销存，两人用，电脑网页。",
}
FEAS = {
    "overall": "可行", "risk_level": "低",
    "tech_assessment": "成熟。", "schedule_assessment": "可行。",
    "budget_assessment": "匹配。", "suggestions": ["先上线核心功能"],
}
GOOD_PLAN = {
    "project_name": "进销存管理系统",
    "one_liner": "把进货卖货库存放到电脑上管。",
    "business_summary": "3万预算内的轻量进销存。",
    "core_business_modules": [
        {"name": "商品管理", "description": "商品档案登记", "priority": "P0"},
        {"name": "采购进货", "description": "进货单录入", "priority": "P0"},
        {"name": "销售出货", "description": "销售开单", "priority": "P0"},
    ],
    "tech_architecture": "网页 + FastAPI + MySQL。",
    "tech_stack": [
        {"layer": "前端", "choice": "Vue", "reason": "轻量"},
        {"layer": "后端", "choice": "FastAPI", "reason": "快"},
    ],
    "implementation_phases": ["一期：商品+进销闭环"],
    "key_risks": ["数据迁移"],
}


def _bad_plan(mode: str) -> str:
    plan = json.loads(json.dumps(GOOD_PLAN))
    if mode == "optional":
        plan.pop("one_liner", None)   # 顶层可选
        plan.pop("glossary", None)    # 顶层可选
        for m in plan["core_business_modules"]:
            m.pop("example", None)    # 模块内可选（GOOD_PLAN 本就不带，显式删一次）
        return json.dumps(plan, ensure_ascii=False)
    if mode == "required":
        for m in plan["core_business_modules"]:
            m.pop("priority")         # 必填：T-1 定位时真实触发
        return json.dumps(plan, ensure_ascii=False)
    return "抱歉，我还需要更多信息……这里不是 JSON"


def run_mode(mode: str) -> None:
    from app.infra import model_client

    calls = {"generate": 0}

    def stub_chat(messages, **kwargs):
        prompt = messages[0]["content"] if messages else ""
        if "资深的 AI 产品顾问" in prompt:
            return json.dumps(REQ_FULL, ensure_ascii=False)
        if "可行性评估" in prompt:
            return json.dumps(FEAS, ensure_ascii=False)
        if "core_business_modules" in prompt:
            calls["generate"] += 1
            return _bad_plan(mode)
        return json.dumps(GOOD_PLAN, ensure_ascii=False)

    orig = model_client.chat_client.chat
    model_client.chat_client.chat = stub_chat
    try:
        from app.agent.graph import build_graph

        graph = build_graph()
        cfg = {"configurable": {"thread_id": f"t2-{mode}-{uuid.uuid4().hex[:6]}"}}
        graph.invoke({"raw_idea": "预算3万做个进销存",
                      "messages": [{"role": "user", "content": "预算3万做个进销存"}]}, cfg)
        v = graph.get_state(cfg).values
        print(f"\n===== mode={mode}（generate 被调 {calls['generate']} 次）=====")
        print(f"  error       = {v.get('error')!r}")
        print(f"  plan 存在  = {bool(v.get('plan'))}")
        print(f"  budget 存在 = {bool(v.get('budget'))}")
        out = v.get("final_output") or ""
        print(f"  final_output[:80] = {out[:80]!r}")
    finally:
        model_client.chat_client.chat = orig


if __name__ == "__main__":
    modes = [sys.argv[1]] if len(sys.argv) > 1 else ["optional", "required", "invalid"]
    for m in modes:
        run_mode(m)
