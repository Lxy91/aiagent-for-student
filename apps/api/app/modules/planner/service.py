import secrets
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.infrastructure.db.models import PlanDraftModel, PlanModel, TaskModel
from app.modules.planner.schemas import (
    ConfirmPlanRequest,
    CreatePlanDraftRequest,
    PlanDraftResponse,
    PlanResponse,
    TaskDraftResponse,
    TaskResponse,
    TaskUpdateRequest,
)


class PlannerService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def draft(self, user_id: UUID, payload: CreatePlanDraftRequest) -> PlanDraftResponse:
        today = date.today()
        deadline = payload.deadline or today + timedelta(days=3)
        task_specs = [
            (
                "明确目标与约束",
                "整理现状、可用时间、关键对象和交付要求。",
                45,
                "写出一页目标说明，包含交付物和截止时间。",
            ),
            (
                "完成核心准备工作",
                "按优先级处理最影响结果的准备事项。",
                120,
                "核心材料形成可评审的第一版。",
            ),
            (
                "检查并完成交付",
                "根据完成定义检查结果，预留一次修订。",
                60,
                "交付物通过自查，并能说明下一步。",
            ),
        ]
        tasks: list[dict] = []
        previous_id: str | None = None
        for index, (title, description, minutes, done_definition) in enumerate(task_specs):
            task_id = str(uuid4())
            tasks.append(
                {
                    "id": task_id,
                    "title": title,
                    "description": description,
                    "estimated_minutes": minutes,
                    "priority": "high" if index < 2 else "medium",
                    "due_at": min(deadline, today + timedelta(days=index + 1)).isoformat(),
                    "done_definition": done_definition,
                    "depends_on": [previous_id] if previous_id else [],
                }
            )
            previous_id = task_id
        draft = PlanDraftModel(
            id=str(uuid4()),
            user_id=str(user_id),
            title=payload.goal[:40],
            goal=payload.goal,
            deliverable=payload.deliverable or "形成可检查、可展示的结果",
            deadline=deadline,
            assumptions=["每天至少可投入 1 小时", "关键协作对象能够及时反馈"],
            tasks=tasks,
            risks=["可用时间不足时，应优先保证核心交付物"],
            clarification_needed=False,
            clarification_questions=[],
            confirmation_token=secrets.token_urlsafe(24),
            confirmed=False,
        )
        self.session.add(draft)
        await self.session.commit()
        return self._draft_response(draft)

    async def confirm(
        self, user_id: UUID, draft_id: UUID, payload: ConfirmPlanRequest
    ) -> PlanResponse:
        draft = await self.session.scalar(
            select(PlanDraftModel).where(
                PlanDraftModel.id == str(draft_id), PlanDraftModel.user_id == str(user_id)
            )
        )
        if draft is None:
            raise AppError("PLAN_DRAFT_NOT_FOUND", "计划草案不存在", status_code=404)
        if draft.confirmed:
            plan = await self.session.scalar(
                select(PlanModel)
                .options(selectinload(PlanModel.tasks))
                .where(PlanModel.source_draft_id == str(draft_id))
            )
            if plan is None:
                raise AppError("PLAN_CONFIRMATION_INCOMPLETE", "计划确认状态异常", status_code=409)
            return self._plan_response(plan)
        if not secrets.compare_digest(payload.confirmation_token, draft.confirmation_token):
            raise AppError("INVALID_CONFIRMATION_TOKEN", "确认令牌无效", status_code=403)
        plan = PlanModel(
            id=str(uuid4()),
            source_draft_id=draft.id,
            user_id=str(user_id),
            title=draft.title,
            goal=draft.goal,
            deliverable=draft.deliverable,
            deadline=draft.deadline,
            status="active",
            version=1,
            created_at=datetime.now(UTC),
        )
        for task in draft.tasks:
            plan.tasks.append(
                TaskModel(
                    id=task["id"],
                    user_id=str(user_id),
                    title=task["title"],
                    description=task["description"],
                    estimated_minutes=task["estimated_minutes"],
                    priority=task["priority"],
                    due_at=date.fromisoformat(task["due_at"]) if task["due_at"] else None,
                    done_definition=task["done_definition"],
                    depends_on=task["depends_on"],
                    status="todo",
                    completed_at=None,
                )
            )
        draft.confirmed = True
        self.session.add(plan)
        await self.session.commit()
        return self._plan_response(plan)

    async def list(self, user_id: UUID) -> list[PlanResponse]:
        result = await self.session.scalars(
            select(PlanModel)
            .options(selectinload(PlanModel.tasks))
            .where(PlanModel.user_id == str(user_id))
            .order_by(PlanModel.created_at.desc())
        )
        return [self._plan_response(item) for item in result]

    async def update_task(
        self, user_id: UUID, task_id: UUID, payload: TaskUpdateRequest
    ) -> TaskResponse:
        item = await self.session.scalar(
            select(TaskModel).where(TaskModel.id == str(task_id), TaskModel.user_id == str(user_id))
        )
        if item is None:
            raise AppError("TASK_NOT_FOUND", "任务不存在", status_code=404)
        item.status = payload.status
        item.completed_at = datetime.now(UTC) if payload.status == "done" else None
        plan = await self.session.scalar(
            select(PlanModel)
            .options(selectinload(PlanModel.tasks))
            .where(PlanModel.id == item.plan_id)
        )
        if plan is None:
            raise AppError("PLAN_NOT_FOUND", "计划不存在", status_code=404)
        plan.status = (
            "completed" if all(t.status in {"done", "cancelled"} for t in plan.tasks) else "active"
        )
        await self.session.commit()
        return self._task_response(item)

    @staticmethod
    def _draft_response(draft: PlanDraftModel) -> PlanDraftResponse:
        return PlanDraftResponse(
            id=draft.id,
            title=draft.title,
            goal=draft.goal,
            deliverable=draft.deliverable,
            deadline=draft.deadline,
            assumptions=draft.assumptions,
            tasks=[TaskDraftResponse.model_validate(task) for task in draft.tasks],
            risks=draft.risks,
            clarification_needed=draft.clarification_needed,
            clarification_questions=draft.clarification_questions,
            confirmation_token=draft.confirmation_token,
        )

    @staticmethod
    def _plan_response(plan: PlanModel) -> PlanResponse:
        return PlanResponse(
            id=plan.id,
            title=plan.title,
            goal=plan.goal,
            deliverable=plan.deliverable,
            deadline=plan.deadline,
            status=plan.status,
            version=plan.version,
            tasks=[PlannerService._task_response(task) for task in plan.tasks],
            created_at=plan.created_at,
        )

    @staticmethod
    def _task_response(task: TaskModel) -> TaskResponse:
        return TaskResponse(
            id=task.id,
            plan_id=task.plan_id,
            title=task.title,
            description=task.description,
            estimated_minutes=task.estimated_minutes,
            priority=task.priority,
            due_at=task.due_at,
            done_definition=task.done_definition,
            depends_on=task.depends_on,
            status=task.status,
            completed_at=task.completed_at,
        )
