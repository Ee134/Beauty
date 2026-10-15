"""Chat: the single orchestration entry point."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..agent import orchestrator
from ..models import Conversation, Message
from ..services.errors import AppError, not_found
from .deps import CurrentAuth, DbSession, IdempotencyKey, SettingsDep

router = APIRouter()


class ChatRequest(BaseModel):
    session_id: str | None = Field(default=None, description="会话 id；为空则新建")
    message: str = Field(min_length=1, max_length=4000)
    client_context: dict[str, Any] | None = None


@router.get("/chat/sessions")
def list_sessions(auth: CurrentAuth, db: DbSession) -> dict[str, Any]:
    rows = list(
        db.execute(
            select(Conversation)
            .where(Conversation.tenant_id == auth.tenant_id, Conversation.user_id == auth.user_id)
            .order_by(Conversation.created_at.desc())
            .limit(20)
        ).scalars()
    )
    return {
        "sessions": [
            {
                "id": c.id,
                "title": c.title,
                "status": c.status,
                "last_message_at": c.last_message_at.isoformat() if c.last_message_at else None,
            }
            for c in rows
        ]
    }


@router.get("/chat/sessions/{session_id}/messages")
def session_messages(
    session_id: str,
    auth: CurrentAuth,
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    conversation = db.get(Conversation, session_id)
    if (
        conversation is None
        or conversation.tenant_id != auth.tenant_id
        or conversation.user_id != auth.user_id
    ):
        raise not_found("会话")
    rows = list(
        db.execute(
            select(Message)
            .where(Message.conversation_id == session_id)
            .order_by(Message.sequence)
            .limit(limit)
        ).scalars()
    )
    return {
        "session_id": session_id,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "sequence": m.sequence,
                "cards": m.cards,
                "citations": m.citations,
                "run_id": m.run_id,
                "redacted": m.redacted_at is not None,
                "created_at": m.created_at.isoformat(),
            }
            for m in rows
        ],
    }


@router.post("/chat/messages")
def post_message(
    payload: ChatRequest,
    auth: CurrentAuth,
    db: DbSession,
    settings: SettingsDep,
    idem: IdempotencyKey,
) -> dict[str, Any]:
    try:
        result = orchestrator.run_turn(
            db,
            auth=auth,
            message=payload.message,
            conversation_id=payload.session_id,
            idempotency_key=idem,
            settings=settings,
        )
    except AppError:
        db.rollback()
        raise
    db.commit()
    output = result.output
    conversation = db.get(Message, result.assistant_message_id) if result.assistant_message_id else None
    return {
        "session_id": conversation.conversation_id if conversation else payload.session_id,
        "output": output,
        "notice": (
            "mock 模式：回复由确定性编排生成，不声称真实模型或真实识别能力。"
            if settings.model_mode == "mock"
            else "live 模式。"
        ),
    }
