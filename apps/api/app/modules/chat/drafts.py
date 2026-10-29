"""Collect long drafts privately and continue only when the provider reports truncation."""

from collections.abc import AsyncIterator

from app.core.errors import AppError
from app.infrastructure.llm.deepseek import DeepSeekProvider
from app.modules.chat.runtime_context import compact_runtime_context


async def stream_draft(
    provider: DeepSeekProvider,
    messages: list[dict],
    budget: int,
    *,
    plan: dict,
    original_request: str,
    citations: list[dict],
    first_text: str | None = None,
    first_truncated: bool = False,
    max_continuations: int = 2,
) -> AsyncIterator[dict]:
    working = list(messages)
    for continuation in range(max_continuations + 1):
        current = ""
        if continuation == 0 and first_text is not None:
            current = first_text
            yield {"type": "delta", "text": current}
            truncated = first_truncated
        else:
            context = compact_runtime_context(
                working,
                [],
                budget,
                plan=plan,
                citations=citations,
                original_request=original_request,
            )
            working = context.messages
            yield {
                "type": "request",
                "messages": working,
                "continuation": continuation,
                "max_tokens": provider.chat_output_limit,
            }
            async for chunk in provider.stream_chat(working):
                current += chunk
                yield {"type": "delta", "text": chunk}
            truncated = provider.last_finish_reason == "length"
        if not truncated:
            return
        if continuation == max_continuations:
            raise AppError(
                "MODEL_OUTPUT_TRUNCATED",
                "方案尚未输出完整，草稿和断点已保存，可继续补完。",
                status_code=502,
                retryable=True,
            )
        yield {
            "type": "phase",
            "detail": f"方案较长，正在从断点补完（{continuation + 1}/{max_continuations}）。",
        }
        working.extend(
            [
                {"role": "assistant", "content": current},
                {
                    "role": "system",
                    "content": "上段因输出长度上限被截断。只从断点接着补完剩余内容，"
                    "不要从头重写，不重复已输出的表格或段落；保留原日期与约束，确保所有交付章节完整。",
                },
            ]
        )
