from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class CreateConversationRequest(BaseModel):
    title: str = Field(default="新对话", min_length=1, max_length=100)
    mode: Literal["standard", "temporary"] = "standard"


class ConversationResponse(BaseModel):
    id: UUID
    title: str
    mode: str
    created_at: datetime


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)


class CitationResponse(BaseModel):
    id: str
    title: str
    url: str
    snippet: str
    source: str
    published_at: str | None = None


class ReasoningStepResponse(BaseModel):
    id: str
    title: str
    detail: str
    status: Literal["pending", "running", "completed", "failed"]
    kind: Literal["analysis", "plan", "tool", "answer"]
    elapsed_ms: int = Field(default=0, ge=0)


class MessageResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
    citations: list[CitationResponse] = Field(default_factory=list)
    reasoning_steps: list[ReasoningStepResponse] = Field(default_factory=list)
