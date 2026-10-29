from uuid import UUID

from fastapi import APIRouter

from app.api.dependencies import SettingsDep
from app.core.security import CurrentUserDep
from app.infrastructure.db.session import SessionDep
from app.modules.interview.schemas import (
    CreateInterviewSessionRequest,
    GenerateInterviewReportRequest,
    InterviewReadinessResponse,
    InterviewReportResponse,
    InterviewSessionResponse,
)
from app.modules.interview.service import InterviewService
from app.modules.memory.resume import ResumeService

router = APIRouter(prefix="/interviews", tags=["interviews"])


@router.get("/readiness", response_model=InterviewReadinessResponse)
async def readiness(
    current_user: CurrentUserDep, settings: SettingsDep
) -> InterviewReadinessResponse:
    del current_user
    return InterviewService(settings).readiness()


@router.post("/sessions", response_model=InterviewSessionResponse, status_code=201)
async def create_session(
    payload: CreateInterviewSessionRequest,
    current_user: CurrentUserDep,
    settings: SettingsDep,
    session: SessionDep,
) -> InterviewSessionResponse:
    return InterviewService(settings).create(
        current_user.id,
        payload,
        await ResumeService(session).context(current_user.id, allow_lookup=False),
    )


@router.post("/sessions/{session_id}:start", response_model=InterviewSessionResponse)
async def start_session(
    session_id: UUID, current_user: CurrentUserDep, settings: SettingsDep
) -> InterviewSessionResponse:
    return await InterviewService(settings).start(current_user.id, session_id)


@router.post("/sessions/{session_id}:stop", response_model=InterviewSessionResponse)
async def stop_session(
    session_id: UUID, current_user: CurrentUserDep, settings: SettingsDep
) -> InterviewSessionResponse:
    return await InterviewService(settings).stop(current_user.id, session_id)


@router.post("/sessions/{session_id}:report", response_model=InterviewReportResponse)
async def generate_report(
    session_id: UUID,
    payload: GenerateInterviewReportRequest,
    current_user: CurrentUserDep,
    settings: SettingsDep,
) -> InterviewReportResponse:
    return await InterviewService(settings).generate_report(current_user.id, session_id, payload)
