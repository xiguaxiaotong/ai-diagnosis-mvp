"""预算档位：用户预算 → 全局约束（demo / mid / pro），贯穿理解→追问→生成→汇总。

产品逻辑（P8 需求）：
- 预算是全局记忆参数：一旦用户提到预算，全程锁定（understand 每轮刷新，
  用户改口时新值覆盖），所有节点读同一份 tier 判断
- 三档分级：
    demo  ≤ 5,000 / 表达成本敏感     → 自用 Demo：最小可用、开源组件、本地部署，
                                       砍掉商用模块，不推荐付费云服务
    mid   5,000 < x ≤ 10,000        → 轻量生产：单机 + 必要云服务，砍高并发
    pro   > 10,000                  → 完整生产：全模块 + 分期实施
- 档位一旦确定随会话持久（LangGraph checkpointer 自动落盘）

设计考量：
- 纯规则零 LLM：分类确定性、可单测、零 token 成本
- recap 文案面向普通用户（无术语）；guidance 文案喂给 generate prompt
"""

import logging

from app.agent.nodes.budget import parse_budget

logger = logging.getLogger(__name__)

# 档位边界（元）
DEMO_MAX = 5_000
MID_MAX = 10_000

# 成本敏感关键词（与 budget.py 的 COST_SENSITIVE_KEYWORDS 同源口径）
# 「几百」「预算有限」等模糊低预算表述也视同 demo 档信号
COST_SENSITIVE = ("预算敏感", "低成本", "试用", "便宜", "省钱", "小成本", "几百", "预算有限", "没多少预算")

# 免费试试关键词：命中 → free 档（只出思路和现成工具，不报价），优先级最高
FREE_KEYWORDS = (
    "免费试试", "免费", "不花钱", "不想花钱", "零成本", "不想投入",
    "先不投入", "不打算花钱", "先试试", "先免费",
)


TIERS: dict[str, dict] = {
    "free": {
        "label": "免费思路版",
        # generate prompt 注入的硬约束（产品规则：免费试试不输出付费开发报价）
        "guidance": (
            "用户选择「免费试试」：只要思路方案，不做开发报价。方案必须遵守：\n"
            "- 严禁输出任何开发金额、预算区间、工期承诺、分期交付计划"
            "（implementation_phases 必须是空数组 []）\n"
            "- 方案内容 = ①这个需求可以怎么做（功能思路）②推荐现成的免费工具"
            "（如 Obsidian、Notion、飞书多维表格、微信小程序免费额度等，贴合需求选）"
            "③如果以后想开发，功能先做什么后做什么\n"
            "- tech_stack 给「现成免费工具 / 免费方案」而不是外包开发选型，"
            "reason 说明怎么免费用起来\n"
            "- key_risks 只提示使用现成工具的注意点（如：数据存在本地，"
            "电脑坏了会丢，重要数据记得定期导出备份）\n"
            "- business_summary 说明：这是免费思路版，先用现成工具跑起来；"
            "想知道花钱找人开发要多少钱，随时问我再给报价参考\n"
            "- 用户在修改意见里主动问「花钱开发要多少钱」时：可以给粗略的价格"
            "参考区间，但主方案结构不变（仍不生成正式预算明细）"
        ),
    },
    "demo": {
        "label": "自用 Demo 版",
        # generate prompt 注入的硬约束
        "guidance": (
            "用户预算很低（≤5000 或明确表达成本敏感），只能做「自用 Demo 版」，"
            "方案必须遵守：\n"
            "- 只保留 1-3 个 P0 最小可用模块，其余全部砍掉或标记为「以后再说」\n"
            "- 技术选型只用免费/开源组件（如微信小程序 + 免费云开发额度、"
            "本地运行的开源软件），不推荐任何付费云服务和高并发架构\n"
            "- 不做商用级设计：不要支付对接、不要多端、不要运维监控这类生产模块\n"
            "- business_summary 必须明确标注「自用 Demo 版，不适合对外商用」\n"
            "- 预估成本超出预算时自动降级简化，而不是说服用户加预算"
        ),
    },
    "mid": {
        "label": "轻量生产版",
        "guidance": (
            "用户预算中等（5千~1万），做「轻量生产版」，方案必须遵守：\n"
            "- P0 模块做全，P1 只选最必要的 1-2 个，P2 全部移出本期\n"
            "- 部署用单机轻量方案（一台云服务器或 Serverless），不推荐集群/微服务\n"
            "- 只上一端（小程序或网页二选一），多端放二期\n"
            "- business_summary 标注「轻量生产版：按当前预算裁剪了部分功能」"
        ),
    },
    "pro": {
        "label": "完整生产版",
        "guidance": (
            "用户预算充足（>1万），可输出「完整生产版」：\n"
            "- P0/P1 模块做全，P2 按价值排序进分期\n"
            "- 可规划生产级部署（独立数据库、备份、基础监控），但仍避免过度设计"
        ),
    },
}


def classify_budget(mentioned: str | None) -> dict | None:
    """用户预算表述 → 档位信息 dict（写进 state.budget_tier）；无预算信息返回 None。

    返回结构（state 持久，各节点按需读取）：
        tier       demo/mid/pro
        label      档位中文名（前端徽章 / 方案标注用）
        mentioned  用户原话（保留口径，不换算）
        amount     解析出的预算上限（元）；成本敏感但无数字时为 None
        guidance   generate prompt 注入的硬约束文本
        recap      每轮对话开头复述给用户看的约束回顾（大白话）
    """
    if not mentioned:
        return None
    text = str(mentioned)

    # 免费试试：优先级最高——只要思路和现成工具，严禁报价（产品规则 #1/#4）
    if any(k in text for k in FREE_KEYWORDS):
        logger.info("[budget_tier] %s -> free 档", text)
        return {
            "tier": "free",
            "label": TIERS["free"]["label"],
            "mentioned": text,
            "amount": None,
            "guidance": TIERS["free"]["guidance"],
            "recap": "您选择先免费试试——方案只给做法思路和现成免费工具，不含开发报价；想知道花钱开发的价格，随时问我",
        }

    amount = parse_budget(text)
    cost_sensitive = any(k in text for k in COST_SENSITIVE)

    # 无数字且无成本态度 → 不构成约束
    if amount is None and not cost_sensitive:
        return None

    # 档位判定：金额优先，成本敏感（无金额）视同 demo
    if amount is None or amount <= DEMO_MAX:
        tier = "demo"
    elif amount <= MID_MAX:
        tier = "mid"
    else:
        tier = "pro"

    if amount is not None:
        recap = (
            f"已锁定您的预算约 {amount:,} 元，方案会按「{TIERS[tier]['label']}」来设计"
        )
    else:
        recap = f"您希望低成本先试，方案会按「{TIERS[tier]['label']}」来设计"
    recap += "（自用 Demo，不做商用级）" if tier == "demo" else ""

    info = {
        "tier": tier,
        "label": TIERS[tier]["label"],
        "mentioned": text,
        "amount": amount,
        "guidance": TIERS[tier]["guidance"],
        "recap": recap,
    }
    logger.info("[budget_tier] %s -> %s 档", text, tier)
    return info
