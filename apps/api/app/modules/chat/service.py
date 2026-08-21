from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.infrastructure.db.models import ConversationModel, MessageModel
from app.modules.chat.schemas import (
    ConversationResponse,
    CreateConversationRequest,
    MessageResponse,
)


class ConversationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self, user_id: UUID, payload: CreateConversationRequest
    ) -> ConversationResponse:
        item = ConversationModel(
            id=str(uuid4()),
            user_id=str(user_id),
            title=payload.title,
            mode=payload.mode,
            created_at=datetime.now(UTC),
        )
        self.session.add(item)
        await self.session.commit()
        return self._conversation_response(item)

    async def list(self, user_id: UUID) -> list[ConversationResponse]:
        result = await self.session.scalars(
            select(ConversationModel)
            .where(ConversationModel.user_id == str(user_id))
            .order_by(ConversationModel.created_at.desc())
        )
        return [self._conversation_response(item) for item in result]

    async def get_owned(self, user_id: UUID, conversation_id: UUID) -> ConversationModel:
        item = await self.session.scalar(
            select(ConversationModel).where(
                ConversationModel.id == str(conversation_id),
                ConversationModel.user_id == str(user_id),
            )
        )
        if item is None:
            raise AppError("CONVERSATION_NOT_FOUND", "会话不存在", status_code=404)
        return item

    async def add_message(self, conversation_id: UUID, role: str, content: str) -> MessageModel:
        item = MessageModel(
            id=str(uuid4()),
            conversation_id=str(conversation_id),
            role=role,
            content=content,
            created_at=datetime.now(UTC),
        )
        self.session.add(item)
        await self.session.commit()
        return item

    async def recent_messages(self, conversation_id: UUID, limit: int = 12) -> list[dict[str, str]]:
        result = await self.session.scalars(
            select(MessageModel)
            .where(MessageModel.conversation_id == str(conversation_id))
            .order_by(MessageModel.created_at.desc())
            .limit(limit)
        )
        items = list(result)
        items.reverse()
        return [{"role": item.role, "content": item.content} for item in items]

    async def list_messages(
        self, user_id: UUID, conversation_id: UUID
    ) -> list[MessageResponse]:
        await self.get_owned(user_id, conversation_id)
        result = await self.session.scalars(
            select(MessageModel)
            .where(MessageModel.conversation_id == str(conversation_id))
            .order_by(MessageModel.created_at.asc())
        )
        return [
            MessageResponse(
                id=item.id,
                conversation_id=item.conversation_id,
                role=item.role,
                content=item.content,
                created_at=item.created_at,
            )
            for item in result
        ]

    @staticmethod
    def _conversation_response(item: ConversationModel) -> ConversationResponse:
        return ConversationResponse(
            id=item.id,
            title=item.title,
            mode=item.mode,
            created_at=item.created_at,
        )
