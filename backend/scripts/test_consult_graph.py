"""stub 图级验证：咨询分流在真实图里接线正确（零 token，不调真 LLM）。

stub chat_client.chat：consult prompt（含「方案顾问」）→ 咨询话术；
其他（understand）→ 合法需求 JSON。
"""

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.infra import model_client

UNDERSTAND_JSON = """
{"project_title": "社区团购接龙小程序", "business_type": "社区零售",
 "core_features": ["接龙", "订单"], "target_users": ["团长"],
 "mentioned_budget": null, "mentioned_deadline": null,
 "missing_info": ["使用规模（多少人/多少单量）"], "summary": "社区团购"}
"""
CONSULT_REPLY = "我们的报价由系统根据您的需求自动测算，公开透明。具体的构成涉及内部核算，不便透露。"


def fake_chat(messages, **kwargs):
    prompt = messages[0]["content"]
    return CONSULT_REPLY if "方案顾问" in prompt else UNDERSTAND_JSON


model_client.chat_client.chat = fake_chat

from app.db.database import SessionLocal  # noqa: E402
from app.db.models import Project  # noqa: E402
from app.agent.graph import diagnosis_graph  # noqa: E402
from app.services.diagnosis_service import _config, chat_turn  # noqa: E402
from app.services import project_service  # noqa: E402

db = SessionLocal()
p = project_service.create_project(db, title="咨询分流验证", raw_idea="占位")
pid = p.id
db.close()

try:
    # 1. 首条消息就是咨询 → 应走 consult，不推进追问轮次
    r1 = chat_turn(pid, "你们是怎么收费的？")
    assert r1["phase"] == "clarify", r1["phase"]
    assert "内部核算" in r1["reply"], r1["reply"][:80]
    st = diagnosis_graph.get_state(_config(pid)).values
    assert st.get("clarify_round", 0) == 0, f"咨询不该消耗追问轮次: {st.get('clarify_round')}"
    assert st.get("intent") == "consult"
    print("✅ 1. 首条消息咨询：走 consult，clarify_round=0")

    # 2. 接着给需求 → 正常进 understand
    r2 = chat_turn(pid, "我想给小区做个团购接龙小程序，300人用")
    st2 = diagnosis_graph.get_state(_config(pid)).values
    assert r2["phase"] == "clarify" and st2.get("clarify_round") == 1, (r2["phase"], st2.get("clarify_round"))
    assert st2.get("intent") == "requirement"
    print("✅ 2. 需求消息：正常进 understand，clarify_round=1")

    # 3. 需求中夹咨询 → 不消耗轮次
    r3 = chat_turn(pid, "为什么你们比别家贵")
    st3 = diagnosis_graph.get_state(_config(pid)).values
    assert "内部核算" in r3["reply"] and st3.get("clarify_round") == 1, (r3["reply"][:50], st3.get("clarify_round"))
    print("✅ 3. 追问中夹咨询：仍走 consult，轮次不变")

    print("\n✅ 图级咨询分流验证全通过")
finally:
    db = SessionLocal()
    project_service.delete_project(db, pid) if hasattr(project_service, "delete_project") else db.query(Project).filter(Project.id == pid).delete()
    db.commit()
    db.close()
    print("（已清理测试项目）")
