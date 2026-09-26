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

# P8 demo 档单价表（元）——自用 Demo 是简化实现口径（开源组件/低代码/AI 辅助搭建），
# 不是外包交付价。旧逻辑 demo 档沿用外包价 → 3 千预算的方案永远「最低 1.3 万」，
# 与档位约束自相矛盾（这是「忽略预算持续输出复杂方案」在计价层的残留）。
DEMO_UNIT_PRICE = {
    "P0": (1_500, 3_000),
    "P1": (1_000, 2_000),
    "P2": (500, 1_000),
}

# 对接系统集成：每命中一类关键词的加价（元）
# 注意（T-1 定位结论）：「进销存」「库存系统」是产品域词——用户要做的系统
# 本身就是进销存（project_title「进销存管理系统」曾因此被当成对接目标，
# 虚增一类 3k-6k 加价）。真实对接表述必含「对接/打通/同步」语义，
# 由「现有系统对接」类兜住，产品域词不单独触发加价。
INTEGRATION_KEYWORDS = {
    "收银/POS 对接": ("收银", "pos", "收款机"),
    "支付对接": ("支付", "微信支付", "支付宝"),
    "ERP 对接": ("erp",),
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

# 参与 corpus 关键词扫描的 requirements 语义字段（白名单）。
# question_details / missing_info 是交互脚手架——带着问题原文（「需要和
# 现有系统打通吗？」）和未被用户选中的示例选项（「对接收银机」）；summary
# 常含否定句（「不用对接收银机，独立使用」）。关键词引擎没有否定语义，
# 全量 values() 扫描会把用户明确拒绝/没选的东西虚报成加价信号
# （T-1 定位：真实诊断曾虚增 3 类集成加价 9k-18k，见 scripts/t1_budget_trace.py）。
# 取舍：漏检（用户真要对接但功能清单没体现→后续人工沟通补报价）危害
# 远小于虚增（直接把报价抬高吓跑用户）。
REQ_TEXT_FIELDS = (
    "project_title", "business_type", "core_features", "target_users",
    "mentioned_budget", "mentioned_deadline", "pain_points",
)

# 最低报价兜底：低于这个数不现实
MIN_TOTAL = 20_000

# 成本敏感（用户表达「免费试用/便宜点/不想多花钱」）：最小可行方案口径，
# 最低报价兜底放宽——还按 2 万兜底会把「想先免费试试」的用户直接吓跑
COST_SENSITIVE_KEYWORDS = ("预算敏感", "低成本", "免费", "试用", "便宜", "省钱", "不想投入")
COST_SENSITIVE_MIN_TOTAL = 5_000


def _hit_keywords(text: str, keywords: tuple[str, ...]) -> bool:
    return any(k in text for k in keywords)


_BUDGET_NUM = re.compile(r"(\d+(?:\.\d+)?)\s*(万|w|W|k|K|千|块钱|元)?")


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
        elif unit in ("k", "K", "千") or unit in ("块钱", "元"):
            # 「3千」「3000块钱」「3000元」同一口径；万级写法优先（max 取大值兜底歧义）
            v *= 1_000 if unit == "千" else 1
        values.append(v)
    result = int(max(values))
    if result < 100 or result > 100_000_000:
        return None
    return result


def estimate_budget(plan: dict, requirements: dict | None, tier: dict | None = None) -> dict:
    """规则引擎入口：SolutionPlan dict → 预算 dict（可独立调用，便于测试）。

    tier：understand 节点写入的预算档位（P8），决定兜底价口径与 budget_match 措辞。
    """
    modules = plan.get("core_business_modules", [])
    stack_text = " ".join(
        f"{t.get('layer', '')}{t.get('choice', '')}" for t in plan.get("tech_stack", [])
    ).lower()
    feat_text = " ".join(m.get("description", "") for m in modules)
    req_text = ""
    if requirements:
        req_text = " ".join(
            str(requirements.get(k) or "") for k in REQ_TEXT_FIELDS
        )
    corpus = f"{feat_text} {req_text}".lower()

    line_items: list[BudgetLineItem] = []
    assumptions: list[str] = []

    # 1. 模块计价：优先级 × 数量（P8：demo 档用自用口径低价表，外包价只用于 mid/pro）
    tier_name = (tier or {}).get("tier") if tier else None
    price_table = DEMO_UNIT_PRICE if tier_name == "demo" else UNIT_PRICE
    total_min = total_max = 0
    for m in modules:
        lo, hi = price_table.get(m.get("priority", "P1"), price_table["P1"])
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
    # 成本敏感判定只看 mentioned_budget 字段（用户预算口径），
    # 不能扫全部需求文本——core_features 里的「免费试用 7 天」是产品功能，不是预算态度
    mentioned_raw = str((requirements or {}).get("mentioned_budget") or "")
    cost_sensitive = _hit_keywords(mentioned_raw.lower(), COST_SENSITIVE_KEYWORDS)

    # P8 预算档位兜底：档位决定「最低可行成本」口径——
    # demo（≤5千/自用）按最小 Demo 价兜底，mid 按 8 千兜底，pro/未提按 2 万兜底。
    # 旧逻辑一律 2 万兜底，把「预算 8 千」的用户直接判「低于最低可行成本」，
    # 这是「忽略预算持续输出复杂方案」的直接原因之一。
    tier_name = (tier or {}).get("tier") if tier else None
    if tier_name == "demo":
        floor = 3_000  # 自用 Demo 口径（模块单价已按 demo 表压低）
    elif tier_name == "mid":
        floor = 8_000
    else:
        floor = COST_SENSITIVE_MIN_TOTAL if cost_sensitive else MIN_TOTAL
    total_min = max(total_min, floor)
    total_max = max(total_max, total_min + 5_000)  # 区间至少拉开 5k
    if cost_sensitive or tier_name == "demo":
        assumptions.append(
            "用户预算敏感（希望低成本），按最小可行方案测算："
            "建议先上 P0 核心功能验证价值，再分期扩展"
        )

    # 5.5 用户明确预算硬约束：报价必须以用户口径为准，不得自说自话
    #   - 预算可信（≥ 档位最低可行成本）：区间收敛进预算，上限贴预算（预算驱动范围）
    #   - 预算过低（< 档位最低可行成本）：区间保持现实成本，budget_match 明确警示
    user_budget = parse_budget((requirements or {}).get("mentioned_budget"))
    if user_budget:
        if total_max > user_budget >= floor:
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

    # 6. 与用户提及预算对比（P8：档位决定口径，不再一律按 2 万最低成本说话）
    mentioned = (requirements or {}).get("mentioned_budget")
    tier_label = (tier or {}).get("label") if tier else None
    if user_budget:
        if total_max <= user_budget and total_max > user_budget * 0.3:
            budget_match = f"用户明确预算「{mentioned}」，测算区间 {total_min}-{total_max} 元，在预算内"
        elif user_budget < floor:
            budget_match = (
                f"用户预算「{mentioned}」低于该规模方案的最低可行成本（{floor} 元），"
                "需向用户说明并协商进一步缩减需求范围"
            )
        else:
            budget_match = (
                f"用户明确预算「{mentioned}」，测算区间 {total_min}-{total_max} 元"
                "（预算较充足，可覆盖更多 P1/P2 功能或预留迭代资金）"
            )
    elif mentioned:
        if cost_sensitive:
            budget_match = (
                f"用户预算态度：「{mentioned}」，未给具体金额。"
                f"已按最小可行方案测算，区间 {total_min}-{total_max} 元"
            )
        else:
            budget_match = (
                f"用户提及预算「{mentioned}」但无法解析具体金额，"
                f"测算区间为 {total_min}-{total_max} 元，需与用户确认"
            )
    else:
        budget_match = "用户未提及预算"

    # 档位信息随预算结果下发（前端徽章 / 方案页标注用）
    if tier_label:
        budget_match = f"【{tier_label}】{budget_match}"

    result = BudgetEstimate(
        total_min=total_min,
        total_max=total_max,
        line_items=line_items,
        assumptions=assumptions,
        budget_match=budget_match,
    ).model_dump()
    if tier:
        result["tier"] = {
            "tier": tier.get("tier"),
            "label": tier.get("label"),
            "mentioned": tier.get("mentioned"),
            "recap": tier.get("recap"),
        }
    return result


def budget_node(state: DiagnosisState) -> dict:
    """预算测算节点：读 plan（+requirements+budget_tier），写 budget。"""
    plan = state.get("plan")
    if not plan:
        return {"error": "预算测算失败：缺少方案信息"}

    # 免费试试（free 档）：不产生任何开发报价（产品规则：主方案不含预算）
    tier = state.get("budget_tier") or {}
    if tier.get("tier") == "free":
        logger.info("[budget] free 档 → 跳过报价测算")
        return {"budget": None}

    budget = estimate_budget(plan, state.get("requirements"), tier=tier)
    logger.info(
        "[budget] range=%d-%d items=%d",
        budget["total_min"], budget["total_max"], len(budget["line_items"]),
    )
    return {"budget": budget}
