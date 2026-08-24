from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class CalendarDraftInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    start_at: datetime
    end_at: datetime
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=60)
    notes: str = Field(default="", max_length=1000)
    task_id: str | None = None

    @model_validator(mode="after")
    def validate_range(self) -> "CalendarDraftInput":
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be later than start_at")
        return self


class CalendarDraftOutput(BaseModel):
    action_id: str
    status: str
    title: str
    start_at: datetime
    end_at: datetime
    timezone: str
    idempotency_key: str
