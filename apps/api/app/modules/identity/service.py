from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import CurrentUser, create_access_token, hash_password, verify_password
from app.infrastructure.db.models import UserModel
from app.modules.identity.schemas import (
    LoginRequest,
    RegisterRequest,
    SessionResponse,
    UserResponse,
)


class IdentityService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def register(self, payload: RegisterRequest) -> SessionResponse:
        key = payload.email.lower()
        existing = await self.session.scalar(select(UserModel).where(UserModel.email == key))
        if existing is not None:
            raise AppError("EMAIL_ALREADY_EXISTS", "该邮箱已注册", status_code=409)
        user = UserModel(
            id=str(uuid4()),
            email=key,
            display_name=payload.display_name,
            password_hash=hash_password(payload.password),
        )
        self.session.add(user)
        await self.session.commit()
        return self._session(user)

    async def login(self, payload: LoginRequest) -> SessionResponse:
        user = await self.session.scalar(
            select(UserModel).where(UserModel.email == payload.email.lower())
        )
        if user is None or not verify_password(payload.password, user.password_hash):
            raise AppError("INVALID_CREDENTIALS", "邮箱或密码错误", status_code=401)
        return self._session(user)

    def _session(self, user: UserModel) -> SessionResponse:
        current_user = CurrentUser(id=user.id, email=user.email)
        return SessionResponse(
            user=UserResponse(id=user.id, email=user.email, display_name=user.display_name),
            access_token=create_access_token(current_user, self.settings),
        )
