from __future__ import annotations

import httpx

from app.core.config import Settings
from app.core.errors import AppError
from app.ports.web_search import SearchResult, WebSearchResponse


class TavilyWebSearchProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def search(self, query: str, *, max_results: int) -> WebSearchResponse:
        if not self.settings.online_search_available:
            raise AppError(
                "TOOL_UNAVAILABLE",
                "联网搜索尚未配置，请在服务端设置 TAVILY_API_KEY",
                status_code=503,
                retryable=False,
            )

        url = f"{self.settings.tavily_base_url.rstrip('/')}/search"
        headers = {
            "Authorization": f"Bearer {self.settings.tavily_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "query": query,
            "search_depth": "basic",
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
        }
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.web_search_timeout_seconds, connect=5.0)
            ) as client:
                response = await client.post(url, headers=headers, json=payload)
            if response.status_code >= 400:
                raise AppError(
                    "WEB_SEARCH_PROVIDER_ERROR",
                    "联网搜索服务暂时不可用",
                    status_code=502,
                    details=[{"provider_status": response.status_code}],
                    retryable=response.status_code in {408, 429, 500, 502, 503, 504},
                )
            body = response.json()
        except AppError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise AppError(
                "WEB_SEARCH_PROVIDER_ERROR",
                "连接联网搜索服务失败，请稍后重试",
                status_code=502,
                retryable=True,
            ) from exc

        results = []
        for item in body.get("results", []):
            if not item.get("title") or not item.get("url"):
                continue
            results.append(
                SearchResult(
                    title=item["title"],
                    url=item["url"],
                    snippet=(item.get("content") or "")[:1200],
                    source=httpx.URL(item["url"]).host or "web",
                    score=item.get("score"),
                    published_at=item.get("published_date"),
                )
            )
        return WebSearchResponse(
            query=body.get("query") or query,
            results=results,
            response_time_seconds=body.get("response_time"),
        )
