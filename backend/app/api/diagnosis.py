"""P6 诊断 API：SSE 对话流 + 项目方案详情 + 确认循环接口。

- POST /api/chat                 一次对话轮（新想法/追问回答/方案确认均可），
                                 回复以 SSE 逐块推送（text/event-stream）
- GET  /api/project/{id}         项目详情：状态 + 完整方案 JSON + 对话记录
- POST /api/project/{id}/confirm 确认循环动作：confirm / revise / reject

SSE 事件格式（data: JSON\n\n）：
    {"type": "meta",  "phase": "..."}       首事件：本轮结果类型
    {"type": "delta", "content": "..."}     正文增量块
    {"type": "done"}                        结束标记
"""

import json
import logging
import time
from typing import Any, Iterator, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services import diagnosis_service, project_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# 每个 SSE 块的字符数（模拟 token 粒度；真实 LLM 流式在图内节点，MVP 不拆到 token）
_CHUNK_SIZE = 3
_CHUNK_DELAY = 0.02


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _stream_reply(reply: str, phase: str, extra: dict[str, Any]) -> Iterator[str]:
    """把一轮回复切成小块按 SSE 推送。"""
    yield _sse({"type": "meta", "phase": phase, **extra})
    for i in range(0, len(reply), _CHUNK_SIZE):
        yield _sse({"type": "delta", "content": reply[i:i + _CHUNK_SIZE]})
    yield _sse({"type": "done"})


class ChatRequest(BaseModel):
    project_id: int
    message: str


class ConfirmRequest(BaseModel):
    action: Literal["confirm", "revise", "reject"]
    feedback: str | None = None


def _run_and_record(db: Session, project_id: int, message: str) -> dict:
    """跑一轮图 + 双向落库（用户消息 + 助手回复）。"""
    result = diagnosis_service.chat_turn(project_id, message)
    project_service.add_message(db, project_id, "user", message)
    project_service.add_message(db, project_id, "assistant", result["reply"])
    return result


@router.post("/chat")
def chat(body: ChatRequest, db: Session = Depends(get_db)):
    """对话诊断入口：SSE 流式返回。

    事件序列：stage（图节点阶段，多个）→ meta → delta（多个）→ done。
    阶段事件让前端在 LLM 执行期间展示「正在理解需求/生成方案…」，
    避免长等待中用户以为卡死。
    """
    project = project_service.get_project(db, body.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")

    def sse():
        result = None
        for kind, payload in diagnosis_service.chat_turn_stream(body.project_id, body.message):
            if kind == "stage":
                node, label = payload
                yield f"data: {json.dumps({'type': 'stage', 'stage': node, 'label': label}, ensure_ascii=False)}\n\n"
            else:
                result = payload
        # 双向落库（用户消息 + 助手回复）
        project_service.add_message(db, body.project_id, "user", body.message)
        project_service.add_message(db, body.project_id, "assistant", result["reply"])
        extra = {"questions": result["questions"], "revision_round": result["revision_round"]}
        yield from _stream_reply(result["reply"], result["phase"], extra)

    return StreamingResponse(
        sse(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/project/{project_id}")
def get_project_detail(project_id: int, db: Session = Depends(get_db)):
    """项目详情：基础字段 + 完整方案 JSON（plan 列存的就是完整方案对象）。"""
    project = project_service.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")

    solution: dict | None = None
    if project.plan:
        try:
            solution = json.loads(project.plan)
        except json.JSONDecodeError:
            logger.warning("项目 %s 的 plan 字段不是合法 JSON", project_id)

    return {
        "id": project.id,
        "title": project.title,
        "raw_idea": project.raw_idea,
        "status": project.status,
        "budget_min": project.budget_min,
        "budget_max": project.budget_max,
        "solution": solution,
        "messages": [
            {"id": m.id, "role": m.role, "content": m.content,
             "created_at": m.created_at.isoformat()}
            for m in project_service.get_messages(db, project_id)
        ],
    }


@router.post("/project/{project_id}/confirm")
def confirm(project_id: int, body: ConfirmRequest, db: Session = Depends(get_db)):
    """确认循环动作：confirm / revise（需 feedback）/ reject。"""
    project = project_service.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 三种动作统一转成用户消息，走同一条 resume 通道（意图由图内规则分类）
    action_text = {
        "confirm": "确认，就这样",
        "reject": "算了，不要了",
    }.get(body.action)
    message = body.feedback.strip() if body.action == "revise" else action_text
    if not message:
        raise HTTPException(status_code=422, detail="revise 动作必须提供 feedback")

    result = _run_and_record(db, project_id, message)
    return {
        "phase": result["phase"],
        "reply": result["reply"],
        "revision_round": result["revision_round"],
        "solution": result["solution"],
    }
