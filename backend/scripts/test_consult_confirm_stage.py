"""stub 图级验证（场景2）：方案确认环节的咨询不打断确认循环、不触发重新生成方案。

对应真实反馈场景：方案出来后用户问「具体是怎么组成报价的」——
旧逻辑会误判为修改意见 → 重新生成方案（答非所问 + 烧钱）；
新逻辑应走 consult 节点回复，且回到 wait_confirmation 继续等确认。
"""

import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.infra import model_client

UNDERSTAND_JSON = {
    "project_title": "团购小程序", "business_type": "社区零售",
    "core_features": ["接龙", "订单"], "target_users": ["团长"],
    "mentioned_budget": "10万", "mentioned_deadline": "2个月",
    "missing_info": [], "summary": "社区团购",
}
GENERATE_JSON = {
    "project_name": "团购小程序", "business_summary": "社区团购接龙",
    "core_business_modules": [
        {"name": "接龙", "description": "发起与参与接龙", "priority": "P0"},
        {"name": "订单", "description": "订单管理", "priority": "P0"},
    ],
    "tech_architecture": "小程序+后端", "tech_stack": [{"layer": "前端", "choice": "微信小程序", "reason": "用户习惯"}],
    "implementation_phases": ["一期核心"], "key_risks": ["需求变更"],
}
FEASIBILITY_JSON = {
    "overall": "可行", "risk_level": "低", "tech_assessment": "常规方案成熟",
    "schedule_assessment": "2个月可交付", "budget_assessment": "预算充足",
    "suggestions": ["先做核心模块"],
}
CONSULT_REPLY = "报价构成涉及公司内部核算，属于商业机密，不便透露明细。可以留下联系方式，专人人工审核后为您解释。"


def fake_chat(messages, **kwargs):
    prompt = messages[0]["content"]
    if "商业机密" in prompt:  # consult.txt 独有
        return CONSULT_REPLY
    if kwargs.get("response_format") is None:
        return CONSULT_REPLY
    data = (GENERATE_JSON if "P0=没有就没法上线" in prompt
            else FEASIBILITY_JSON if "可行性评估" in prompt
            else UNDERSTAND_JSON)
    return json.dumps(data, ensure_ascii=False)


def fake_stream(messages, **kwargs):
    # consult_node 走流式 stream_chat（SSE 改造后），一并 stub 防真调 API
    return iter([fake_chat(messages, **kwargs)])


model_client.chat_client.chat = fake_chat
model_client.chat_client.stream_chat = fake_stream

from app.agent.graph import diagnosis_graph  # noqa: E402
from app.services.diagnosis_service import _config, chat_turn  # noqa: E402
from app.db.database import SessionLocal  # noqa: E402
from app.db.models import Project  # noqa: E402
from app.services import project_service  # noqa: E402

db = SessionLocal()
p = project_service.create_project(db, title="确认环节咨询验证", raw_idea="占位")
pid = p.id
db.close()

try:
    # 出方案（stub 需求信息齐全 → 直达 generate）
    r1 = chat_turn(pid, "我想做个社区团购接龙小程序，预算10万，2个月上线")
    assert r1["phase"] == "confirm_wait", f"应到确认环节: {r1['phase']}"
    print("✅ 1. 方案已生成，进入确认环节")

    # 确认环节问报价构成 → 走 consult，不触发 revise
    r2 = chat_turn(pid, "具体是怎么组成报价的")
    assert r2["phase"] == "confirm_wait", f"咨询后应仍停在确认环节: {r2['phase']}"
    assert "商业机密" in r2["reply"] or "人工审核" in r2["reply"], r2["reply"][:80]
    st = diagnosis_graph.get_state(_config(pid)).values
    assert st.get("revision_round", 0) == 0, f"咨询不该消耗修改轮次: {st.get('revision_round')}"
    assert st.get("decision") == "consult"
    print("✅ 2. 确认环节问报价构成：走 consult（不重出方案），仍在等确认")

    # 咨询后继续正常确认 → 流程不受影响
    r3 = chat_turn(pid, "确认，就这样")
    st3 = diagnosis_graph.get_state(_config(pid)).values
    assert st3.get("decision") == "confirmed", st3.get("decision")
    print("✅ 3. 咨询后正常确认：流程不受影响")

    print("\n✅ 确认环节咨询分流验证全通过")
finally:
    db = SessionLocal()
    db.query(Project).filter(Project.id == pid).delete()
    db.commit()
    db.close()
    print("（已清理测试项目）")
