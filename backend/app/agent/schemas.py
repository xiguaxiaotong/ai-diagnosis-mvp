"""P1 诊断智能体：Pydantic 输出模型（需求 / 方案 / 预算）。

LLM 返回的 JSON 统一用这些模型校验，非法输出直接报错而不是带病流转。
Week2 先实现 ProjectRequirements，方案/预算模型后续节点用到时再扩展。
"""

from pydantic import BaseModel, Field


class ExampleOption(BaseModel):
    """点选选项：label 是答案，note 是大白话说明（降低理解门槛）。"""

    label: str = Field(description="选项答案本身，≤8 字，口语化")
    note: str = Field(
        default="",
        description="一句大白话说明（≤20 字），讲清选它意味着什么",
    )


class QuestionDetail(BaseModel):
    """追问问题 + 示例选项（A 组交互升级）。

    examples 是贴合当前项目场景的典型答案，前端渲染成可点选 chip，
    同一问题组内单选（互斥），跨问题组互不干扰。
    """

    question: str = Field(description="问题文本，与 missing_info 中的问题对应")
    examples: list[ExampleOption] = Field(
        default_factory=list,
        description="2-3 个互斥选项（label + 大白话 note）",
    )


class ProjectRequirements(BaseModel):
    """需求理解节点的结构化输出。

    由「需求理解」节点从用户口语化描述中抽取；
    missing_info 非空时触发追问澄清（clarify 节点）。
    """

    project_title: str = Field(description="提炼后的项目名称，10 字以内")
    business_type: str = Field(description="行业/业务类型，如：餐饮、零售、教育")
    core_features: list[str] = Field(
        description="核心功能需求列表，3-8 条，每条一句话"
    )
    target_users: list[str] = Field(
        description="目标用户/使用角色，如：店员、顾客、管理员"
    )
    mentioned_budget: str | None = Field(
        default=None, description="用户提到的预算，未提及则为 null"
    )
    mentioned_deadline: str | None = Field(
        default=None, description="用户提到的期望工期，未提及则为 null"
    )
    missing_info: list[str] = Field(
        description="影响方案与报价的关键缺失信息，最多 3 条；信息齐全则为空列表"
    )
    question_details: list[QuestionDetail] = Field(
        default_factory=list,
        description="与 missing_info 一一对应的问题详情（含示例选项）",
    )
    pain_points: list[str] = Field(
        default_factory=list,
        description="从用户描述中识别的痛点（大白话，2-4 条）",
    )
    clarified_answers: list[str] = Field(
        default_factory=list,
        description=(
            "已回答问题的落档（W11D4 防重复追问）：『问题：答案』逐条，"
            "搁置型答案（还没定/都行等）附带处理语义（如先做独立版）；"
            "由 understand 节点代码级维护，LLM 不产出此字段"
        ),
    )
    summary: str = Field(description="用一段话（80 字内）复述需求，向用户确认理解")


class FunctionalModule(BaseModel):
    """业务功能模块（方案的业务部分）。"""

    name: str = Field(description="模块名称，如：扫码点单")
    description: str = Field(description="功能描述，一句话说清楚做什么、解决什么麻烦")
    example: str = Field(
        default="",
        description="具体使用场景举例（10-30 字），客户一看就知道怎么用",
    )
    priority: str = Field(description="优先级：P0=核心 / P1=重要 / P2=可选")


class TechChoice(BaseModel):
    """技术选型（方案的技术部分）。"""

    layer: str = Field(description="技术层级，如：前端、后端、数据库、部署")
    choice: str = Field(description="推荐的具体选型")
    reason: str = Field(description="选择理由，一句话，需考虑成本与维护难度")


class GlossaryItem(BaseModel):
    """术语小白卡条目（B 组排版）：方案里出现的技术词 → 大白话解释。"""

    term: str = Field(description="方案中出现的技术术语，如：API、云服务器")
    explanation: str = Field(
        description="一句大白话解释（20-40 字），用生活化类比，不用别的术语"
    )


class SolutionPlan(BaseModel):
    """方案生成节点的结构化输出：业务方案 + 技术方案。

    注意：不含价格。预算由后续 budget 节点单独生成，
    且必须是区间（商业计划书要求），避免方案与预算耦合导致反复重算。
    """

    project_name: str = Field(description="项目名称，与需求理解结果保持一致或微调")
    one_liner: str = Field(
        default="",
        description="一句话大白话总结（30字内）：这套东西帮你做什么，如「帮你把每天的账自动记好，手机一看就知道」",
    )
    business_summary: str = Field(description="业务方案概述，100 字内，讲清楚系统帮客户解决什么问题")
    core_business_modules: list[FunctionalModule] = Field(
        description="业务功能模块，3-8 个，覆盖需求中的核心功能"
    )
    tech_architecture: str = Field(description="技术架构概述，100 字内")
    tech_stack: list[TechChoice] = Field(
        description="分层技术选型，4-6 层（前端/后端/数据库/部署等）"
    )
    glossary: list[GlossaryItem] = Field(
        default_factory=list,
        description="本方案中出现的技术术语大白话解释，3-6 条；没有术语则为空",
    )
    implementation_phases: list[str] = Field(
        description="分期实施建议，2-3 期，每期一句话说明交付什么"
    )
    key_risks: list[str] = Field(
        description="关键风险提示，2-4 条，如第三方依赖、数据合规、工期风险"
    )


class FeasibilityReport(BaseModel):
    """可行性评估节点的结构化输出。"""

    overall: str = Field(description="总体结论：可行 / 有条件可行 / 风险较高，三选一")
    risk_level: str = Field(description="风险等级：低 / 中 / 高，三选一")
    tech_assessment: str = Field(description="技术可行性评估，2-3 句话")
    schedule_assessment: str = Field(description="工期可行性评估，对照用户期望工期；未提及则按常规评估")
    budget_assessment: str = Field(description="预算合理性评估，对照测算出的预算区间")
    suggestions: list[str] = Field(description="落地建议，2-4 条，可执行的具体动作")


class BudgetLineItem(BaseModel):
    """预算明细行：每一项钱的来源。"""

    item: str = Field(description="计价项，如：扫码点单（P0 模块）")
    basis: str = Field(description="计价依据，如：P0 模块单价 8000-12000 元")
    min_amount: int = Field(description="该项最低金额（元）")
    max_amount: int = Field(description="该项最高金额（元）")


class BudgetEstimate(BaseModel):
    """预算测算节点的结构化输出（规则引擎产出，非 LLM）。

    商业计划书硬性要求：预算必须是区间，不定值。
    """

    currency: str = Field(default="CNY", description="币种")
    total_min: int = Field(description="预算区间下限（元）")
    total_max: int = Field(description="预算区间上限（元）")
    line_items: list[BudgetLineItem] = Field(description="预算明细，逐项列出钱的构成")
    assumptions: list[str] = Field(description="测算假设，如工期加急、需对接现有系统")
    budget_match: str = Field(
        description="与用户提及预算的对比结论；用户未提预算则为「用户未提及预算」"
    )
