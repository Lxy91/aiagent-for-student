"""Read public page bodies through Tavily; never connect to user-supplied hosts locally."""

import ipaddress

import httpx
from pydantic import BaseModel, Field, HttpUrl, field_validator

from app.core.config import Settings
from app.core.diagnostics import safe_debug
from app.core.errors import AppError
from app.tools.contracts import ToolContext


class WebFetchInput(BaseModel):
    url: HttpUrl = Field(description="需要读取正文的公开网页 URL，优先使用搜索结果中的来源")
    max_chars: int = Field(default=16000, ge=1000, le=24000)

    @field_validator("url")
    @classmethod
    def public_url(cls, value: HttpUrl) -> HttpUrl:
        host = (value.host or "").strip("[]").lower().rstrip(".")
        if value.username or value.password or value.port not in {80, 443}:
            raise ValueError("Only public HTTP(S) pages without credentials are supported")
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            raise ValueError("Local hosts are not supported")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if "." not in host:
                raise ValueError("Public hostname required") from None
        else:
            if not address.is_global:
                raise ValueError("Private addresses are not supported")
        return value


class WebFetchOutput(BaseModel):
    url: str
    title: str
    content: str
    truncated: bool
    source: str


class WebFetchHandler:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def __call__(self, payload: WebFetchInput, context: ToolContext) -> WebFetchOutput:
        del context
        if not self.settings.online_search_available:
            raise AppError("TOOL_UNAVAILABLE", "网页读取需要配置 TAVILY_API_KEY", status_code=503)
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.web_search_timeout_seconds
            ) as client:
                response = await client.post(
                    f"{self.settings.tavily_base_url.rstrip('/')}/extract",
                    headers={"Authorization": f"Bearer {self.settings.tavily_api_key}"},
                    json={
                        "urls": [str(payload.url)],
                        "extract_depth": "basic",
                        "include_images": False,
                    },
                )
            response.raise_for_status()
            body = response.json()
            results = body.get("results") or []
            if not results or not results[0].get("raw_content"):
                raise AppError(
                    "WEB_FETCH_EMPTY",
                    "未能读取网页正文，请更换来源",
                    status_code=502,
                    details=[
                        safe_debug(
                            {
                                "provider_status": response.status_code,
                                "failed_results": body.get("failed_results", []),
                            }
                        )
                    ],
                )
            item = results[0]
            content = str(item["raw_content"])
            return WebFetchOutput(
                url=str(payload.url),
                title=item.get("title") or payload.url.host or "网页正文",
                content=content[: payload.max_chars],
                truncated=len(content) > payload.max_chars,
                source=payload.url.host or "web",
            )
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            details = {"exception_type": type(exc).__name__, "reason": str(exc)}
            provider_status = None
            if isinstance(exc, httpx.HTTPStatusError):
                provider_status = exc.response.status_code
                details.update(provider_status=provider_status, body=exc.response.text[:4000])
            if isinstance(exc, httpx.TimeoutException):
                details["timeout_seconds"] = self.settings.web_search_timeout_seconds
            raise AppError(
                "WEB_FETCH_PROVIDER_ERROR",
                "网页正文读取失败，请更换来源或稍后重试",
                status_code=502,
                details=[safe_debug(details)],
                retryable=provider_status is None
                or provider_status in {408, 429, 500, 502, 503, 504},
            ) from exc
