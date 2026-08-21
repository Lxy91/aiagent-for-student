from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.infrastructure.db.models import KnowledgeDocumentModel
from app.modules.knowledge.schemas import KnowledgeDocumentResponse

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".md", ".txt"}


class KnowledgeService:
    def __init__(self, session: AsyncSession, max_upload_bytes: int) -> None:
        self.session = session
        self.max_upload_bytes = max_upload_bytes

    async def create(
        self, user_id: UUID, filename: str, content: bytes, source: str
    ) -> KnowledgeDocumentResponse:
        extension = Path(filename).suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise AppError(
                "UNSUPPORTED_FILE_TYPE",
                "仅支持 PDF、DOCX、Markdown 和 TXT 文件",
                status_code=415,
            )
        if len(content) > self.max_upload_bytes:
            raise AppError("FILE_TOO_LARGE", "文件不能超过 20 MB", status_code=413)
        if not content:
            raise AppError("EMPTY_FILE", "文件内容为空", status_code=400)
        item = KnowledgeDocumentModel(
            id=str(uuid4()),
            owner_id=str(user_id),
            title=filename,
            source=source.strip()[:200] or "用户上传",
            trust_level="C",
            status="ready",
            chunks=max(1, len(content) // 1200),
            size_bytes=len(content),
            created_at=datetime.now(UTC),
            error=None,
        )
        self.session.add(item)
        await self.session.commit()
        return self._response(item)

    async def list(self, user_id: UUID) -> list[KnowledgeDocumentResponse]:
        result = await self.session.scalars(
            select(KnowledgeDocumentModel)
            .where(KnowledgeDocumentModel.owner_id == str(user_id))
            .order_by(KnowledgeDocumentModel.created_at.desc())
        )
        return [self._response(item) for item in result]

    async def get(self, user_id: UUID, document_id: UUID) -> KnowledgeDocumentResponse:
        item = await self.session.scalar(
            select(KnowledgeDocumentModel).where(
                KnowledgeDocumentModel.id == str(document_id),
                KnowledgeDocumentModel.owner_id == str(user_id),
            )
        )
        if item is None:
            raise AppError("DOCUMENT_NOT_FOUND", "文档不存在", status_code=404)
        return self._response(item)

    @staticmethod
    def _response(item: KnowledgeDocumentModel) -> KnowledgeDocumentResponse:
        return KnowledgeDocumentResponse(
            id=item.id,
            title=item.title,
            source=item.source,
            trust_level=item.trust_level,
            status=item.status,
            chunks=item.chunks,
            size_bytes=item.size_bytes,
            created_at=item.created_at,
            error=item.error,
        )
