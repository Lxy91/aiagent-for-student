from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, Response, UploadFile

from app.api.dependencies import SettingsDep
from app.core.errors import AppError
from app.core.security import CurrentUserDep
from app.infrastructure.db.session import SessionDep
from app.modules.growth.schemas import (
    GenerateReportRequest,
    GrowthProfileResponse,
    ProgressReportResponse,
    WorkMaterialResponse,
)
from app.modules.growth.service import GrowthService

router = APIRouter(tags=["growth"])


@router.get("/materials", response_model=list[WorkMaterialResponse])
async def list_materials(
    current_user: CurrentUserDep, settings: SettingsDep, session: SessionDep
) -> list[WorkMaterialResponse]:
    return await GrowthService(session, settings.max_upload_bytes).list_materials(current_user.id)


@router.post("/materials", response_model=WorkMaterialResponse, status_code=202)
async def upload_material(
    current_user: CurrentUserDep,
    settings: SettingsDep,
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    purpose: Annotated[str, Form()] = "meeting",
) -> WorkMaterialResponse:
    if not file.filename:
        raise AppError("INVALID_FILENAME", "缺少文件名", status_code=400)
    content = await file.read(settings.max_upload_bytes + 1)
    return await GrowthService(session, settings.max_upload_bytes).create_material(
        current_user.id,
        file.filename,
        file.content_type or "application/octet-stream",
        content,
        purpose,
    )


@router.get("/materials/{material_id}", response_model=WorkMaterialResponse)
async def get_material(
    material_id: UUID,
    current_user: CurrentUserDep,
    settings: SettingsDep,
    session: SessionDep,
) -> WorkMaterialResponse:
    return await GrowthService(session, settings.max_upload_bytes).get_material(
        current_user.id, material_id
    )


@router.delete("/materials/{material_id}", status_code=204)
async def delete_material(
    material_id: UUID,
    current_user: CurrentUserDep,
    settings: SettingsDep,
    session: SessionDep,
) -> Response:
    await GrowthService(session, settings.max_upload_bytes).delete_material(
        current_user.id, material_id
    )
    return Response(status_code=204)


@router.post("/reports:draft", response_model=ProgressReportResponse, status_code=201)
async def generate_report(
    payload: GenerateReportRequest,
    current_user: CurrentUserDep,
    settings: SettingsDep,
    session: SessionDep,
) -> ProgressReportResponse:
    return await GrowthService(session, settings.max_upload_bytes).generate_report(
        current_user.id, payload
    )


@router.get("/reports", response_model=list[ProgressReportResponse])
async def list_reports(
    current_user: CurrentUserDep, settings: SettingsDep, session: SessionDep
) -> list[ProgressReportResponse]:
    return await GrowthService(session, settings.max_upload_bytes).list_reports(current_user.id)


@router.get("/growth-profile", response_model=GrowthProfileResponse)
async def get_growth_profile(
    current_user: CurrentUserDep, settings: SettingsDep, session: SessionDep
) -> GrowthProfileResponse:
    return await GrowthService(session, settings.max_upload_bytes).growth_profile(current_user.id)
