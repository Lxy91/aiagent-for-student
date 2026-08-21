from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class KnowledgeDocumentResponse(BaseModel):
    id: UUID
    title: str
    source: str
    trust_level: Literal["A", "B", "C"]
    status: Literal["processing", "ready", "failed"]
    chunks: int
    size_bytes: int
    created_at: datetime
    error: str | None = None
