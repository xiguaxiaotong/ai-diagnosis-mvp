"""需求理解节点：用户口语化描述 → ProjectRequirements 结构化 JSON。

验收标准（Week2 Day1）：Prompt 单独文件，能通过 LLM 输出结构化 JSON。
"""

import difflib
import json
import logging
from typing import Any

from app.agent.prompt_loader import render
from app.agent.schemas import ProjectRequirements
from app.agent.state import DiagnosisState
from app.infra.model_client import chat_client

logger = logging.getLogger(__name__)


def extract_json(text: str) -> str:
    """容错提取：剥掉可能的 markdown 代码块围栏和前后杂文。"""
    text = text.strip()
    if text.startswith("```"):
        # 去掉 ```json ... ``` 围栏
        text = text.split("`" * 3)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    # 截取首个 { 到末个 } 之间
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    return text


def _merge_requirements(old: dict | None, new: dict) -> dict:
    """实体记忆合并（代码层兜底，不靠 LLM 自觉）：

    旧值非空 + 新值为空（None/""/[]）→ 强制保留旧值。
    根治「LLM 每轮重新抽取看漏已答字段 → missing_info 又包含它 → 重复提问」。
    用户改口（新值非空）时新值自然覆盖，符合「最新值优先」。
    """
    if not old:
        return new
    for key, old_val in old.items():
        if key == "missing_info":
            continue
        new_val = new.get(key)
        empty = new_val is None or new_val == "" or new_val == []
        if old_val and empty:
            new[key] = old_val
    return new


def _parse_pain_confirm(raw_idea: str) -> tuple[list[str], str]:
    """A 组痛点确认：前端卡片发送「【痛点确认】A；B」格式消息。

    代码级解析（不依赖 LLM）：拆出确认的痛点列表 + 去掉标记后的正文，
    正文继续走正常抽取（确认消息里往往还带补充说明）。
    """
    if not raw_idea.startswith("【痛点确认】"):
        return [], raw_idea
    rest = raw_idea[len("【痛点确认】"):].strip()
    # 兼容「我确认的痛点：A；B」或直接「A；B」
    if rest.startswith("我"):
        rest = rest.split("：", 1)[-1]
    points = [p.strip() for p in rest.replace("；", ";").split(";") if p.strip()]
    return points, rest


# ---------- W11D4 防重复追问：已回答问题登记（代码级，不信任 LLM 自觉） ----------

# 搁置型答案关键词：语义 = 「接受默认/最简方案」，视为有效回答而非空回答。
# 覆盖快捷答题卡与自由输入的高频说法（还没定/以后再说/不确定/都行等）。
DEFERRED_KEYWORDS = (
    "还没定", "还没想好", "没想好", "以后再说", "再说吧", "不确定",
    "不知道", "都行", "随便", "看着办", "无所谓", "没有特别要求", "听你的",
)


def is_deferred_answer(answer: str) -> bool:
    """搁置型回答判定。

    「还没定/以后再说/不确定/都行」是用户已表态（按默认/最简方案走），
    不是空回答——继续追问同一问题只会激怒用户（线上 bug：同一问题原样再问）。
    """
    a = answer.strip()
    return any(k in a for k in DEFERRED_KEYWORDS)


def _similar_text(a: str, b: str) -> bool:
    """文本近似判定：互相包含 或 序列相似度 ≥ 0.75 视为同一问题。"""
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.75


def parse_quick_answers(text: str, questions: list[str]) -> list[tuple[str, str]]:
    """从用户消息拆「问题：答案」对（前端答题卡逐行发送 `问题：label`）。

    匹配宽容：全角/半角冒号都认；问题侧与上一轮问题全等/包含/高相似即对号。
    兜底：上一轮只有 1 个问题且按行没匹配上时，整条消息视为该题的回答。
    返回 [(上一轮问题原文, 用户答案原文)]。
    """
    pairs: list[tuple[str, str]] = []
    for line in (l.strip() for l in text.splitlines()):
        if not line:
            continue
        sep = "：" if "：" in line else (":" if ":" in line else None)
        if not sep:
            continue
        q_part, a_part = line.split(sep, 1)
        q_part, a_part = q_part.strip(), a_part.strip()
        if not a_part:
            continue
        match = next((q for q in questions if _similar_text(q_part, q)), None)
        if match:
            pairs.append((match, a_part))
    if not pairs and len(questions) == 1 and text.strip():
        pairs.append((questions[0], text.strip()))
    return pairs


def filter_answered(questions: list[str], answered: list[dict[str, Any]]) -> list[str]:
    """防重复兜底：已回答清单（含搁置型答案）里的问题一律从追问列表剔除。

    不信任 LLM 一定听话——understand 的 missing_info 由 LLM 产出，
    这里在代码层再拦一道（ask 节点也复用本函数做双保险）。
    """
    if not answered:
        return questions
    asked = [a["question"] for a in answered]
    return [q for q in questions if not any(_similar_text(q, aq) for aq in asked)]


def _deferred_note(question: str) -> str:
    """搁置型答案落 requirements 的处理语义（对接类 → 先做独立版）。"""
    if "对接" in question or "系统" in question:
        return "（还没定：方案先按独立版设计，预留后续对接）"
    return "（搁置型回答：方案按默认/最简方式处理）"


def understand_node(state: DiagnosisState) -> dict:
    """执行需求理解，返回状态增量：requirements / needs_clarify / clarify_questions。

    实体记忆机制：上一轮 requirements（经 checkpointer 持久化）作为
    「已确认字段」注入 prompt，LLM 只做合并更新；
    代码层再兜底一次（_merge_requirements），已答字段永不丢失。
    """
    raw_idea = state.get("raw_idea", "")
    history = state.get("messages", [])
    prev_req = state.get("requirements") or {}
    prev_questions = state.get("clarify_questions", [])

    # 最新用户消息（resume 轮答案在 messages 尾部，raw_idea 不更新）
    last_user = next(
        (m["content"] for m in reversed(history) if m.get("role") == "user"),
        "",
    )

    # W11D4：登记已回答问题（含搁置型答案），同题新答案覆盖旧记录（最新值优先）
    answered = [dict(item) for item in (state.get("answered_questions") or [])]
    for q, a in parse_quick_answers(last_user, prev_questions):
        answered = [item for item in answered if item["question"] != q]
        answered.append({"question": q, "answer": a})

    # 渲染对话历史（最多取最近 6 条，控制 token；关键信息已在实体记忆里）
    history_text = "\n".join(
        f"{'用户' if m['role'] == 'user' else '顾问'}: {m['content']}"
        for m in history[-6:]
    ) or "（无）"

    answered_text = (
        "\n".join(f"- {item['question']}：{item['answer']}" for item in answered)
        or "（暂无）"
    )

    prompt = render(
        "understand",
        raw_idea=raw_idea,
        history=history_text,
        confirmed=json.dumps(prev_req, ensure_ascii=False) if prev_req else "（暂无，这是第一轮）",
        last_questions="\n".join(f"- {q}" for q in prev_questions) if prev_questions else "（无）",
        answered=answered_text,
    )

    # DeepSeek 支持 response_format=json_object 强制 JSON 输出
    # 信息抽取任务用低温度，减少随机追问/漏抽
    try:
        try:
            answer = chat_client.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.2,
                response_format={"type": "json_object"},
            )
        except Exception:
            # 某些中转/兼容层不支持 json_object，退化为普通调用
            logger.warning("response_format=json_object 调用失败，退化为普通调用")
            answer = chat_client.chat([{"role": "user", "content": prompt}], temperature=0.2)

        data = json.loads(extract_json(answer))
        req = ProjectRequirements.model_validate(data)
    except (json.JSONDecodeError, ValueError) as e:
        # JSON 解析/字段校验失败 → 转 needs_clarify，让图回到 wait_input 引导重述
        from app.agent.nodes._error import user_friendly_understand_error
        return user_friendly_understand_error(str(e))
    except Exception as e:
        # 网络超时/未知异常 → 也走友好提示，避免整图挂掉
        logger.exception("[understand] LLM 调用异常，转重述引导")
        from app.agent.nodes._error import user_friendly_understand_error
        return user_friendly_understand_error(f"LLM 调用失败: {type(e).__name__}")

    # 代码层兜底：LLM 漏抽的已答字段强制回填（实体记忆不丢）
    merged = _merge_requirements(prev_req, req.model_dump())

    # W11D4：已回答问题落进 requirements（含搁置型答案的处理语义），
    # generate 节点注入 requirements_json 时全程可见——「还没定」不再是空回答
    clarified = [c for c in (merged.get("clarified_answers") or []) if isinstance(c, str)]
    for item in answered:
        line = f"{item['question']}：{item['answer']}"
        if is_deferred_answer(item["answer"]):
            line += _deferred_note(item["question"])
        if line not in clarified:
            clarified.append(line)
    merged["clarified_answers"] = clarified
    req = ProjectRequirements.model_validate(merged)

    # 预算档位：用户提到预算 → 全局锁定（改口自然覆盖；没提过保持 None）
    from app.agent.budget_tier import classify_budget
    tier = classify_budget(req.mentioned_budget)

    # W11D4 防重复兜底：已回答（含搁置型）的问题从追问列表剔除——
    # 不信任 LLM 一定听话，代码层拦死「同一问题原样再问」
    questions = filter_answered(req.missing_info[:3], answered)

    # A 组：question_details 与 missing_info 对齐（LLM 漏配/长度不齐时代码兜底）
    details = [d.model_dump() for d in req.question_details]
    aligned: list[dict] = []
    for idx, q in enumerate(questions):
        # 先按文本严格匹配；LLM 措辞与 missing_info 不一致时按位置对齐（约定一一对应）
        match = next((d for d in details if d.get("question") == q), None)
        if match is None and idx < len(details):
            match = details[idx]
        raw_exs = (match or {}).get("examples", []) if match else []
        examples = []
        for e in raw_exs[:3]:
            if isinstance(e, dict):  # 新格式 {label, note}
                if e.get("label"):
                    examples.append({"label": e["label"], "note": e.get("note", "")})
            elif isinstance(e, str) and e:  # LLM 退化成纯字符串 → 补空 note
                examples.append({"label": e, "note": ""})
        aligned.append({"question": q, "examples": examples})
    # 有问题没配示例时，退而用常见选项兜底（按问题关键词命中，带大白话说明）
    FALLBACK_EXAMPLES = [
        (("部署", "使用", "手机", "电脑", "设备"), [
            {"label": "微信小程序", "note": "微信里点开就用，不用下载"},
            {"label": "手机 App", "note": "单独装一个 App，功能更顺"},
            {"label": "电脑网页", "note": "电脑浏览器打开就能用"},
        ]),
        (("规模", "多少", "单", "笔", "量"), [
            {"label": "每天几十笔", "note": "小店面日常量，够用"},
            {"label": "每天几百笔", "note": "量大，要考虑流畅不卡"},
            {"label": "就我自己用", "note": "单人使用，最省钱"},
        ]),
        (("预算", "多少钱", "投入"), [
            {"label": "几百块", "note": "简易 Demo，基础功能自用"},
            {"label": "几千块", "note": "完整可用版，功能更全"},
            {"label": "先免费试试", "note": "先出方案原型，不写代码"},
        ]),
        (("工期", "时间", "多久", "急"), [
            {"label": "越快越好", "note": "加急做，可能加钱"},
            {"label": "1 个月内", "note": "常规节奏，质量稳"},
            {"label": "不着急", "note": "慢慢做，性价比高"},
        ]),
        (("多人", "谁用", "一起", "员工"), [
            {"label": "就我自己", "note": "单人账号，最简单"},
            {"label": "两三个人", "note": "小团队共用一个后台"},
            {"label": "多个员工", "note": "要分角色权限，复杂些"},
        ]),
        (("统计", "汇总", "合计", "报表"), [
            {"label": "每天每月都要", "note": "随时看当天和整月情况"},
            {"label": "只要每月合计", "note": "月底看总数就够了"},
            {"label": "不用统计", "note": "能记能查就行，最省"},
        ]),
    ]
    for item in aligned:
        if not item["examples"]:
            for keys, exs in FALLBACK_EXAMPLES:
                if any(k in item["question"] for k in keys):
                    item["examples"] = [dict(e) for e in exs]
                    break

    # A 组痛点：LLM 识别候选 + 用户勾选确认（代码级，从最新用户消息拆出）累加去重
    pain_confirmed, _ = _parse_pain_confirm(last_user)
    confirmed_points = list(state.get("confirmed_pain_points") or [])
    for p in pain_confirmed:
        if p not in confirmed_points:
            confirmed_points.append(p)

    def _dup(p: str, lst: list[str]) -> bool:
        """近似去重：复用 _similar_text（包含 或 相似度 ≥ 0.75 视为同一条）"""
        return any(_similar_text(p, q) for q in lst)

    # 候选 = 已确认痛点 + 本轮新识别（与已确认/已收集的近似重复都滤掉）
    seen: list[str] = []
    for p in (req.pain_points or []):
        if not _dup(p, confirmed_points) and not _dup(p, seen):
            seen.append(p)
    pain_candidates = confirmed_points + seen

    logger.info(
        "[understand] round=%s title=%s features=%d missing=%d tier=%s pain=%d",
        state.get("clarify_round", 0) + 1,
        req.project_title, len(req.core_features), len(questions),
        tier["tier"] if tier else "-", len(pain_candidates),
    )
    update = {
        "requirements": req.model_dump(),
        "needs_clarify": len(questions) > 0,
        "clarify_questions": questions,
        "clarify_round": state.get("clarify_round", 0) + 1,
        # A 组：示例随问题、痛点候选与确认集都进 state（checkpointer 持久）
        "question_details": aligned,
        "pain_points": pain_candidates,
        "confirmed_pain_points": confirmed_points,
        # W11D4：已回答问题清单（checkpointer 持久，跨轮累积）
        "answered_questions": answered,
    }
    if tier:
        update["budget_tier"] = tier  # None（没提预算）时保留旧值，不覆盖
    return update
