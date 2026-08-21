from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.infrastructure.db.models import MemoryCandidateModel, MemoryModel
from app.modules.memory.schemas import (
    ConfirmMemoryRequest,
    CreateMemoryCandidateRequest,
    MemoryCandidateResponse,
    MemoryResponse,
    MemoryUpdateRequest,
)


class MemoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, user_id: UUID) -> list[MemoryResponse]:
        result = await self.session.scalars(
            select(MemoryModel)
            .where(MemoryModel.user_id == str(user_id))
            .order_by(MemoryModel.pinned.desc(), MemoryModel.updated_at.desc())
        )
        return [self._memory_response(item) for item in result]

    async def propose(
        self, user_id: UUID, payload: CreateMemoryCandidateRequest
    ) -> MemoryCandidateResponse:
        item = MemoryCandidateModel(
            id=str(uuid4()),
            user_id=str(user_id),
            type=payload.type,
            content=payload.content,
            source=payload.source,
            reason="该信息较稳定，可能改善后续职场建议。",
        )
        self.session.add(item)
        await self.session.commit()
        return MemoryCandidateResponse(
            id=item.id,
            type=item.type,
            content=item.content,
            source=item.source,
            reason=item.reason,
        )

    async def confirm(
        self, user_id: UUID, candidate_id: UUID, payload: ConfirmMemoryRequest
    ) -> MemoryResponse:
        candidate = await self.session.scalar(
            select(MemoryCandidateModel).where(
                MemoryCandidateModel.id == str(candidate_id),
                MemoryCandidateModel.user_id == str(user_id),
            )
        )
        if candidate is None:
            raise AppError("MEMORY_CANDIDATE_NOT_FOUND", "候选记忆不存在", status_code=404)
        item = MemoryModel(
            id=str(uuid4()),
            user_id=str(user_id),
            type=candidate.type,
            content=payload.content or candidate.content,
            source=candidate.source,
            active=True,
            pinned=False,
            updated_at=datetime.now(UTC),
        )
        self.session.add(item)
        await self.session.delete(candidate)
        await self.session.commit()
        return self._memory_response(item)

    async def update(
        self, user_id: UUID, memory_id: UUID, payload: MemoryUpdateRequest
    ) -> MemoryResponse:
        item = await self._owned(user_id, memory_id)
        for key, value in payload.model_dump(exclude_none=True).items():
            setattr(item, key, value)
        item.updated_at = datetime.now(UTC)
        await self.session.commit()
        return self._memory_response(item)

    async def delete(self, user_id: UUID, memory_id: UUID) -> None:
        item = await self._owned(user_id, memory_id)
        await self.session.delete(item)
        await self.session.commit()

    async def _owned(self, user_id: UUID, memory_id: UUID) -> MemoryModel:
        item = await self.session.scalar(
            select(MemoryModel).where(
                MemoryModel.id == str(memory_id), MemoryModel.user_id == str(user_id)
            )
        )
        if item is None:
            raise AppError("MEMORY_NOT_FOUND", "记忆不存在", status_code=404)
        return item

    @staticmethod
    def _memory_response(item: MemoryModel) -> MemoryResponse:
        return MemoryResponse(
            id=item.id,
            type=item.type,
            content=item.content,
            source=item.source,
            active=item.active,
            pinned=item.pinned,
            updated_at=item.updated_at,
        )
