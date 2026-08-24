from typing import Protocol

from pydantic import BaseModel, Field, HttpUrl


class SearchResult(BaseModel):
    title: str
    url: HttpUrl
    snippet: str
    source: str
    score: float | None = None
    published_at: str | None = None


class WebSearchResponse(BaseModel):
    query: str
    results: list[SearchResult] = Field(default_factory=list)
    response_time_seconds: float | None = None


class WebSearchProvider(Protocol):
    async def search(self, query: str, *, max_results: int) -> WebSearchResponse: ...
