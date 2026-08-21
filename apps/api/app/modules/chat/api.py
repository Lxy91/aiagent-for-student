import json
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.api.dependencies import SettingsDep
from app.core.errors import AppError
from app.core.security import CurrentUserDep
from app.infrastructure.db.session import SessionDep
from app.infrastructure.llm.deepseek import DeepSeekProvider
from app.modules.chat.schemas import (
    ConversationResponse,
    CreateConversationRequest,
    MessageResponse,
    SendMessageRequest,
)
from app.modules.chat.service import ConversationService

router = APIRouter(prefix="/conversations", tags=["chat"])


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@router.post("", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    payload: CreateConversationRequest, current_user: CurrentUserDep, session: SessionDep
) -> ConversationResponse:
    return await ConversationService(session).create(current_user.id, payload)


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(
    current_user: CurrentUserDep, session: SessionDep
) -> list[ConversationResponse]:
    return await ConversationService(session).list(current_user.id)


@router.get("/{conversation_id}/messages", response_model=list[MessageResponse])
async def list_messages(
    conversation_id: UUID, current_user: CurrentUserDep, session: SessionDep
) -> list[MessageResponse]:
    return await ConversationService(session).list_messages(current_user.id, conversation_id)


@router.post("/{conversation_id}/messages:stream")
async def stream_message(
    conversation_id: UUID,
    payload: SendMessageRequest,
    request: Request,
    current_user: CurrentUserDep,
    settings: SettingsDep,
    session: SessionDep,
) -> StreamingResponse:
    service = ConversationService(session)
    await service.get_owned(current_user.id, conversation_id)
    await service.add_message(conversation_id, "user", payload.content)
    trace_id = request.state.trace_id

    async def event_stream() -> AsyncIterator[str]:
        response_id = uuid4()
        yield sse("message.started", {"message_id": response_id, "trace_id": trace_id})
        history = await service.recent_messages(conversation_id)
        messages = [
            {
                "role": "system",
                "content": (
                    "你是大学生职场适应助手。先理解问题，再给具体、尊重组织差异的建议。"
                    "沟通场景优先给可直接使用的话术，并说明使用边界。不得伪造引用。"
                ),
            },
            *history,
        ]
        full_response = ""
        try:
            async for chunk in DeepSeekProvider(settings).stream_chat(messages):
                if await request.is_disconnected():
                    return
                full_response += chunk
                yield sse("message.delta", {"text": chunk})
            await service.add_message(conversation_id, "assistant", full_response)
            yield sse(
                "message.completed",
                {
                    "message_id": response_id,
                    "finish_reason": "stop",
                    "usage": None,
                    "demo_mode": not settings.deepseek_enabled,
                },
            )
        except AppError as exc:
            yield sse(
                "error",
                {
                    "code": exc.code,
                    "message": exc.message,
                    "trace_id": trace_id,
                    "retryable": exc.retryable,
                },
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
