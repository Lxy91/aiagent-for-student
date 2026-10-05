from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import Response

from app.core.security import CurrentUserDep
from app.infrastructure.db.session import SessionDep
from app.modules.artifacts.service import ArtifactService

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


@router.get("/{artifact_id}/download")
async def download_artifact(
    artifact_id: UUID, current_user: CurrentUserDep, session: SessionDep
) -> Response:
    artifact = await ArtifactService(session).get_owned(current_user.id, artifact_id)
    encoded_filename = quote(artifact.filename)
    return Response(
        content=artifact.binary_content,
        media_type=artifact.mime_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            "Content-Length": str(artifact.size_bytes),
            "X-Content-Type-Options": "nosniff",
        },
    )
