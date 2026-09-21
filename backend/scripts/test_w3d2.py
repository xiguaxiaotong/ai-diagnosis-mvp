"""Week3 Day2 验收：feasibility 可行性评估 + output 汇总节点。

验收标准：完整方案对象生成，持久化到 SQLite。
流程：创建项目 → 全图 invoke（模糊需求 → 追问 → 回答 → 方案/预算/评估/汇总）
     → 断言 state 有完整方案对象 → 断言 SQLite 中项目已更新。

用法（在 backend/ 目录下运行，需要 DEEPSEEK_API_KEY）：
    python scripts/test_w3d2.py
"""

import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.types import Command  # noqa: E402

from app.agent.graph import diagnosis_graph  # noqa: E402
from app.config import DEEPSEEK_API_KEY  # noqa: E402
from app.db.database import SessionLocal, init_db  # noqa: E402
from app.db.models import Project  # noqa: E402
from app.services import project_service  # noqa: E402

ANSWER_1 = (
    "三家门店，每家店一天大概 200 单；要做微信小程序；"
    "需要对接店里现有的收银系统；预算两三万，希望一个月内上线"
)
ANSWER_2 = (
    "补充：系统主要给顾客和店员用，需要基础的订单管理和核销；"
    "不用对接外卖平台，数据存自己服务器"
)


def main() -> None:
    if not DEEPSEEK_API_KEY or "你的" in DEEPSEEK_API_KEY:
        print("❌ 请先在 .env 中配置 DEEPSEEK_API_KEY")
        sys.exit(1)

    # ========== 准备：建库 + 建项目（模拟前端先创建项目再发起诊断） ==========
    init_db()
    db = SessionLocal()
    project = project_service.create_project(db, title="点单小程序", raw_idea="我想做个点单小程序")
    project_id = project.id
    db.close()
    print(f"已创建项目 id={project_id}（status=diagnosing）")

    cfg = {"configurable": {"thread_id": f"test-w3d2-{project_id}"}}
    idea = "我想做个点单小程序"

    # ========== 第 1 步：发起诊断 ==========
    s = diagnosis_graph.invoke(
        {
            "project_id": project_id,
            "raw_idea": idea,
            "messages": [{"role": "user", "content": idea}],
        },
        cfg,
    )
    assert s.get("error") is None, f"节点报错: {s.get('error')}"

    # ========== 第 2 步：追问循环 ==========
    for answer in (ANSWER_1, ANSWER_2):
        if not s.get("needs_clarify"):
            break
        print(f"\n【追问】{s['clarify_questions']}")
        s = diagnosis_graph.invoke(Command(resume=answer), cfg)
        assert s.get("error") is None, f"节点报错: {s.get('error')}"

    # ========== 第 3 步：state 完整方案对象断言 ==========
    assert s.get("full_solution"), "完整方案对象未生成"
    sol = s["full_solution"]
    for key in ("requirements", "plan", "budget", "feasibility", "final_output"):
        assert sol.get(key), f"完整方案对象缺少 {key}"
    feas = sol["feasibility"]
    assert feas["overall"] in ("可行", "有条件可行", "风险较高"), f"overall 非法: {feas['overall']}"
    assert feas["risk_level"] in ("低", "中", "高"), f"risk_level 非法: {feas['risk_level']}"
    assert 2 <= len(feas["suggestions"]) <= 4, "落地建议应 2-4 条"
    assert s["final_output"], "final_output 未生成"
    print(f"\n✅ state 完整方案对象 OK（feasibility={feas['overall']}/风险{feas['risk_level']}）")

    # ========== 第 4 步：SQLite 持久化断言 ==========
    db = SessionLocal()
    try:
        p = project_service.get_project(db, project_id)
        assert p is not None, "项目丢失"
        assert p.status == Project.STATUS_PLAN_GENERATED, f"状态未推进: {p.status}"
        assert p.plan, "plan 字段未写入"
        stored = json.loads(p.plan)
        assert stored["plan"]["project_name"], "持久化的方案 JSON 不完整"
        assert stored["budget"]["total_min"] > 0, "持久化预算缺失"
        assert stored["feasibility"]["overall"] == feas["overall"], "持久化评估与 state 不一致"
        assert p.budget_min == stored["budget"]["total_min"], "budget_min 未写入"
        assert p.budget_max == stored["budget"]["total_max"], "budget_max 未写入"
    finally:
        db.close()
    print(f"✅ SQLite 持久化 OK（status={p.status}, budget={p.budget_min:.0f}-{p.budget_max:.0f} 元）")

    # ========== 展示 final_output ==========
    print("\n" + "=" * 20, "final_output（面向用户）", "=" * 20)
    print(s["final_output"])
    print("=" * 60)
    print("✅ Week3 Day2 验收通过（feasibility + output + SQLite 持久化）")


if __name__ == "__main__":
    main()
