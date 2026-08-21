import base64
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.core.errors import AppError

bearer_scheme = HTTPBearer(auto_error=False)


class CurrentUser(BaseModel):
    id: UUID
    email: str


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    salt_text = base64.urlsafe_b64encode(salt).decode()
    digest_text = base64.urlsafe_b64encode(digest).decode()
    return f"scrypt${salt_text}${digest_text}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        _, salt_text, digest_text = encoded.split("$", 2)
        salt = base64.urlsafe_b64decode(salt_text)
        expected = base64.urlsafe_b64decode(digest_text)
        actual = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _encode_segment(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _decode_segment(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_access_token(user: CurrentUser, settings: Settings) -> str:
    header = _encode_segment(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.access_token_minutes)
    claims = {"sub": str(user.id), "email": user.email, "exp": int(expires_at.timestamp())}
    payload = _encode_segment(json.dumps(claims).encode())
    signature = hmac.new(
        settings.app_secret_key.encode(), f"{header}.{payload}".encode(), hashlib.sha256
    ).digest()
    return f"{header}.{payload}.{_encode_segment(signature)}"


def decode_access_token(token: str, settings: Settings) -> CurrentUser:
    try:
        header, payload, signature = token.split(".")
        expected = hmac.new(
            settings.app_secret_key.encode(), f"{header}.{payload}".encode(), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(_decode_segment(signature), expected):
            raise ValueError("signature")
        data = json.loads(_decode_segment(payload))
        if int(data["exp"]) < int(datetime.now(UTC).timestamp()):
            raise ValueError("expired")
        return CurrentUser(id=UUID(data["sub"]), email=data["email"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise AppError("UNAUTHORIZED", "登录状态无效或已过期", status_code=401) from exc


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CurrentUser:
    if credentials is None:
        raise AppError("UNAUTHORIZED", "请先登录", status_code=401)
    return decode_access_token(credentials.credentials, settings)


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
