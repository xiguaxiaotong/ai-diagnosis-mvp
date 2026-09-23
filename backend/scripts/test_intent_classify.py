"""离线单测：意图分流规则 is_consult + 确认循环 classify_decision。"""

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.nodes.confirm import classify_decision
from app.agent.nodes.consult import is_consult

# 应判为「咨询」的消息（咨询/闲聊，不该触发生成或修改方案）
consult_cases = [
    "具体是怎么组成报价的",
    "你们是怎么收费的？",
    "为什么比别家贵",
    "你们公司是做什么的",
    "多久能上线？",
    # 注：原「你们能做小程序吗」「能做一个网站吗」按用户决策改判 requirement
    # （用户表达了真实需求意图，让 AI 去抽细节而非空对空谈价）。
    # 短问句「能做一个网站吗」含「能做」→ 判 requirement。
    "介绍一下你们的流程",
    "你好",
    "在吗",
    "你们是机器人吗",
]

# 应判为「需求/修改」（不能误伤）
requirement_cases = [
    "我想给小区做个团购接龙小程序",
    "预算提高到10w",
    "预算15万，3个月上线",
    "把会员模块去掉",
    "能不能便宜点",
    "大概200人用，每场团购50单",
    "需要对接物业系统",
    "微信小程序吧",
    "我们是在小区卖菜的，想做个接龙工具",
]

for t in consult_cases:
    assert is_consult(t), f"应判咨询: {t}"
for t in requirement_cases:
    assert not is_consult(t), f"误判咨询: {t}"
print("✅ is_consult 全通过")

# 确认循环意图：咨询不触发 revise
assert classify_decision("具体是怎么组成报价的") == "consult"
assert classify_decision("你们怎么收费的？") == "consult"
assert classify_decision("确认，就这样") == "confirmed"
assert classify_decision("不要了") == "rejected"
assert classify_decision("把会员模块去掉") == "revised"
assert classify_decision("预算砍到5万") == "revised"
print("✅ classify_decision 全通过（咨询不再触发重新生成方案）")
