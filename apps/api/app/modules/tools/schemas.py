from typing import Any

from pydantic import BaseModel, Field


class InvokeToolRequest(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)
    confirmation_token: str | None = None
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=100)


class InvokeToolResponse(BaseModel):
    tool: str
    version: str
    effect: str
    result: dict[str, Any]
    trace_id: str
