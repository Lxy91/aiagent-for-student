from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.dependencies import SettingsDep
from app.core.security import CurrentUserDep
from app.infrastructure.db.models import ToolRunModel
from app.infrastructure.db.session import SessionDep
from app.modules.tools.schemas import InvokeToolRequest, InvokeToolResponse
from app.tools.contracts import ToolContext, ToolManifestResponse, ToolRunResponse
from app.tools.factory import build_tool_registry

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("", response_model=list[ToolManifestResponse])
async def list_tools(
    current_user: CurrentUserDep, settings: SettingsDep, session: SessionDep
) -> list[ToolManifestResponse]:
    del current_user
    return build_tool_registry(session, settings).list()


@router.post("/{tool_name:path}:invoke", response_model=InvokeToolResponse)
async def invoke_tool(
    tool_name: str,
    payload: InvokeToolRequest,
    request: Request,
    current_user: CurrentUserDep,
    settings: SettingsDep,
    session: SessionDep,
) -> InvokeToolResponse:
    registry = build_tool_registry(session, settings)
    definition = registry.get(tool_name)
    result = await registry.invoke(
        definition.name,
        payload.arguments,
        ToolContext(
            user_id=current_user.id,
            trace_id=request.state.trace_id,
            confirmation_token=payload.confirmation_token,
            idempotency_key=payload.idempotency_key,
        ),
    )
    return InvokeToolResponse(
        tool=definition.name,
        version=definition.version,
        effect=definition.effect,
        result=result.model_dump(mode="json"),
        trace_id=request.state.trace_id,
    )


@router.get("/runs", response_model=list[ToolRunResponse])
async def list_tool_runs(
    current_user: CurrentUserDep, session: SessionDep, limit: int = 50
) -> list[ToolRunResponse]:
    result = await session.scalars(
        select(ToolRunModel)
        .where(ToolRunModel.user_id == str(current_user.id))
        .order_by(ToolRunModel.created_at.desc())
        .limit(min(max(limit, 1), 100))
    )
    return [
        ToolRunResponse(
            id=UUID(item.id),
            trace_id=item.trace_id,
            tool_name=item.tool_name,
            tool_version=item.tool_version,
            effect=item.effect,
            status=item.status,
            latency_ms=item.latency_ms,
            input_summary=item.input_summary,
            output_summary=item.output_summary,
            error_code=item.error_code,
        )
        for item in result
    ]
