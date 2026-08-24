from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

ToolEffect = Literal["read", "draft", "write", "external"]


class ToolContext(BaseModel):
    user_id: UUID
    trace_id: str
    confirmation_token: str | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    version: str
    description: str
    effect: ToolEffect
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    timeout_seconds: float
    requires_confirmation: bool
    handler: Callable[[BaseModel, ToolContext], Awaitable[BaseModel]]

    def model_tool_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name.replace(".", "__"),
                "description": self.description,
                "parameters": self.input_model.model_json_schema(),
            },
        }


class ToolManifestResponse(BaseModel):
    name: str
    version: str
    description: str
    effect: ToolEffect
    timeout_seconds: float
    requires_confirmation: bool
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]


class ToolRunResponse(BaseModel):
    id: UUID
    trace_id: str
    tool_name: str
    tool_version: str
    effect: ToolEffect
    status: str
    latency_ms: int
    input_summary: dict[str, Any]
    output_summary: dict[str, Any] | None
    error_code: str | None
