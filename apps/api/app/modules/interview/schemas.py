from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class CreateInterviewSessionRequest(BaseModel):
    track: Literal["react", "vue", "general"] = "general"
    interview_type: Literal["technical", "hr", "mixed"] = "mixed"
    difficulty: Literal["standard", "advanced", "pressure"] = "standard"
    duration_minutes: int = Field(default=30, ge=10, le=90)
    enable_avatar: bool = False


class InterviewSessionResponse(BaseModel):
    id: UUID
    app_id: str
    room_id: str
    user_id: str
    agent_user_id: str
    task_id: str
    token: str
    avatar_wss_token: str | None = None
    avatar_image_url: str | None = None
    avatar_speaker: str = "saturn_zh_male_cixingnansang_tob"
    track: str
    interview_type: str
    difficulty: str
    duration_minutes: int
    enable_avatar: bool = False
    interview_prompt: str
    status: Literal["ready", "active", "stopped"]


class InterviewReadinessResponse(BaseModel):
    configured: bool
    provider: str = "volcengine"
    message: str
    avatar_configured: bool = False


class InterviewTranscriptEntry(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    recorded_at_seconds: int = Field(default=0, ge=0, le=7200)


class GenerateInterviewReportRequest(BaseModel):
    answers: list[InterviewTranscriptEntry] = Field(default_factory=list, max_length=100)


class InterviewScoreItem(BaseModel):
    key: Literal["fundamentals", "framework", "engineering", "communication", "problem_solving"]
    label: str
    score: int = Field(ge=0, le=100)
    comment: str


class InterviewQaReview(BaseModel):
    question: str
    answer: str
    score: int = Field(ge=0, le=100)
    feedback: str


class InterviewReportResponse(BaseModel):
    session_id: UUID
    overall_score: int = Field(ge=0, le=100)
    summary: str
    score_items: list[InterviewScoreItem]
    qa_reviews: list[InterviewQaReview]
    strengths: list[str]
    improvements: list[str]
    next_steps: list[str]
    transcript_source: Literal["browser_speech_recognition"] = "browser_speech_recognition"
    created_at: datetime
