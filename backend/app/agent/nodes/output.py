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
from app.infra import stream_sink
from app.db.models import Project
from app.services import project_service

logger = logging.getLogger(__name__)

# 可行性结论 → 大白话（产品规则：杜绝评估报告腔）
FEAS_PLAIN = {
    "可行": "能做成",
    "有条件可行": "基本能做成，但有几个要注意的点",
    "风险较高": "做之前要想清楚，坑不少",
}
RISK_PLAIN = {"低": "风险小", "中": "有些地方要注意", "高": "坑比较多"}


def _build_final_output(state: DiagnosisState) -> str:
    """三段式通俗总结（B 组排版）：①能干啥 ②解决麻烦 ③成本工作量。

    面向不懂技术的客户：杜绝术语、长句拆短、关键信息前置；
    final_output 在对话页直接展示，是用户看到方案的第一眼。
    """
    plan, budget, feas = state.get("plan", {}), state.get("budget"), state.get("feasibility", {})
    modules = plan.get("core_business_modules", [])
    p0 = [m["name"] for m in modules if m.get("priority") == "P0"]
    tier = state.get("budget_tier") or {}
    is_free = tier.get("tier") == "free"
    pain_points = state.get("confirmed_pain_points") or []
    phases = plan.get("implementation_phases", [])

    lines: list[str] = []

    # 一句话大白话总结置顶（产品规则 #7：方案最开头先放一句总结）
    lines.append("📋 方案完成：《%s》" % plan.get("project_name", "未命名项目"))
    lines.append("")
    if plan.get("one_liner"):
        lines.append(f"💡 一句话总结：{plan['one_liner']}")
        lines.append("")
    lines.append(f"① 这个方案能干啥：{plan.get('business_summary', '')}")

    # ② 能解决的麻烦：对应确认的痛点（用户勾选过的最优先），没有就归纳模块
    lines.append("")
    lines.append("② 能帮你解决的麻烦：")
    if pain_points:
        lines.extend(f"  ✓ {p}" for p in pain_points[:4])
    else:
        lines.extend(f"  ✓ {m['description']}" for m in modules if m.get("priority") == "P0")

    # ③ 免费版讲「下一步怎么做」，付费版讲「花多少钱、多长时间」（产品规则 #1/#4）
    lines.append("")
    if is_free or not budget:
        lines.append("③ 下一步怎么做：先用方案里推荐的现成免费工具跑起来，够用就不花钱；")
        lines.append("  想知道花钱找人开发大概要多少钱，直接问我，我再给你报价参考 👌")
    else:
        cost = (
            f"③ 花多少钱、多长时间：预算约 {budget.get('total_min', 0):,} - {budget.get('total_max', 0):,} 元"
        )
        if phases:
            cost += f"，建议分 {len(phases)} 步走，第一步先做好：{p0[0] if p0 else '最核心的功能'}，其他以后再加"
        lines.append(cost)
    if tier:
        lines.append(f"  🎯 {tier.get('recap') or tier.get('label')}")
    overall = FEAS_PLAIN.get(feas.get("overall", ""), feas.get("overall", ""))
    risk = RISK_PLAIN.get(feas.get("risk_level", ""), feas.get("risk_level", ""))
    lines.append(f"  能不能做成：{overall or '待评估'}（{risk or '待评估'}）")

    lines.append("")
    lines.append(f"核心功能：{'、'.join(p0) if p0 else '见方案详情'}")
    lines.append("详细方案已生成，可打开方案页查看。" if is_free else "详细方案和预算明细已生成，可打开方案页查看。")

    suggestions = feas.get("suggestions", [])
    if suggestions:
        lines.append("【给你的建议】")
        lines.extend(f"  {i}. {s}" for i, s in enumerate(suggestions, 1))
    return "\n".join(lines)


def _persist(project_id: int | None, solution: dict) -> None:
    """把完整方案写入 SQLite；无 project_id（如纯图测试）则跳过。

    免费思路版没有 budget（产品规则：不报价）→ 预算区间列存 NULL。
    """
    if not project_id:
        logger.warning("[output] state 无 project_id，跳过持久化")
        return
    budget = solution.get("budget")
    fields: dict = {
        "plan": json.dumps(solution, ensure_ascii=False),
        "status": Project.STATUS_PLAN_GENERATED,
    }
    if budget:
        fields["budget_min"] = float(budget["total_min"])
        fields["budget_max"] = float(budget["total_max"])
    db = SessionLocal()
    try:
        updated = project_service.update_project(db, project_id, **fields)
        if updated is None:
            logger.error("[output] 项目不存在: id=%s，跳过持久化", project_id)
    finally:
        db.close()


def output_node(state: DiagnosisState) -> dict:
    """汇总节点：生成完整方案对象 + final_output 文本 + 持久化。

    错误兜底：当 plan/budget 缺失（上游 generate/budget 节点失败）时，
    不让图直接停在空 reply 的 wait_confirmation 让用户摸不着头脑，
    而是返回显式错误提示给用户，让用户有机会选择「重新尝试」或「收尾」。

    免费思路版没有 budget 是正常状态（产品规则：不报价），不算缺项。
    """
    is_free = (state.get("budget_tier") or {}).get("tier") == "free"
    required = ["requirements", "plan"] + ([] if is_free else ["budget"])
    missing = [k for k in required if not state.get(k)]
    if missing:
        err = state.get("error") or "生成方案时出现异常"
        final_output = (
            f"抱歉，方案生成过程中遇到了点问题（{err}）。\n\n"
            "您可以告诉我哪里需要调整（我会再试一次），或者直接告诉我「不要了」结束这次诊断。"
        )
        logger.error("[output] 缺少 %s，错误兜底：%s", missing, err)
        return {"final_output": final_output, "full_solution": None, "error": err}

    final_output = _build_final_output(state)
    # 方案摘要实时流出（service 层做打字机节奏），不再等图收尾后一次性推送
    stream_sink.emit(final_output)

    solution = {
        "requirements": state["requirements"],
        "plan": state["plan"],
        "budget": state["budget"],
        "feasibility": state.get("feasibility"),  # 评估失败不阻塞汇总
        "final_output": final_output,
        # B 组排版：方案页三段式总结要用（痛点回应 + 预算档位标注）
        "confirmed_pain_points": state.get("confirmed_pain_points") or [],
        "budget_tier": state.get("budget_tier"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    _persist(state.get("project_id"), solution)

    logger.info("[output] project_id=%s 汇总完成（%d 字摘要）",
                state.get("project_id"), len(final_output))
    return {"final_output": final_output, "full_solution": solution}
