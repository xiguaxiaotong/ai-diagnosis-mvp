"""测试数据特征规则清单（W10 Day4）：audit_test_data / purge_test_data 共用。

设计原则：**宁可漏报，不可误杀**——所以规则分两级：
  - 确认级（CONFIRMED）：工程测试的确定性特征（用户名前缀、连号假手机、
    工程测试标题词），audit 报「确定删除」，purge 只删这一级；
  - 疑似级（SUSPECT）：可能出现在真实客户表述里的词（"测试"/"大学生"），
    audit 单列「疑似」区仅供人工定夺，purge 永远不碰。

维护约定：以后有新的垃圾模式，往对应列表加一行即可（配注释注明来源），
不要把规则散落到 audit/purge 脚本里。
"""
import re

# ---------- 用户名规则（确认级） ----------
# 注册名前缀：历年测试轮次造的用户（来源见各轮验收记录）
USERNAME_PREFIXES: tuple[str, ...] = (
    "tier_test_",   # T1/T2 分层评估
    "grpA_", "grpB_", "selUI_",  # 黄金集 A/B 组 + 竞品 UI 对照组
    "restore_",     # W9 恢复演练
    "forgottest_",  # 忘记密码流测试
    "pbk_",         # 密码 hash 迁移测试
    "oldhash_",     # 旧 hash 兼容测试
    "me_", "me2_",  # /me 资料页测试
    "list_", "list2_",  # 项目列表测试
    "d3_",          # W9 Day3 批量项目
    "lead_", "lead2_",  # 线索流转测试
    "day4_",        # W10 Day4 线索测试
    "nonadm_",      # 非 admin 权限测试（403 矩阵）
    "smoke_",       # W10 Day1 冒烟套件（套件自身会清，规则兜底防漏网）
)

# 用户名正则（确认级）：裸 tester+数字 等
USERNAME_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p) for p in (
        r"^tester\d+$",          # tester9771
    )
)

# 游客账号：注册接口无用户名时落的默认昵称（username IS NULL AND name = 游客）
GUEST_NAME = "游客"

# ---------- 手机号规则（确认级，仅报告——leads 受白名单保护永不删） ----------
# 13800000000-13800000009：测试连号段（真实 138 段不会连零到个位）
FAKE_PHONE_PATTERN = re.compile(r"^13800000\d{2}$")

# ---------- 项目标题规则 ----------
# 确认级：只可能是工程测试的词，不可能出现在真实客户需求里
TITLE_CONFIRMED_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (word, re.compile(word))
    for word in (
        "外卖",        # 用户点名：「我是大学生点外卖」类需求全是演示数据
        "并发锁测试",
        "文件注入测试",
        "链路测试",
        "记忆验证",
        "意图验证",
        "演示项目",
        "真实联调",
        "API 测试",
        "复验",
        "游客测试",
    )
)

# 疑似级：真实客户也可能说的词——只报告，purge 不删
TITLE_SUSPECT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (word, re.compile(word))
    for word in (
        "测试",      # 「压测工具」可能是真需求
        "大学生",    # 「面向大学生的兼职平台」是真需求
    )
)

# ---------- 白名单（purge 永不删，audit 标注保护原因） ----------
# admin 本人；有 leads/worksheets 关联的用户动态保护（业务数据一律保留）
PROTECTED_USER_IDS: frozenset[int] = frozenset({1})
