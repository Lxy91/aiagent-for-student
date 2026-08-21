from fastapi import APIRouter

from app.api.dependencies import SettingsDep
from app.infrastructure.db.session import SessionDep
from app.modules.identity.schemas import LoginRequest, RegisterRequest, SessionResponse
from app.modules.identity.service import IdentityService

router = APIRouter(prefix="/auth", tags=["identity"])


@router.post("/register", response_model=SessionResponse, status_code=201)
async def register(
    payload: RegisterRequest, settings: SettingsDep, session: SessionDep
) -> SessionResponse:
    return await IdentityService(session, settings).register(payload)


@router.post("/login", response_model=SessionResponse)
async def login(
    payload: LoginRequest, settings: SettingsDep, session: SessionDep
) -> SessionResponse:
    return await IdentityService(session, settings).login(payload)
