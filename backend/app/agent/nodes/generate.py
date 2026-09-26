"""方案生成节点：结构化需求 → 业务方案 + 技术方案（SolutionPlan JSON）。

验收标准（Week2 Day4）：需求完整后能生成方案 JSON。
与 understand 节点同款容错：json_object 强制 JSON → 失败退化普通调用 →
_extract_json 剥围栏 → Pydantic 校验。

T-2（W9）输出异常分级处理（不要一刀切全兜底）：
- 可选字段缺失（one_liner / glossary / 模块 example）：pydantic 默认值
  就是安全默认，自动补齐主流程继续，logger.warning 留痕；
- 必填字段缺失 / 非法 JSON / 字段类型不合法：点名问题重试一次
  （重试 prompt 附「上次输出的问题」清单，LLM 不用猜哪里错了），
  仍失败才走 error 兜底，文案记明「重试后仍缺 X」。
  背景：真实诊断中 generate 偶发漏模块 priority 字段（temperature=0.3 的
  输出不确定性），单次格式偏差曾把整条方案链打进 error 兜底——
  见 backend/docs/TODO.md T-2 与 scripts/t2_generate_repro.py 复现。
"""

import json
import logging
import re
from typing import Any

from pydantic import ValidationError

from app.agent.nodes.understand import extract_json
from app.agent.prompt_loader import render
from app.agent.schemas import SolutionPlan
from app.agent.state import DiagnosisState
from app.infra.model_client import chat_client

logger = logging.getLogger(__name__)

# 顶层可选字段（pydantic 已有安全默认值，缺失不阻断主流程）
_TOP_OPTIONAL = ("one_liner", "glossary")


def _call_llm(prompt: str) -> str:
    """统一调用入口：json_object 强制 JSON，不支持的中转层退化普通调用。"""
    try:
        return chat_client.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            response_format={"type": "json_object"},
        )
    except Exception:
        logger.warning("response_format=json_object 调用失败，退化为普通调用")
        return chat_client.chat([{"role": "user", "content": prompt}], temperature=0.3)


def _plan_problems(answer: str) -> tuple[dict[str, Any] | None, list[str]]:
    """LLM 原始输出 → (data, 问题清单)；清单为空 = 可直接建 SolutionPlan。

    问题清单可读化（直接拼进重试 prompt / error 文案）：
    - 非法 JSON / 非 JSON 对象 → 一条总述；
    - 校验失败 → 逐条「缺少必填字段 X」/「字段 X 不合法：原因」，
      序列下标归一（core_business_modules.0.priority → [].priority）后去重，
      避免 5 个模块漏同一字段刷 5 条。
    """
    try:
        data = json.loads(extract_json(answer))
    except json.JSONDecodeError as e:
        return None, [f"输出不是合法 JSON（{e}）"]
    if not isinstance(data, dict):
        return None, ["输出不是 JSON 对象"]

    try:
        SolutionPlan.model_validate(data)
        return data, []
    except ValidationError as e:
        problems: list[str] = []
        for err in e.errors():
            loc = re.sub(r"\.\d+", "[]", ".".join(str(x) for x in err["loc"]))
            if err["type"] == "missing":
                msg = f"缺少必填字段 {loc}"
            else:
                msg = f"字段 {loc} 不合法：{err['msg']}"
            if msg not in problems:
                problems.append(msg)
        return data, problems


def generate_node(state: DiagnosisState) -> dict[str, Any]:
    """基于 requirements 生成 SolutionPlan，返回状态增量 {"plan": ...}。"""
    requirements = state.get("requirements")
    if not requirements:
        return {"error": "方案生成失败：缺少需求信息"}

    # 用户确认循环中的修改要求（首轮生成时为空）
    feedback = (state.get("revision_feedback") or "").strip()
    feedback_section = f"\n## 用户修改要求（必须落实到方案中）\n\n{feedback}\n" if feedback else ""

    # 相似历史案例（retrieve 节点写入；空则不加该段）
    cases = state.get("retrieved_cases") or []
    cases_section = ""
    if cases:
        lines = []
        for c in cases:
            # 行业标签存在才拼（嵌套 f-string 复用双引号是 py3.12 语法，改用中间变量兼容 3.11）
            head = f"[{c['industry']}] " if c.get("industry") else ""
            lines.append(f"- 《{c['title']}》{head}{c['summary']}（相似度 {c['score']:.2f}）")
        cases_section = "\n## 相似历史案例（真实项目复盘，供参考）\n\n" + "\n".join(lines) + "\n"
        logger.info("[generate] 注入 %d 个相似案例", len(cases))

    # 预算档位硬约束（P8）：预算一旦提及全程锁定，方案复杂度不得越档
    tier = state.get("budget_tier")
    budget_section = (
        f"\n## 预算档位约束（硬性边界，必须遵守）\n\n"
        f"用户原话：「{tier['mentioned']}」，档位：{tier['label']}\n"
        f"{tier['guidance']}\n"
        if tier else ""
    )

    # A 组痛点（用户勾选确认过）：方案要正面回应每条痛点
    pain_points = state.get("confirmed_pain_points") or []
    pain_section = (
        "\n## 用户确认的痛点（方案必须逐条回应）\n\n"
        + "\n".join(f"- {p}" for p in pain_points)
        + "\n在 business_summary 与模块 description 中说明对应模块解决了哪条痛点。\n"
        if pain_points else ""
    )

    prompt = render(
        "generate",
        requirements_json=json.dumps(requirements, ensure_ascii=False, indent=2),
        budget_constraint=budget_section,
        pain_points_section=pain_section,
        revision_feedback=feedback_section,
        similar_cases=cases_section,
    )

    # T-2 分级容错：首次不合格 → 点名问题重试一次 → 仍失败才 error 兜底
    data, problems = _plan_problems(_call_llm(prompt))
    if problems:
        retry_note = (
            "\n## 上次输出的问题（本次必须修正）\n\n"
            + "\n".join(f"- {p}" for p in problems)
            + "\n请重新输出完整的方案 JSON，结构与字段要求不变，"
            "必须补上/修正上述字段。\n"
        )
        logger.warning("[generate] 首次输出不合格，点名重试一次：%s", "；".join(problems))
        data, problems = _plan_problems(_call_llm(prompt + retry_note))
    if problems:
        logger.error("[generate] 重试后仍不合格，放弃：%s", "；".join(problems))
        return {"error": f"方案生成失败（重试后仍缺：{'；'.join(problems)}）"}
    assert data is not None  # problems 为空 ⇔ 解析成功（给 mypy 收窄，运行时恒真）

    # 可选字段缺失：pydantic 默认值补齐，主流程继续（warning 留痕）
    missing_optional = [k for k in _TOP_OPTIONAL if k not in data]
    modules = data.get("core_business_modules") or []
    if any(isinstance(m, dict) and "example" not in m for m in modules):
        missing_optional.append("core_business_modules[].example")
    if missing_optional:
        logger.warning("[generate] 可选字段缺失，已按默认值补齐：%s", "、".join(missing_optional))

    plan = SolutionPlan.model_validate(data)
    logger.info(
        "[generate] project=%s modules=%d stack=%d phases=%d",
        plan.project_name, len(plan.core_business_modules),
        len(plan.tech_stack), len(plan.implementation_phases),
    )
    return {"plan": plan.model_dump()}
