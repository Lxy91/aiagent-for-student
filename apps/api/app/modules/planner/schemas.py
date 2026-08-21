from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

TaskStatus = Literal["todo", "doing", "done", "cancelled"]
TaskPriority = Literal["high", "medium", "low"]


class CreatePlanDraftRequest(BaseModel):
    goal: str = Field(min_length=3, max_length=1000)
    deadline: date | None = None
    deliverable: str | None = Field(default=None, max_length=500)


class TaskDraftResponse(BaseModel):
    id: UUID
    title: str
    description: str
    estimated_minutes: int
    priority: TaskPriority
    due_at: date | None
    done_definition: str
    depends_on: list[UUID] = Field(default_factory=list)


class PlanDraftResponse(BaseModel):
    id: UUID
    title: str
    goal: str
    deliverable: str
    deadline: date | None
    assumptions: list[str]
    tasks: list[TaskDraftResponse]
    risks: list[str]
    clarification_needed: bool
    clarification_questions: list[str]
    confirmation_token: str


class ConfirmPlanRequest(BaseModel):
    confirmation_token: str = Field(min_length=16)


class TaskResponse(TaskDraftResponse):
    plan_id: UUID
    status: TaskStatus
    completed_at: datetime | None = None


class PlanResponse(BaseModel):
    id: UUID
    title: str
    goal: str
    deliverable: str
    deadline: date | None
    status: Literal["active", "completed", "cancelled"]
    version: int
    tasks: list[TaskResponse]
    created_at: datetime


class TaskUpdateRequest(BaseModel):
    status: TaskStatus
