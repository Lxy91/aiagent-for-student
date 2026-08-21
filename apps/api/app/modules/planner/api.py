from uuid import UUID

from fastapi import APIRouter

from app.core.security import CurrentUserDep
from app.infrastructure.db.session import SessionDep
from app.modules.planner.schemas import (
    ConfirmPlanRequest,
    CreatePlanDraftRequest,
    PlanDraftResponse,
    PlanResponse,
    TaskResponse,
    TaskUpdateRequest,
)
from app.modules.planner.service import PlannerService

router = APIRouter(tags=["planner"])


@router.post("/plans:draft", response_model=PlanDraftResponse, status_code=201)
async def create_plan_draft(
    payload: CreatePlanDraftRequest, current_user: CurrentUserDep, session: SessionDep
) -> PlanDraftResponse:
    return await PlannerService(session).draft(current_user.id, payload)


@router.post("/plan-drafts/{draft_id}:confirm", response_model=PlanResponse, status_code=201)
async def confirm_plan(
    draft_id: UUID, payload: ConfirmPlanRequest, current_user: CurrentUserDep, session: SessionDep
) -> PlanResponse:
    return await PlannerService(session).confirm(current_user.id, draft_id, payload)


@router.get("/plans", response_model=list[PlanResponse])
async def list_plans(current_user: CurrentUserDep, session: SessionDep) -> list[PlanResponse]:
    return await PlannerService(session).list(current_user.id)


@router.patch("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: UUID, payload: TaskUpdateRequest, current_user: CurrentUserDep, session: SessionDep
) -> TaskResponse:
    return await PlannerService(session).update_task(current_user.id, task_id, payload)
