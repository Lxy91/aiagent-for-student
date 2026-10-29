from pathlib import Path
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Response, UploadFile
from sqlalchemy import select

from app.api.dependencies import SettingsDep
from app.core.errors import AppError
from app.core.security import CurrentUserDep
from app.infrastructure.db.models import ResumeModel
from app.infrastructure.db.session import SessionDep
from app.modules.memory.resume import ResumeResponse, ResumeService, ResumeUpdate
from app.modules.memory.schemas import (
    ConfirmMemoryRequest,
    CreateMemoryCandidateRequest,
    MemoryCandidateResponse,
    MemoryResponse,
    MemoryUpdateRequest,
)
from app.modules.memory.service import MemoryService

router = APIRouter(tags=["memory"])


@router.get("/memories", response_model=list[MemoryResponse])
async def list_memories(current_user: CurrentUserDep, session: SessionDep) -> list[MemoryResponse]:
    return await MemoryService(session).list(current_user.id)


@router.post("/memory-candidates", response_model=MemoryCandidateResponse, status_code=201)
async def create_candidate(
    payload: CreateMemoryCandidateRequest, current_user: CurrentUserDep, session: SessionDep
) -> MemoryCandidateResponse:
    return await MemoryService(session).propose(current_user.id, payload)


@router.post(
    "/memory-candidates/{candidate_id}:confirm", response_model=MemoryResponse, status_code=201
)
async def confirm_candidate(
    candidate_id: UUID,
    payload: ConfirmMemoryRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> MemoryResponse:
    return await MemoryService(session).confirm(current_user.id, candidate_id, payload)


@router.patch("/memories/{memory_id}", response_model=MemoryResponse)
async def update_memory(
    memory_id: UUID,
    payload: MemoryUpdateRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> MemoryResponse:
    return await MemoryService(session).update(current_user.id, memory_id, payload)


@router.delete("/memories/{memory_id}", status_code=204)
async def delete_memory(
    memory_id: UUID, current_user: CurrentUserDep, session: SessionDep
) -> Response:
    await MemoryService(session).delete(current_user.id, memory_id)
    return Response(status_code=204)


@router.get("/resume", response_model=ResumeResponse | None)
async def get_resume(current_user: CurrentUserDep, session: SessionDep):
    service = ResumeService(session)
    item = await service.get(current_user.id)
    return await service.ensure_summary(item) if item else None


@router.put("/resume", response_model=ResumeResponse)
async def upload_resume(
    file: UploadFile, current_user: CurrentUserDep, session: SessionDep, settings: SettingsDep
):
    content = await file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise AppError("FILE_TOO_LARGE", "简历文件不能超过 20 MB", status_code=413)
    return await ResumeService(session).upload(current_user.id, file.filename or "resume", content)


@router.patch("/resume", response_model=ResumeResponse)
async def update_resume(payload: ResumeUpdate, current_user: CurrentUserDep, session: SessionDep):
    item = await ResumeService(session).get(current_user.id)
    if item is None:
        raise AppError("RESUME_NOT_FOUND", "请先上传简历", status_code=404)
    item.active = payload.active
    await session.commit()
    return item


@router.delete("/resume", status_code=204)
async def delete_resume(current_user: CurrentUserDep, session: SessionDep):
    item = await ResumeService(session).get(current_user.id)
    if item is not None:
        await session.delete(item)
        await session.commit()
    return Response(status_code=204)


@router.post("/resume:regenerate-summary", response_model=ResumeResponse)
async def regenerate_resume(current_user: CurrentUserDep, session: SessionDep):
    service = ResumeService(session)
    item = await service.get(current_user.id)
    if item is None:
        raise AppError("RESUME_NOT_FOUND", "请先上传简历", status_code=404)
    return await service.ensure_summary(item, force=True)


@router.get("/resume/attachment")
async def get_resume_attachment(current_user: CurrentUserDep, session: SessionDep):
    row = (
        await session.execute(
            select(ResumeModel.filename, ResumeModel.binary_content).where(
                ResumeModel.user_id == str(current_user.id)
            )
        )
    ).first()
    if row is None:
        raise AppError("RESUME_NOT_FOUND", "请先上传简历", status_code=404)
    filename, content = row
    if content is None:
        raise AppError(
            "RESUME_ATTACHMENT_MISSING",
            "这份简历上传时未保留原附件，请重新上传后查看",
            status_code=404,
        )
    media_type = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".txt": "text/plain",
        ".md": "text/plain",
    }.get(Path(filename).suffix.lower(), "application/octet-stream")
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(filename, safe='')}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
