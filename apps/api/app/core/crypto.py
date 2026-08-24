import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.errors import AppError


class CredentialCipher:
    """Encrypt connector credentials at rest using an app-secret-derived key."""

    def __init__(self, secret: str) -> None:
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise AppError(
                "CONNECTION_CREDENTIAL_INVALID",
                "连接凭据无法解密，请重新连接",
                status_code=409,
            ) from exc
