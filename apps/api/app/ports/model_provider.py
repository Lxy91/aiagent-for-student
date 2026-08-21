from collections.abc import AsyncIterator, Sequence
from typing import Protocol


class ModelProvider(Protocol):
    async def stream_chat(self, messages: Sequence[dict[str, str]]) -> AsyncIterator[str]: ...
