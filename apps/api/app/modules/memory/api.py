from uuid import UUID

from fastapi import APIRouter, Response

from app.core.security import CurrentUserDep
from app.infrastructure.db.session import SessionDep
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
