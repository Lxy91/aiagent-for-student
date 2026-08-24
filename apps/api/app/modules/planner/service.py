import logging
import secrets
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.errors import AppError
from app.infrastructure.db.models import PlanDraftModel, PlanModel, TaskModel
from app.infrastructure.llm.deepseek import DeepSeekProvider
from app.modules.planner.schemas import (
    ConfirmPlanRequest,
    CreatePlanDraftRequest,
    PlanDraftResponse,
    PlanResponse,
    TaskDraftResponse,
    TaskResponse,
    TaskUpdateRequest,
)

logger = logging.getLogger(__name__)


class GeneratedTask(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1000)
    estimated_minutes: int = Field(ge=10, le=480)
    priority: str = Field(pattern="^(high|medium|low)$")
    due_offset_days: int = Field(ge=0, le=90)
    done_definition: str = Field(min_length=1, max_length=500)
    depends_on_indexes: list[int] = Field(default_factory=list)


class GeneratedPlan(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    deliverable: str = Field(min_length=1, max_length=500)
    assumptions: list[str] = Field(min_length=1, max_length=5)
    risks: list[str] = Field(min_length=1, max_length=5)
    tasks: list[GeneratedTask] = Field(min_length=2, max_length=5)


class PlannerService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings

    async def draft(self, user_id: UUID, payload: CreatePlanDraftRequest) -> PlanDraftResponse:
        today = date.today()
        deadline = payload.deadline or today + timedelta(days=3)
        generated = await self._generate_plan(payload, deadline)
        if generated is not None:
            return await self._save_generated_draft(user_id, payload, deadline, generated)
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

    async def _generate_plan(
        self, payload: CreatePlanDraftRequest, deadline: date
    ) -> GeneratedPlan | None:
        if self.settings is None or not self.settings.deepseek_enabled:
            return None
        system_prompt = (
            "你是职场行动规划器。把目标拆为 2-5 个可执行步骤，步骤要有完成定义、估时、"
            "优先级、相对截止天数和依赖。不要输出解释，只输出 json。"
            "JSON 格式示例：{\"title\":\"计划标题\",\"deliverable\":\"最终交付物\","
            "\"assumptions\":[\"假设\"],\"risks\":[\"风险\"],\"tasks\":[{"
            "\"title\":\"步骤\",\"description\":\"具体动作\",\"estimated_minutes\":60,"
            "\"priority\":\"high\",\"due_offset_days\":1,"
            "\"done_definition\":\"可检查的完成标准\",\"depends_on_indexes\":[]}]}。"
            "depends_on_indexes 使用从 0 开始的前序步骤索引，只能依赖更早步骤。"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"目标：{payload.goal}\n截止日期：{deadline.isoformat()}\n"
                    f"期望交付物：{payload.deliverable or '请根据目标推断'}"
                ),
            },
        ]
        provider = DeepSeekProvider(self.settings)
        for attempt in range(2):
            try:
                raw = await provider.complete_json(messages)
                return GeneratedPlan.model_validate(raw)
            except ValidationError:
                messages.append(
                    {
                        "role": "user",
                        "content": "上一次 JSON 不符合字段或数量约束，请严格按示例重新输出。",
                    }
                )
            except AppError:
                if attempt == 1:
                    logger.warning("AI plan generation failed; using deterministic fallback")
        return None

    async def _save_generated_draft(
        self,
        user_id: UUID,
        payload: CreatePlanDraftRequest,
        deadline: date,
        generated: GeneratedPlan,
    ) -> PlanDraftResponse:
        task_ids = [str(uuid4()) for _ in generated.tasks]
        tasks: list[dict] = []
        for index, task in enumerate(generated.tasks):
            dependency_ids = [
                task_ids[item]
                for item in task.depends_on_indexes
                if 0 <= item < index
            ]
            tasks.append(
                {
                    "id": task_ids[index],
                    "title": task.title,
                    "description": task.description,
                    "estimated_minutes": task.estimated_minutes,
                    "priority": task.priority,
                    "due_at": min(
                        deadline, date.today() + timedelta(days=task.due_offset_days)
                    ).isoformat(),
                    "done_definition": task.done_definition,
                    "depends_on": dependency_ids,
                }
            )
        draft = PlanDraftModel(
            id=str(uuid4()),
            user_id=str(user_id),
            title=generated.title,
            goal=payload.goal,
            deliverable=payload.deliverable or generated.deliverable,
            deadline=deadline,
            assumptions=generated.assumptions,
            tasks=tasks,
            risks=generated.risks,
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
