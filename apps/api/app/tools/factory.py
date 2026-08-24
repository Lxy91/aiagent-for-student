from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.infrastructure.search.tavily import TavilyWebSearchProvider
from app.tools.calendar_draft.handler import CalendarDraftHandler
from app.tools.calendar_draft.schema import CalendarDraftInput, CalendarDraftOutput
from app.tools.contracts import ToolDefinition
from app.tools.registry import ToolRegistry
from app.tools.web_search.handler import WebSearchHandler
from app.tools.web_search.schema import WebSearchInput, WebSearchOutput


def build_tool_registry(session: AsyncSession, settings: Settings) -> ToolRegistry:
    registry = ToolRegistry(session)
    registry.register(
        ToolDefinition(
            name="web.search",
            version="1.0.0",
            description=(
                "搜索公开互联网以回答最新、时效性强或需要外部来源的问题。"
                "返回标题、网址与摘要；不用于搜索用户私有知识库。"
            ),
            effect="read",
            input_model=WebSearchInput,
            output_model=WebSearchOutput,
            timeout_seconds=settings.web_search_timeout_seconds + 1,
            requires_confirmation=False,
            handler=WebSearchHandler(
                TavilyWebSearchProvider(settings), settings.web_search_max_results
            ),
        )
    )
    registry.register(
        ToolDefinition(
            name="calendar.create_event_draft",
            version="1.0.0",
            description=(
                "创建可供用户检查的日历事件草稿，不会写入任何外部日历。"
                "仅当用户明确要求安排时间或生成日历草稿时使用。"
            ),
            effect="draft",
            input_model=CalendarDraftInput,
            output_model=CalendarDraftOutput,
            timeout_seconds=5,
            requires_confirmation=False,
            handler=CalendarDraftHandler(session),
        )
    )
    return registry
