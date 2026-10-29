from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies import SettingsDep
from app.core.security import CurrentUserDep
from app.infrastructure.db.session import SessionDep
from app.infrastructure.vector.qdrant import QdrantRecruitmentStore
from app.modules.recruitment.schemas import (
    JobImportRequest,
    JobImportResponse,
    JobResponse,
    JobSearchHit,
)
from app.modules.recruitment.service import RecruitmentService

router = APIRouter(prefix="/recruitment", tags=["recruitment"])


@router.post("/jobs/import", response_model=JobImportResponse)
async def import_jobs(
    payload: JobImportRequest,
    current_user: CurrentUserDep,
    settings: SettingsDep,
    session: SessionDep,
) -> JobImportResponse:
    del current_user
    vector_store = (
        QdrantRecruitmentStore.from_settings(settings) if settings.qdrant_available else None
    )
    return await RecruitmentService(session, vector_store).import_jobs(payload.items)


@router.get("/jobs", response_model=list[JobResponse])
async def list_jobs(
    current_user: CurrentUserDep,
    settings: SettingsDep,
    session: SessionDep,
    city: str = "",
    education: str = "",
    experience: str = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[JobResponse]:
    del current_user
    del settings
    return await RecruitmentService(session).list_jobs(
        city=city, education=education, experience=experience, limit=limit
    )


@router.get("/search", response_model=list[JobSearchHit])
async def search_jobs(
    current_user: CurrentUserDep,
    settings: SettingsDep,
    session: SessionDep,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[JobSearchHit]:
    del current_user
    vector_store = (
        QdrantRecruitmentStore.from_settings(settings) if settings.qdrant_available else None
    )
    return await RecruitmentService(session, vector_store).search(q, limit=limit)
