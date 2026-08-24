from pydantic import BaseModel, Field, HttpUrl


class WebSearchInput(BaseModel):
    query: str = Field(min_length=2, max_length=300, description="需要联网检索的问题或关键词")
    max_results: int = Field(default=5, ge=1, le=8)


class WebSearchItem(BaseModel):
    title: str
    url: HttpUrl
    snippet: str
    source: str
    published_at: str | None = None


class WebSearchOutput(BaseModel):
    query: str
    results: list[WebSearchItem]
