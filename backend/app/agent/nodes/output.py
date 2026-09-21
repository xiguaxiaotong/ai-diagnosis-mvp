"""方案汇总节点：拼装完整方案对象 + 持久化到 SQLite。

验收标准（Week3 Day2）：完整方案对象生成，持久化到 SQLite。
- 汇总是确定性拼接（不调 LLM）：requirements + plan + budget + feasibility
- final_output：面向用户的纯文本摘要（前端对话页直接展示）
- 持久化：project.plan 存完整方案 JSON，budget_min/max 存区间，状态推进到 plan_generated
"""

import json
import logging
from datetime import datetime

from app.agent.state import DiagnosisState
from app.db.database import SessionLocal
from app.db.models import Project
from app.services import project_service

logger = logging.getLogger(__name__)


def _build_final_output(state: DiagnosisState) -> str:
    """确定性拼接面向用户的方案摘要文本。"""
    plan, budget, feas = state.get("plan", {}), state.get("budget", {}), state.get("feasibility", {})
    modules = plan.get("core_business_modules", [])
    p0 = [m["name"] for m in modules if m.get("priority") == "P0"]

    lines = [
        f"📋 方案完成：《{plan.get('project_name', '未命名项目')}》",
        "",
        f"【业务方案】{plan.get('business_summary', '')}",
        f"【核心模块】{'、'.join(p0) if p0 else '见方案详情'}",
        f"【预算区间】{budget.get('total_min', 0):,} - {budget.get('total_max', 0):,} 元"
        f"（明细 {len(budget.get('line_items', []))} 项，可解释报价构成）",
        f"【可行性】{feas.get('overall', '待评估')}（风险{feas.get('risk_level', '-')}）"
        f"—— {feas.get('tech_assessment', '')}",
    ]
    suggestions = feas.get("suggestions", [])
    if suggestions:
        lines.append("【落地建议】")
        lines.extend(f"  {i}. {s}" for i, s in enumerate(suggestions, 1))
    return "\n".join(lines)


def _persist(project_id: int | None, solution: dict) -> None:
    """把完整方案写入 SQLite；无 project_id（如纯图测试）则跳过。"""
    if not project_id:
        logger.warning("[output] state 无 project_id，跳过持久化")
        return
    budget = solution["budget"]
    db = SessionLocal()
    try:
        updated = project_service.update_project(
            db,
            project_id,
            plan=json.dumps(solution, ensure_ascii=False),
            budget_min=float(budget["total_min"]),
            budget_max=float(budget["total_max"]),
            status=Project.STATUS_PLAN_GENERATED,
        )
        if updated is None:
            logger.error("[output] 项目不存在: id=%s，跳过持久化", project_id)
    finally:
        db.close()


def output_node(state: DiagnosisState) -> dict:
    """汇总节点：生成完整方案对象 + final_output 文本 + 持久化。"""
    missing = [k for k in ("requirements", "plan", "budget") if not state.get(k)]
    if missing:
        return {"error": f"方案汇总失败：缺少 {'、'.join(missing)}"}

    final_output = _build_final_output(state)

    solution = {
        "requirements": state["requirements"],
        "plan": state["plan"],
        "budget": state["budget"],
        "feasibility": state.get("feasibility"),  # 评估失败不阻塞汇总
        "final_output": final_output,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    _persist(state.get("project_id"), solution)

    logger.info("[output] project_id=%s 汇总完成（%d 字摘要）",
                state.get("project_id"), len(final_output))
    return {"final_output": final_output, "full_solution": solution}
