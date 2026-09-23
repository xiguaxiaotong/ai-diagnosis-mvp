"""需求理解节点：用户口语化描述 → ProjectRequirements 结构化 JSON。

验收标准（Week2 Day1）：Prompt 单独文件，能通过 LLM 输出结构化 JSON。
"""

import difflib
import json
import logging

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

    # 渲染对话历史（最多取最近 6 条，控制 token；关键信息已在实体记忆里）
    history_text = "\n".join(
        f"{'用户' if m['role'] == 'user' else '顾问'}: {m['content']}"
        for m in history[-6:]
    ) or "（无）"

    prompt = render(
        "understand",
        raw_idea=raw_idea,
        history=history_text,
        confirmed=json.dumps(prev_req, ensure_ascii=False) if prev_req else "（暂无，这是第一轮）",
        last_questions="\n".join(f"- {q}" for q in prev_questions) if prev_questions else "（无）",
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
    req = ProjectRequirements.model_validate(merged)

    # 预算档位：用户提到预算 → 全局锁定（改口自然覆盖；没提过保持 None）
    from app.agent.budget_tier import classify_budget
    tier = classify_budget(req.mentioned_budget)

    questions = req.missing_info[:3]

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
    # 注意：resume 轮 raw_idea 不更新（用户消息在 messages 尾部），必须取最后一条 user 消息
    last_user = next(
        (m["content"] for m in reversed(state.get("messages", [])) if m.get("role") == "user"),
        "",
    )
    pain_confirmed, _ = _parse_pain_confirm(last_user)
    confirmed_points = list(state.get("confirmed_pain_points") or [])
    for p in pain_confirmed:
        if p not in confirmed_points:
            confirmed_points.append(p)

    def _dup(p: str, lst: list[str]) -> bool:
        """近似去重：措辞略有出入（「自己用/自用」插入字导致子串互不包含），
        用相似度兜底：完全包含 或 序列相似度 ≥ 0.75 视为同一条"""
        if any(p in q or q in p for q in lst):
            return True
        return any(
            difflib.SequenceMatcher(None, p, q).ratio() >= 0.75 for q in lst
        )

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
    }
    if tier:
        update["budget_tier"] = tier  # None（没提预算）时保留旧值，不覆盖
    return update
