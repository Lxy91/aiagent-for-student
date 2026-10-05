from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class CreateConversationRequest(BaseModel):
    title: str = Field(default="新对话", min_length=1, max_length=100)
    mode: Literal["standard", "temporary"] = "standard"


class ConversationResponse(BaseModel):
    id: UUID
    title: str
    mode: str
    is_pinned: bool
    is_archived: bool
    created_at: datetime


class UpdateConversationRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    is_pinned: bool | None = None
    is_archived: bool | None = None


class SendMessageRequest(BaseModel):
    content: str = Field(default="", max_length=10_000)
    attachment_ids: list[UUID] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def validate_input(self) -> "SendMessageRequest":
        self.content = self.content.strip()
        if not self.content and not self.attachment_ids:
            raise ValueError("message content or attachment is required")
        if len(set(self.attachment_ids)) != len(self.attachment_ids):
            raise ValueError("attachment ids must be unique")
        return self


class MessageAttachmentResponse(BaseModel):
    id: UUID
    title: str
    material_type: Literal["audio", "image", "document", "spreadsheet", "text"]
    mime_type: str
    status: Literal["ready", "needs_confirmation"]


class GeneratedImageResponse(BaseModel):
    id: str
    url: str
    prompt: str
    model: str


class GeneratedArtifactResponse(BaseModel):
    id: str
    filename: str
    artifact_type: Literal["docx", "xlsx"]
    mime_type: str
    size_bytes: int


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
    attachments: list[MessageAttachmentResponse] = Field(default_factory=list)
    generated_images: list[GeneratedImageResponse] = Field(default_factory=list)
    generated_artifacts: list[GeneratedArtifactResponse] = Field(default_factory=list)
