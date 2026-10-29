from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


class JobImportItem(BaseModel):
    source: str = Field(default="public-web", min_length=1, max_length=40)
    external_id: str = Field(min_length=1, max_length=160)
    source_url: HttpUrl
    title: str = Field(min_length=1, max_length=255)
    company: str = Field(default="", max_length=255)
    city: str = Field(default="", max_length=80)
    district: str = Field(default="", max_length=120)
    education: str = Field(default="", max_length=80)
    experience: str = Field(default="", max_length=80)
    salary_text: str = Field(default="", max_length=120)
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    salary_months: int | None = Field(default=None, ge=1, le=24)
    requirements: str = Field(default="", max_length=100_000)
    benefits: list[str] = Field(default_factory=list, max_length=100)
    work_schedule: str = Field(default="", max_length=500)
    description: str = Field(default="", max_length=100_000)
    tags: list[str] = Field(default_factory=list, max_length=100)
    published_at: datetime | None = None
    raw_json: dict = Field(default_factory=dict)


class JobImportRequest(BaseModel):
    items: list[JobImportItem] = Field(min_length=1, max_length=500)


class JobImportResponse(BaseModel):
    inserted: int
    updated: int
    unchanged: int
    chunks: int


class JobResponse(BaseModel):
    id: UUID
    source: str
    external_id: str
    source_url: str
    title: str
    company: str
    city: str
    district: str
    education: str
    experience: str
    salary_text: str
    salary_min: int | None
    salary_max: int | None
    salary_months: int | None
    requirements: str
    benefits: list[str]
    work_schedule: str
    description: str
    tags: list[str]
    status: str
    published_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime


class JobSearchHit(BaseModel):
    job: JobResponse
    score: float
    excerpt: str
