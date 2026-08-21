from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, UploadFile

from app.api.dependencies import SettingsDep
from app.core.errors import AppError
from app.core.security import CurrentUserDep
from app.infrastructure.db.session import SessionDep
from app.modules.knowledge.schemas import KnowledgeDocumentResponse
from app.modules.knowledge.service import KnowledgeService

router = APIRouter(prefix="/knowledge/documents", tags=["knowledge"])


@router.get("", response_model=list[KnowledgeDocumentResponse])
async def list_documents(
    current_user: CurrentUserDep, settings: SettingsDep, session: SessionDep
) -> list[KnowledgeDocumentResponse]:
    return await KnowledgeService(session, settings.max_upload_bytes).list(current_user.id)


@router.post("", response_model=KnowledgeDocumentResponse, status_code=202)
async def upload_document(
    current_user: CurrentUserDep,
    settings: SettingsDep,
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    source: Annotated[str, Form()] = "用户上传",
) -> KnowledgeDocumentResponse:
    if not file.filename:
        raise AppError("INVALID_FILENAME", "缺少文件名", status_code=400)
    content = await file.read(settings.max_upload_bytes + 1)
    return await KnowledgeService(session, settings.max_upload_bytes).create(
        current_user.id, file.filename, content, source
    )


@router.get("/{document_id}", response_model=KnowledgeDocumentResponse)
async def get_document(
    document_id: UUID,
    current_user: CurrentUserDep,
    settings: SettingsDep,
    session: SessionDep,
) -> KnowledgeDocumentResponse:
    return await KnowledgeService(session, settings.max_upload_bytes).get(
        current_user.id, document_id
    )
