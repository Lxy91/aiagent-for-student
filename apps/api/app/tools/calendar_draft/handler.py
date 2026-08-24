import hashlib
import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.infrastructure.db.models import TaskModel, ToolActionModel
from app.tools.calendar_draft.schema import CalendarDraftInput, CalendarDraftOutput
from app.tools.contracts import ToolContext


class CalendarDraftHandler:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def __call__(
        self, payload: CalendarDraftInput, context: ToolContext
    ) -> CalendarDraftOutput:
        if payload.task_id:
            task = await self.session.scalar(
                select(TaskModel).where(
                    TaskModel.id == payload.task_id,
                    TaskModel.user_id == str(context.user_id),
                )
            )
            if task is None:
                raise AppError("TASK_NOT_FOUND", "关联任务不存在", status_code=404)
        serialized = payload.model_dump(mode="json")
        idempotency_source = context.idempotency_key or json.dumps(
            serialized,
            ensure_ascii=False,
            sort_keys=True,
        )
        idempotency_key = hashlib.sha256(
            f"{context.user_id}:{idempotency_source}".encode()
        ).hexdigest()
        existing = await self.session.scalar(
            select(ToolActionModel).where(
                ToolActionModel.user_id == str(context.user_id),
                ToolActionModel.idempotency_key == idempotency_key,
            )
        )
        if existing is None:
            existing = ToolActionModel(
                id=str(uuid4()),
                user_id=str(context.user_id),
                task_id=payload.task_id,
                action_type="calendar.create_event",
                provider=None,
                effect="draft",
                status="draft",
                payload=serialized,
                idempotency_key=idempotency_key,
            )
            self.session.add(existing)
            await self.session.flush()
        return CalendarDraftOutput(
            action_id=existing.id,
            status=existing.status,
            title=payload.title,
            start_at=payload.start_at,
            end_at=payload.end_at,
            timezone=payload.timezone,
            idempotency_key=idempotency_key,
        )
