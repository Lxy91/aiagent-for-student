from app.ports.web_search import WebSearchProvider
from app.tools.contracts import ToolContext
from app.tools.web_search.schema import WebSearchInput, WebSearchItem, WebSearchOutput


class WebSearchHandler:
    def __init__(self, provider: WebSearchProvider, max_results: int) -> None:
        self.provider = provider
        self.max_results = max_results

    async def __call__(
        self, payload: WebSearchInput, context: ToolContext
    ) -> WebSearchOutput:
        del context
        response = await self.provider.search(
            payload.query, max_results=min(payload.max_results, self.max_results)
        )
        return WebSearchOutput(
            query=response.query,
            results=[
                WebSearchItem(
                    title=item.title,
                    url=item.url,
                    snippet=item.snippet,
                    source=item.source,
                    published_at=item.published_at,
                )
                for item in response.results
            ],
        )
