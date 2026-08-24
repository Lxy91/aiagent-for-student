from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.infrastructure.db.models import ToolRunModel
from app.tools.contracts import ToolContext, ToolDefinition, ToolManifestResponse


def _safe_summary(value: dict[str, Any], limit: int = 500) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in value.items():
        if any(secret in key.lower() for secret in ("token", "password", "secret", "key")):
            result[key] = "[REDACTED]"
        elif isinstance(item, str):
            result[key] = item[:limit]
        elif isinstance(item, (int, float, bool)) or item is None:
            result[key] = item
        elif isinstance(item, list):
            result[key] = f"[{len(item)} items]"
        else:
            result[key] = "[object]"
    return result


class ToolRegistry:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._tools:
            raise RuntimeError(f"Tool already registered: {definition.name}")
        if definition.effect in {"write", "external"} and not definition.requires_confirmation:
            raise RuntimeError(f"Side-effecting tool must require confirmation: {definition.name}")
        self._tools[definition.name] = definition

    def get(self, name: str) -> ToolDefinition:
        normalized = name.replace("__", ".")
        try:
            return self._tools[normalized]
        except KeyError as exc:
            raise AppError("TOOL_NOT_FOUND", "工具不存在", status_code=404) from exc

    def list(self) -> list[ToolManifestResponse]:
        return [
            ToolManifestResponse(
                name=item.name,
                version=item.version,
                description=item.description,
                effect=item.effect,
                timeout_seconds=item.timeout_seconds,
                requires_confirmation=item.requires_confirmation,
                input_schema=item.input_model.model_json_schema(),
                output_schema=item.output_model.model_json_schema(),
            )
            for item in self._tools.values()
        ]

    def model_schemas(self, *, effects: set[str] | None = None) -> list[dict[str, Any]]:
        return [
            item.model_tool_schema()
            for item in self._tools.values()
            if effects is None or item.effect in effects
        ]

    async def invoke(
        self, name: str, arguments: dict[str, Any], context: ToolContext
    ) -> BaseModel:
        definition = self.get(name)
        if definition.requires_confirmation and not context.confirmation_token:
            raise AppError(
                "TOOL_CONFIRMATION_REQUIRED",
                "该工具会产生外部副作用，需要用户确认",
                status_code=409,
            )
        try:
            payload = definition.input_model.model_validate(arguments)
        except ValidationError as exc:
            raise AppError(
                "TOOL_VALIDATION_ERROR",
                "工具参数不符合约定",
                status_code=422,
                details=[{"errors": exc.errors(include_url=False)}],
            ) from exc

        serialized = payload.model_dump(mode="json")
        digest = hashlib.sha256(
            json.dumps(serialized, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        run = ToolRunModel(
            id=str(uuid4()),
            trace_id=context.trace_id,
            user_id=str(context.user_id),
            tool_name=definition.name,
            tool_version=definition.version,
            effect=definition.effect,
            status="running",
            input_digest=digest,
            input_summary=_safe_summary(serialized),
            output_summary=None,
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        self.session.add(run)
        await self.session.commit()
        started = perf_counter()
        try:
            result = await asyncio.wait_for(
                definition.handler(payload, context), timeout=definition.timeout_seconds
            )
            validated = definition.output_model.model_validate(result)
            run.status = "succeeded"
            run.output_summary = _safe_summary(validated.model_dump(mode="json"))
            return validated
        except TimeoutError as exc:
            run.status = "failed"
            run.error_code = "TOOL_TIMEOUT"
            raise AppError(
                "TOOL_TIMEOUT", "工具执行超时", status_code=504, retryable=True
            ) from exc
        except AppError as exc:
            run.status = "failed"
            run.error_code = exc.code
            raise
        except Exception as exc:
            run.status = "failed"
            run.error_code = "TOOL_EXECUTION_ERROR"
            raise AppError(
                "TOOL_EXECUTION_ERROR", "工具执行失败", status_code=502, retryable=True
            ) from exc
        finally:
            run.latency_ms = round((perf_counter() - started) * 1000)
            run.completed_at = datetime.now(UTC).replace(tzinfo=None)
            await self.session.commit()
