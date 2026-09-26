"""纯函数与服务层单测 —— 收编自 test_intent_classify / test_w3d3(离线) /
test_w4d2(split_text) / test_day2(embedding) / test_day3(CRUD)。
"""

import pytest

from app.agent.nodes.confirm import (
    MAX_REVISION_ROUNDS,
    classify_decision,
    review_router,
)
from app.agent.nodes.consult import is_consult
from app.retrieval.splitter import split_text


# ---------- 意图分流：is_consult（误伤需求 = 严重回归） ----------

@pytest.mark.parametrize("text", [
    "具体是怎么组成报价的",
    "你们是怎么收费的？",
    "为什么比别家贵",
    "你们公司是做什么的",
    "多久能上线？",
    "介绍一下你们的流程",
    "你好",
    "在吗",
    "你们是机器人吗",
])
def test_is_consult_true(text):
    assert is_consult(text), f"应判咨询: {text}"


@pytest.mark.parametrize("text", [
    "我想给小区做个团购接龙小程序",
    "预算提高到10w",
    "预算15万，3个月上线",
    "把会员模块去掉",
    "能不能便宜点",
    "大概200人用，每场团购50单",
    "需要对接物业系统",
    "微信小程序吧",
    "我们是在小区卖菜的，想做个接龙工具",
])
def test_is_consult_false(text):
    assert not is_consult(text), f"误判咨询: {text}"


# ---------- 确认循环意图：classify_decision ----------

@pytest.mark.parametrize("text,expected", [
    ("具体是怎么组成报价的", "consult"),
    ("你们怎么收费的？", "consult"),
    ("确认，就这样", "confirmed"),
    ("算了，不要了", "rejected"),
    ("不要了", "rejected"),
    ("不要会员模块了", "revised"),
    ("把会员模块去掉", "revised"),
    ("预算砍到5万", "revised"),
    ("预算太高了，便宜点", "revised"),
])
def test_classify_decision(text, expected):
    assert classify_decision(text) == expected


def test_review_router_table():
    assert MAX_REVISION_ROUNDS == 3
    assert review_router({"decision": "confirmed"}) == "confirmed"
    assert review_router({"decision": "rejected"}) == "rejected"
    assert review_router({"decision": "revised", "revision_round": 2}) == "revised"
    # 满轮后继续要求修改 → 强制收尾
    assert review_router({"decision": "revised", "revision_round": 3}) == "maxed"


# ---------- 文档切分：split_text ----------

def test_split_text_short_passthrough():
    assert split_text("短文本") == ["短文本"]
    assert split_text("") == []


def test_split_text_long_chunks():
    long = "系统模块介绍。" * 300  # ~1800 字
    chunks = split_text(long)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c) <= 580, "每块不得超 580 字"


# ---------- embedding 维度（bge-small-zh：512 维） ----------

@pytest.mark.slow
def test_embedding_dim():
    from app.infra.model_client import embedding_client

    vecs = embedding_client.embed(["客服系统", "点单小程序"])
    assert len(vecs) == 2
    assert len(vecs[0]) == 512
    q = embedding_client.embed_query("我想做客服机器人")
    assert len(q) == 512


# ---------- 数据层 CRUD（day3）----------

def test_project_crud_and_cascade():
    from app.db.database import SessionLocal
    from app.db.models import Conversation, Project
    from app.services import project_service

    db = SessionLocal()
    try:
        p = project_service.create_project(db, title="CRUD 验证", raw_idea="占位")
        assert p.status == "diagnosing"
        assert project_service.get_project(db, p.id).title == "CRUD 验证"

        project_service.update_project(
            db, p.id, status="plan_generated", budget_min=25_000, budget_max=35_000)
        got = project_service.get_project(db, p.id)
        assert got.status == "plan_generated"
        assert got.budget_min == 25_000 and got.budget_max == 35_000

        project_service.add_message(db, p.id, role="user", content="第一句")
        project_service.add_message(db, p.id, role="assistant", content="第二句")
        msgs = project_service.get_messages(db, p.id)
        assert [m.role for m in msgs] == ["user", "assistant"]

        assert len(project_service.list_projects(db, limit=10)) >= 1

        pid = p.id
        assert project_service.delete_project(db, pid)
        assert project_service.get_project(db, pid) is None
        # Conversation 级联删除
        assert db.query(Conversation).filter(
            Conversation.project_id == pid).count() == 0
    finally:
        db.close()
