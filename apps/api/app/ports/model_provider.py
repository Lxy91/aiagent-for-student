from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol


class ModelProvider(Protocol):
    async def stream_chat(self, messages: Sequence[dict[str, Any]]) -> AsyncIterator[str]: ...
