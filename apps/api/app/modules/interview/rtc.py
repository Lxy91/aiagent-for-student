from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import struct
from datetime import UTC, datetime
from urllib.parse import quote, urlencode, urlparse

import httpx

from app.core.config import Settings
from app.core.errors import AppError


def _length_prefixed(value: bytes) -> bytes:
    if len(value) > 65_535:
        raise ValueError("RTC token field is too long")
    return struct.pack("<H", len(value)) + value


def create_rtc_token(
    app_id: str,
    app_key: str,
    room_id: str,
    user_id: str,
    *,
    expires_in_seconds: int = 24 * 60 * 60,
    now: int | None = None,
) -> str:
    """Generate the official VeRTC v001 token without exposing AppKey to the browser."""
    issued_at = int(datetime.now(UTC).timestamp()) if now is None else now
    expires_at = issued_at + expires_in_seconds
    privileges = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
    message = b"".join(
        (
            struct.pack("<III", secrets.randbits(32), issued_at, expires_at),
            _length_prefixed(room_id.encode()),
            _length_prefixed(user_id.encode()),
            struct.pack("<H", len(privileges)),
            b"".join(struct.pack("<HI", key, value) for key, value in privileges.items()),
        )
    )
    signature = hmac.new(app_key.encode(), message, hashlib.sha256).digest()
    content = _length_prefixed(message) + _length_prefixed(signature)
    return f"001{app_id}{base64.b64encode(content).decode()}"


class VolcengineRtcClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self._client = client

    async def start_voice_chat(self, body: dict) -> dict:
        return await self._invoke("StartVoiceChat", body)

    async def stop_voice_chat(self, body: dict) -> dict:
        return await self._invoke("StopVoiceChat", body)

    async def _invoke(self, action: str, body: dict) -> dict:
        if not self.settings.volc_rtc_available:
            raise AppError(
                "VOLC_RTC_NOT_CONFIGURED",
                "火山引擎 RTC 尚未完成配置",
                status_code=503,
            )
        endpoint = self.settings.volc_rtc_endpoint.rstrip("/")
        params = {"Action": action, "Version": self.settings.volc_rtc_api_version}
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        headers = self._signed_headers(endpoint, params, payload)
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(self.settings.volc_rtc_timeout_seconds, connect=10.0)
        )
        try:
            response = await client.post(endpoint, params=params, headers=headers, content=payload)
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AppError(
                "VOLC_RTC_REQUEST_FAILED",
                "连接火山引擎 RTC 失败，请稍后重试",
                status_code=502,
                retryable=True,
            ) from exc
        finally:
            if owns_client:
                await client.aclose()
        provider_error = (data.get("ResponseMetadata") or {}).get("Error")
        if response.status_code >= 400 or provider_error:
            raise AppError(
                "VOLC_RTC_PROVIDER_ERROR",
                str((provider_error or {}).get("Message") or "火山引擎 RTC 返回错误"),
                status_code=502,
                details=[{"provider_code": (provider_error or {}).get("Code", "UNKNOWN")}],
                retryable=response.status_code >= 500,
            )
        return data

    def _signed_headers(
        self, endpoint: str, params: dict[str, str], payload: str
    ) -> dict[str, str]:
        parsed = urlparse(endpoint)
        host = parsed.netloc
        path = parsed.path or "/"
        now = datetime.now(UTC)
        x_date = now.strftime("%Y%m%dT%H%M%SZ")
        short_date = x_date[:8]
        canonical_query = urlencode(sorted(params.items()), quote_via=quote, safe="-_.~")
        canonical_headers = (
            f"content-type:application/json\nhost:{host}\nx-content-sha256:"
            f"{hashlib.sha256(payload.encode()).hexdigest()}\nx-date:{x_date}\n"
        )
        signed_headers = "content-type;host;x-content-sha256;x-date"
        canonical_request = "\n".join(
            (
                "POST",
                path,
                canonical_query,
                canonical_headers,
                signed_headers,
                hashlib.sha256(payload.encode()).hexdigest(),
            )
        )
        scope = f"{short_date}/{self.settings.volc_rtc_region}/rtc/request"
        string_to_sign = "\n".join(
            (
                "HMAC-SHA256",
                x_date,
                scope,
                hashlib.sha256(canonical_request.encode()).hexdigest(),
            )
        )
        key = self.settings.volc_secret_access_key.encode()
        for value in (short_date, self.settings.volc_rtc_region, "rtc", "request"):
            key = hmac.new(key, value.encode(), hashlib.sha256).digest()
        signature = hmac.new(key, string_to_sign.encode(), hashlib.sha256).hexdigest()
        authorization = (
            f"HMAC-SHA256 Credential={self.settings.volc_access_key_id}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        return {
            "Content-Type": "application/json",
            "Host": host,
            "X-Content-Sha256": hashlib.sha256(payload.encode()).hexdigest(),
            "X-Date": x_date,
            "Authorization": authorization,
        }
