"""需求理解节点：用户口语化描述 → ProjectRequirements 结构化 JSON。

验收标准（Week2 Day1）：Prompt 单独文件，能通过 LLM 输出结构化 JSON。
"""

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


def understand_node(state: DiagnosisState) -> dict:
    """执行需求理解，返回状态增量：requirements / needs_clarify / clarify_questions。"""
    raw_idea = state.get("raw_idea", "")
    history = state.get("messages", [])

    # 渲染对话历史（最多取最近 6 条，控制 token）
    history_text = "\n".join(
        f"{'用户' if m['role'] == 'user' else '顾问'}: {m['content']}"
        for m in history[-6:]
    ) or "（无）"

    prompt = render("understand", raw_idea=raw_idea, history=history_text)

    # DeepSeek 支持 response_format=json_object 强制 JSON 输出
    # 信息抽取任务用低温度，减少随机追问/漏抽
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

    try:
        data = json.loads(extract_json(answer))
        req = ProjectRequirements.model_validate(data)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error("需求理解输出解析失败: %s\n原始输出: %s", e, answer[:500])
        return {"error": f"需求理解 JSON 解析失败: {e}"}

    questions = req.missing_info[:3]
    logger.info(
        "[understand] round=%s title=%s features=%d missing=%d",
        state.get("clarify_round", 0) + 1,
        req.project_title, len(req.core_features), len(questions),
    )
    return {
        "requirements": req.model_dump(),
        "needs_clarify": len(questions) > 0,
        "clarify_questions": questions,
        "clarify_round": state.get("clarify_round", 0) + 1,
    }
