"""预算测算节点：方案 → 预算区间 + 明细（纯规则引擎，不调 LLM）。

验收标准（Week3 Day1）：给定方案能算出预算 JSON。
设计考量：
- 确定性：同输入必同输出，可单测、可解释、零 token 成本
- 区间输出：商业计划书硬性要求，避免定值报价带来的承诺风险
- 明细可解释：每一项钱都有计价依据，方便向用户解释报价构成

计价规则（元）：
- 模块单价按优先级：P0 8000-12000 / P1 5000-8000 / P2 3000-5000
- 对接系统集成：每命中一类关键词 +3000-6000（收银/支付/ERP/短信/物流...）
- 多端覆盖：App/iOS/安卓 命中 +10000-20000（小程序/网页不加价）
- 加急工期：用户提及 ≤1 个月上线 +10%-20%
"""

import logging
import re

from app.agent.schemas import BudgetEstimate, BudgetLineItem
from app.agent.state import DiagnosisState

logger = logging.getLogger(__name__)

# 模块单价表（元）——MVP 规模的外包定价参考
UNIT_PRICE = {
    "P0": (8_000, 12_000),
    "P1": (5_000, 8_000),
    "P2": (3_000, 5_000),
}

# 对接系统集成：每命中一类关键词的加价（元）
INTEGRATION_KEYWORDS = {
    "收银/POS 对接": ("收银", "pos", "收款机"),
    "支付对接": ("支付", "微信支付", "支付宝"),
    "ERP/进销存对接": ("erp", "进销存", "库存系统"),
    "会员/CRM 对接": ("会员系统", "crm"),
    "短信/消息服务": ("短信", "消息推送", "通知服务"),
    "物流/外卖平台对接": ("物流", "外卖", "配送对接"),
    "现有系统对接": ("对接", "现有系统", "原有系统"),
}
INTEGRATION_PRICE = (3_000, 6_000)

# 多端覆盖加价（App 比小程序贵得多）
MULTI_PLATFORM_KEYWORDS = ("app", "ios", "安卓", "android", "原生")
MULTI_PLATFORM_PRICE = (10_000, 20_000)

# 加急判定：提及一个月内上线
URGENT_KEYWORDS = ("一个月内", "两周", "2 周", "两周内", "尽快上线", "加急")
URGENT_RATE = (0.10, 0.20)

# 最低报价兜底：低于这个数不现实
MIN_TOTAL = 20_000


def _hit_keywords(text: str, keywords: tuple[str, ...]) -> bool:
    return any(k in text for k in keywords)


_BUDGET_NUM = re.compile(r"(\d+(?:\.\d+)?)\s*(万|w|W|k|K)?")


def parse_budget(mentioned) -> int | None:
    """从用户表述中解析预算上限（元）。

    「10万」「10w」「100000」「预算 5-8 万」「1000块钱」→ 100000 / 100000 / 100000 / 80000 / 1000。
    区间取较大值（预算上限口径）；解析不出或数值明显不是金额（<100 或 >1 亿）返回 None。
    """
    if not mentioned:
        return None
    text = str(mentioned).replace(",", "").replace("，", "")
    matches = _BUDGET_NUM.findall(text)
    if not matches:
        return None
    values = []
    for num, unit in matches:
        v = float(num)
        if unit in ("万", "w", "W"):
            v *= 10_000
        elif unit in ("k", "K"):
            v *= 1_000
        values.append(v)
    result = int(max(values))
    if result < 100 or result > 100_000_000:
        return None
    return result


def estimate_budget(plan: dict, requirements: dict | None) -> dict:
    """规则引擎入口：SolutionPlan dict → 预算 dict（可独立调用，便于测试）。"""
    modules = plan.get("core_business_modules", [])
    stack_text = " ".join(
        f"{t.get('layer', '')}{t.get('choice', '')}" for t in plan.get("tech_stack", [])
    ).lower()
    feat_text = " ".join(m.get("description", "") for m in modules)
    req_text = ""
    if requirements:
        req_text = " ".join(
            str(v) for v in requirements.values() if isinstance(v, (str, list))
        )
    corpus = f"{feat_text} {req_text}".lower()

    line_items: list[BudgetLineItem] = []
    assumptions: list[str] = []

    # 1. 模块计价：优先级 × 数量
    total_min = total_max = 0
    for m in modules:
        lo, hi = UNIT_PRICE.get(m.get("priority", "P1"), UNIT_PRICE["P1"])
        line_items.append(BudgetLineItem(
            item=f"{m.get('name', '未命名模块')}（{m.get('priority', 'P1')} 模块）",
            basis=f"{m.get('priority', 'P1')} 模块单价 {lo}-{hi} 元",
            min_amount=lo, max_amount=hi,
        ))
        total_min += lo
        total_max += hi

    # 2. 对接集成加价：按命中类别逐项计
    hit_names = [name for name, kws in INTEGRATION_KEYWORDS.items() if _hit_keywords(corpus, kws)]
    for name in hit_names:
        lo, hi = INTEGRATION_PRICE
        line_items.append(BudgetLineItem(
            item=f"系统集成：{name}",
            basis=f"第三方对接加价 {lo}-{hi} 元/类",
            min_amount=lo, max_amount=hi,
        ))
        total_min += lo
        total_max += hi

    # 3. 多端覆盖加价
    if _hit_keywords(stack_text, MULTI_PLATFORM_KEYWORDS):
        lo, hi = MULTI_PLATFORM_PRICE
        line_items.append(BudgetLineItem(
            item="多端覆盖（App/iOS/安卓）",
            basis=f"多端开发加价 {lo}-{hi} 元",
            min_amount=lo, max_amount=hi,
        ))
        total_min += lo
        total_max += hi

    # 4. 加急工期上浮
    if _hit_keywords(req_text, URGENT_KEYWORDS):
        rush_lo = int(total_min * URGENT_RATE[0])
        rush_hi = int(total_max * URGENT_RATE[1])
        line_items.append(BudgetLineItem(
            item="加急工期上浮",
            basis=f"工期紧张，整体上浮 {URGENT_RATE[0]:.0%}-{URGENT_RATE[1]:.0%}",
            min_amount=rush_lo, max_amount=rush_hi,
        ))
        total_min += rush_lo
        total_max += rush_hi
        assumptions.append("用户提及工期较紧，按加急上浮测算")

    # 5. 兜底与取整（千元）
    total_min = max(total_min, MIN_TOTAL)
    total_max = max(total_max, total_min + 5_000)  # 区间至少拉开 5k

    # 5.5 用户明确预算硬约束：报价必须以用户口径为准，不得自说自话
    #   - 预算可信（≥ 最低可行成本）：区间收敛进预算，上限贴预算（预算驱动范围）
    #   - 预算过低（< 最低可行成本）：区间保持现实成本，budget_match 明确警示
    user_budget = parse_budget((requirements or {}).get("mentioned_budget"))
    if user_budget:
        if total_max > user_budget >= MIN_TOTAL:
            # 超出预算：收敛到预算内，并提示裁剪需求
            total_min = min(total_min, int(user_budget * 0.6))
            total_max = user_budget
            assumptions.append(
                f"用户明确预算 {user_budget} 元，报价已收敛至预算内；"
                "建议砍掉 P1/P2 模块或分期实施以匹配成本"
            )
        elif total_max <= user_budget:
            # 预算充足：上限贴用户预算（外包报价常规：预算决定范围），但防止虚高
            total_max = min(user_budget, max(total_max, total_min * 2))
            assumptions.append(f"用户明确预算 {user_budget} 元，报价上限按预算口径收敛")

    total_min = round(total_min, -3)
    total_max = round(total_max, -3)

    if hit_names:
        assumptions.append(f"需要对接 {len(hit_names)} 类第三方系统，按类别加价")
    assumptions.append("按 MVP 规模测算；超出 MVP 范围的需求（大数据量、高并发）需重新评估")

    # 6. 与用户提及预算对比
    mentioned = (requirements or {}).get("mentioned_budget")
    if user_budget:
        if total_max <= user_budget and total_max > user_budget * 0.3:
            budget_match = f"用户明确预算「{mentioned}」，测算区间 {total_min}-{total_max} 元，在预算内"
        elif user_budget < MIN_TOTAL:
            budget_match = (
                f"用户预算「{mentioned}」低于最低可行成本（{MIN_TOTAL} 元），"
                "该金额无法交付完整方案，需向用户说明并协商缩减需求范围"
            )
        else:
            budget_match = (
                f"用户明确预算「{mentioned}」，测算区间 {total_min}-{total_max} 元"
                "（预算较充足，可覆盖更多 P1/P2 功能或预留迭代资金）"
            )
    elif mentioned:
        budget_match = f"用户提及预算「{mentioned}」但无法解析具体金额，测算区间为 {total_min}-{total_max} 元，需与用户确认"
    else:
        budget_match = "用户未提及预算"

    return BudgetEstimate(
        total_min=total_min,
        total_max=total_max,
        line_items=line_items,
        assumptions=assumptions,
        budget_match=budget_match,
    ).model_dump()


def budget_node(state: DiagnosisState) -> dict:
    """预算测算节点：读 plan（+requirements），写 budget。"""
    plan = state.get("plan")
    if not plan:
        return {"error": "预算测算失败：缺少方案信息"}

    budget = estimate_budget(plan, state.get("requirements"))
    logger.info(
        "[budget] range=%d-%d items=%d",
        budget["total_min"], budget["total_max"], len(budget["line_items"]),
    )
    return {"budget": budget}
