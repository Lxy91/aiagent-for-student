"""Compact whole exchanges while retaining the request, plan and recent evidence."""

import json
from dataclasses import dataclass

from app.core.errors import AppError
from app.modules.chat.context import wrap_untrusted_content
from app.modules.chat.service import estimate_text_tokens

SUMMARY_MARKER = "<untrusted_execution_summary"


def runtime_tokens(messages: list[dict], tools: list[dict]) -> int:
    return estimate_text_tokens(
        json.dumps({"messages": messages, "tools": tools}, ensure_ascii=False, default=str)
    )


def bounded_text(text: str, budget: int) -> str:
    if estimate_text_tokens(text) <= budget:
        return text
    marker = "\n[执行上下文已整理，部分原文省略；必要时重新读取来源]\n"
    low, high = 0, len(text)
    best = marker
    while low <= high:
        length = (low + high) // 2
        head = length * 3 // 4
        tail = length - head
        candidate = text[:head] + marker + (text[-tail:] if tail else "")
        if estimate_text_tokens(candidate) <= budget:
            best = candidate
            low = length + 1
        else:
            high = length - 1
    return best


@dataclass
class RuntimeContext:
    messages: list[dict]
    before_tokens: int
    estimated_tokens: int
    compacted: bool = False
    removed_messages: int = 0


def compact_runtime_context(
    messages: list[dict],
    tools: list[dict],
    budget: int,
    *,
    plan: dict | None = None,
    citations: list[dict] | None = None,
    observations: list[str] | None = None,
    original_request: str | None = None,
) -> RuntimeContext:
    before = runtime_tokens(messages, tools)
    if before <= int(budget * 0.8):
        return RuntimeContext(messages, before, before)
    last_user = max((i for i, item in enumerate(messages) if item["role"] == "user"), default=0)
    anchors = [messages[0]]
    if original_request and original_request != messages[last_user].get("content"):
        anchors.append({"role": "user", "content": original_request})
    if last_user:
        anchors.append(messages[last_user])
    # One group contains the assistant call and every corresponding tool response.
    groups: list[list[dict]] = []
    for item in messages[last_user + 1 :]:
        if item["role"] == "tool" and groups:
            groups[-1].append(item)
        else:
            groups.append([item])
    kept = groups[-2:]
    removed = [item for group in groups[:-2] for item in group]
    earlier = messages[1:last_user]
    prior_summary = next(
        (item["content"] for item in earlier if SUMMARY_MARKER in str(item.get("content", ""))), ""
    )
    summary_data = {
        "plan": {
            **plan,
            "tasks": [
                {**task, "result": bounded_text(str(task.get("result") or ""), 350)}
                for task in plan.get("tasks", [])
            ],
        }
        if plan
        else None,
        "sources": [
            {
                key: bounded_text(str(value), 120) if key == "snippet" else value
                for key, value in source.items()
            }
            for source in (citations or [])
        ],
        "observations": (observations or [])[-8:],
        "earlier_context": bounded_text(prior_summary, 1000)
        if prior_summary
        else [
            {"role": item["role"], "content": bounded_text(str(item.get("content") or ""), 300)}
            for item in earlier[-6:]
        ],
        "recent_evidence": [
            {"role": item["role"], "content": bounded_text(str(item.get("content") or ""), 400)}
            for item in (removed + [message for group in kept for message in group])[-6:]
        ],
    }
    summary = {
        "role": "system",
        "content": wrap_untrusted_content(
            "execution_summary",
            json.dumps(summary_data, ensure_ascii=False),
            label="执行进度与来源摘要，继续未完成步骤，勿重复已完成工作",
        ),
    }
    base = [anchors[0], summary, *anchors[1:]]
    # The original request and saved progress are never silently discarded.
    if runtime_tokens(base, tools) > budget:
        raise AppError(
            "CONTEXT_BUDGET_EXCEEDED",
            "原始任务与执行摘要已超过上下文预算，请提高执行预算或缩小任务范围",
            status_code=422,
            details=[{"token_budget": budget, "required_tokens": runtime_tokens(base, tools)}],
        )
    target = int(budget * 0.75)
    while (
        kept and runtime_tokens(base + [item for group in kept for item in group], tools) > target
    ):
        # Preserve a compact copy of the newest complete call/result pair when possible.
        if len(kept) == 1:
            bounded_group = [dict(item) for item in kept[0]]
            for item in bounded_group:
                if item.get("content"):
                    item["content"] = bounded_text(str(item["content"]), 700)
            kept = [bounded_group]
            if runtime_tokens(base + bounded_group, tools) <= budget:
                break
        kept.pop(0)
    result = base + [item for group in kept for item in group]
    return RuntimeContext(
        result, before, runtime_tokens(result, tools), True, max(0, len(messages) - len(result))
    )
