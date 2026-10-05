from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

MaterialType = Literal["audio", "image", "document", "spreadsheet", "text"]
MaterialStatus = Literal["ready", "needs_confirmation", "blocked"]
PrivacyStatus = Literal["clear", "redacted", "review_required"]


class MeetingMinutesResponse(BaseModel):
    id: UUID
    source_material_id: UUID
    summary: str
    action_items: list[str]
    pending_facts: list[str]
    created_at: datetime


class WorkMaterialResponse(BaseModel):
    id: UUID
    title: str
    material_type: MaterialType
    mime_type: str
    size_bytes: int
    purpose: str
    status: MaterialStatus
    privacy_status: PrivacyStatus
    content_excerpt: str
    created_at: datetime
    minutes: MeetingMinutesResponse | None = None


class GenerateReportRequest(BaseModel):
    period_type: Literal["weekly", "monthly"] = "weekly"
    period_start: date
    period_end: date

    @model_validator(mode="after")
    def validate_period(self) -> "GenerateReportRequest":
        if self.period_end < self.period_start:
            raise ValueError("period_end must not be earlier than period_start")
        if (self.period_end - self.period_start).days > 62:
            raise ValueError("report period cannot exceed 62 days")
        return self


class SourceReference(BaseModel):
    type: Literal["task", "material"]
    id: UUID
    title: str


class ProgressReportResponse(BaseModel):
    id: UUID
    period_type: Literal["weekly", "monthly"]
    period_start: date
    period_end: date
    title: str
    sections: dict[str, list[str]]
    sources: list[SourceReference]
    created_at: datetime


class GrowthEvidenceResponse(BaseModel):
    id: UUID
    capability: str
    summary: str
    source_type: Literal["material", "task", "feedback"]
    source_id: UUID
    source_title: str
    observed_at: datetime


class LearningRecommendation(BaseModel):
    capability: str
    reason: str
    next_action: str
    evidence_count: int = Field(ge=0)


class GrowthProfileResponse(BaseModel):
    evidence: list[GrowthEvidenceResponse]
    recommendations: list[LearningRecommendation]
