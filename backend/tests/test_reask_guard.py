"""W11D4 防重复追问回归（线上 bug：答「还没定」后同一问题原样再问）。

复现链路：用户在快捷答题卡对「是否需要对接现有收银/外卖系统」选「还没定」
→ understand 下一轮又把该问题列进 missing_info → ask 原样再问。

修复设计三层：
1. state.answered_questions 登记已回答问题（含搁置型答案）；
2. understand prompt 明示「已回答问题禁止再问」；
3. 代码层 filter_answered 兜底——LLM 不听话也拦得住（本文件主测这层）。
"""

import json

import pytest

from app.agent.nodes.understand import (
    filter_answered,
    is_deferred_answer,
    parse_quick_answers,
    understand_node,
)
from app.agent.schemas import ProjectRequirements

Q1 = "是否需要对接现有收银/外卖系统"
Q2 = "每天大概多少单量"
Q3 = "预算范围"

# 「不听话的 LLM」：用户已答过 Q1/Q2，missing_info 仍原样塞回（模拟退化）
REQ_STUBBORN = {
    "project_title": "奶茶店点单小程序",
    "business_type": "餐饮",
    "core_features": ["扫码点单", "会员储值"],
    "target_users": ["顾客", "店员"],
    "mentioned_budget": None,
    "mentioned_deadline": None,
    "missing_info": [Q1, Q2, "是否需要会员积分功能"],
    "summary": "奶茶店点单小程序。",
}


@pytest.fixture
def stubborn_llm(monkeypatch):
    """understand 永远返回「重复追问已答问题」的 LLM（测代码层兜底）。"""
    from app.infra import model_client

    def stub_chat(messages, **kwargs):
        prompt = messages[0]["content"] if messages else ""
        if "资深的 AI 产品顾问" in prompt:
            return json.dumps(REQ_STUBBORN, ensure_ascii=False)
        return json.dumps(REQ_STUBBORN, ensure_ascii=False)

    monkeypatch.setattr(model_client.chat_client, "chat", stub_chat)
    monkeypatch.setattr(
        model_client.chat_client, "stream_chat",
        lambda messages, **kwargs: iter([stub_chat(messages, **kwargs)]),
    )
    return stub_chat


# ---------- 单元：搁置型判定 / 答案解析 / 过滤 ----------

@pytest.mark.parametrize("answer", ["还没定", "以后再说", "不确定", "都行", "看着办", "随便", "无所谓", "还没想好"])
def test_deferred_keywords(answer):
    assert is_deferred_answer(answer) is True


@pytest.mark.parametrize("answer", ["需要对接", "不对接，先做独立的", "每天几百笔", "几千块"])
def test_deferred_not_overreach(answer):
    """明确答案是有效回答，不能误判成搁置型。"""
    assert is_deferred_answer(answer) is False


def test_parse_quick_answers_lines():
    """答题卡逐行「问题：答案」格式（前端 submitInput 的实际发送格式）。"""
    text = f"{Q1}：还没定\n{Q2}：每天几百笔"
    pairs = parse_quick_answers(text, [Q1, Q2])
    assert (Q1, "还没定") in pairs
    assert (Q2, "每天几百笔") in pairs


def test_parse_quick_answers_half_colon_and_fuzzy():
    """半角冒号 + 问题措辞略有出入也能对号。"""
    pairs = parse_quick_answers(f"是否需要对接现有收银外卖系统: 都行", [Q1])
    assert pairs == [(Q1, "都行")]


def test_parse_quick_answers_single_question_fallback():
    """只有 1 个问题时，整条自由输入视为该题回答（不按行匹配也不丢）。"""
    pairs = parse_quick_answers("先不做对接，等以后再说", [Q1])
    assert pairs == [(Q1, "先不做对接，等以后再说")]


def test_filter_answered_similar_wording():
    """措辞变化的同一问题（相似度 ≥ 0.75）也被滤掉。"""
    answered = [{"question": Q1, "answer": "还没定"}]
    out = filter_answered([Q1, "需要对接现有收银外卖系统吗", Q3], answered)
    assert out == [Q3]


# ---------- 节点级：LLM 不听话时代码层拦死 ----------

def _state_after_answer(stubborn_llm, answer_text: str) -> dict:
    """第一轮追问 → 用户答题卡回答 → 第二轮 understand 的状态增量。"""
    base = {
        "raw_idea": "我想给奶茶店做扫码点单小程序",
        "messages": [
            {"role": "user", "content": "我想给奶茶店做扫码点单小程序"},
            {"role": "assistant", "content": "为了给您出准确的方案和报价，我需要先确认几个问题："},
            {"role": "user", "content": answer_text},
        ],
        "clarify_questions": [Q1, Q2],
        "requirements": None,
        "clarify_round": 1,
    }
    return understand_node(base)


def test_deferred_answer_not_reasked(stubborn_llm):
    """核心回归：答「还没定」后，下一轮 clarify_questions 不再含该问题。"""
    delta = _state_after_answer(stubborn_llm, f"{Q1}：还没定\n{Q2}：每天几百笔")

    # LLM stub 原样塞回了 Q1/Q2（模拟不听话），代码层必须滤掉
    assert Q1 not in delta["clarify_questions"]
    assert Q2 not in delta["clarify_questions"]
    # 清单外的新问题保留
    assert delta["clarify_questions"] == ["是否需要会员积分功能"]
    # 已回答清单登记在案
    assert {"question": Q1, "answer": "还没定"} in delta["answered_questions"]
    assert {"question": Q2, "answer": "每天几百笔"} in delta["answered_questions"]


def test_deferred_lands_in_requirements(stubborn_llm):
    """「还没定」作为有效答案落进 requirements（语义=先做独立版），不是空回答。"""
    delta = _state_after_answer(stubborn_llm, f"{Q1}：还没定")
    req = ProjectRequirements.model_validate(delta["requirements"])
    assert any(
        Q1 in c and "还没定" in c and "独立版" in c
        for c in req.clarified_answers
    ), req.clarified_answers


def test_all_answered_stops_clarify(stubborn_llm):
    """搁置型回答也算「答完」：LLM 塞回的已答问题全部滤掉后不再追问。"""
    stub = {
        "project_title": "奶茶店点单小程序",
        "business_type": "餐饮",
        "core_features": ["扫码点单"],
        "target_users": ["顾客"],
        "mentioned_budget": None,
        "mentioned_deadline": None,
        "missing_info": [Q1],
        "summary": "奶茶店点单小程序。",
    }
    from app.infra import model_client

    orig = model_client.chat_client.chat

    def stub_chat(messages, **kwargs):
        prompt = messages[0]["content"] if messages else ""
        if "资深的 AI 产品顾问" in prompt:
            return json.dumps(stub, ensure_ascii=False)
        return orig(messages, **kwargs)

    model_client.chat_client.chat = stub_chat  # stubborn_llm fixture 已 monkeypatch
    try:
        delta = _state_after_answer(stub_chat, f"{Q1}：还没定")
        assert delta["needs_clarify"] is False
        assert delta["clarify_questions"] == []
    finally:
        model_client.chat_client.chat = orig


def test_multi_round_no_repeat(stubborn_llm):
    """连答多问不重复：第二轮登记累积，第三轮新旧答案都不再被追问。"""
    # 第二轮：答 Q1
    delta2 = _state_after_answer(stubborn_llm, f"{Q1}：还没定\n{Q2}：每天几百笔")
    # 第三轮：state 带上第二轮产出，再答剩下的新问题
    state3 = {
        "raw_idea": "我想给奶茶店做扫码点单小程序",
        "messages": [
            {"role": "user", "content": f"{Q1}：还没定\n{Q2}：每天几百笔"},
            {"role": "assistant", "content": "还有几个问题：是否需要会员积分功能"},
            {"role": "user", "content": "是否需要会员积分功能：都行"},
        ],
        "clarify_questions": delta2["clarify_questions"],
        "requirements": delta2["requirements"],
        "answered_questions": delta2["answered_questions"],
        "clarify_round": 2,
    }
    delta3 = understand_node(state3)
    answered_qs = [a["question"] for a in delta3["answered_questions"]]
    assert Q1 in answered_qs and Q2 in answered_qs
    assert "是否需要会员积分功能" in answered_qs
    # 三问全部答过 → stubborn LLM 塞回什么都会被滤光
    assert delta3["clarify_questions"] == []
    assert delta3["needs_clarify"] is False
    # 同题新答案覆盖旧记录（不重复堆积）
    assert len(delta3["answered_questions"]) == 3


# ---------- ask 节点双保险 ----------

def test_ask_node_filters_answered(stubborn_llm):
    """ask 节点自身再拦一道：即使 clarify_questions 漏了已答问题，也不发问。"""
    from app.agent.nodes.ask import ask_node

    state = {
        "clarify_questions": [Q1, "还需要什么功能"],
        "answered_questions": [{"question": Q1, "answer": "还没定"}],
        "messages": [],
    }
    delta = ask_node(state)
    content = delta["messages"][-1]["content"]
    assert Q1 not in content
    assert "还需要什么功能" in content
