from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

MemoryType = Literal["profile", "preference", "goal", "experience"]


class MemoryResponse(BaseModel):
    id: UUID
    type: MemoryType
    content: str
    source: str
    active: bool
    pinned: bool
    updated_at: datetime


class MemoryUpdateRequest(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=1000)
    active: bool | None = None
    pinned: bool | None = None


class CreateMemoryCandidateRequest(BaseModel):
    type: MemoryType
    content: str = Field(min_length=1, max_length=1000)
    source: str = Field(default="手动添加", max_length=200)


class MemoryCandidateResponse(BaseModel):
    id: UUID
    type: MemoryType
    content: str
    source: str
    reason: str


class ConfirmMemoryRequest(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=1000)
