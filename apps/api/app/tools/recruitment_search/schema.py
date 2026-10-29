from pydantic import BaseModel, Field


class RecruitmentSearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    max_results: int = Field(default=8, ge=1, le=20)


class RecruitmentSearchItem(BaseModel):
    title: str
    company: str
    city: str
    education: str
    experience: str
    salary: str
    benefits: list[str]
    work_schedule: str
    excerpt: str
    source_url: str
    score: float


class RecruitmentSearchOutput(BaseModel):
    query: str
    results: list[RecruitmentSearchItem]
