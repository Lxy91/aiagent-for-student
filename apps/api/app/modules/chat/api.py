import json
from collections.abc import AsyncIterator
from time import perf_counter
from uuid import UUID, uuid4

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.api.dependencies import SettingsDep
from app.core.errors import AppError
from app.core.security import CurrentUserDep
from app.infrastructure.db.session import SessionDep
from app.infrastructure.llm.deepseek import DeepSeekProvider
from app.modules.chat.schemas import (
    ConversationResponse,
    CreateConversationRequest,
    MessageResponse,
    SendMessageRequest,
)
from app.modules.chat.service import (
    ConversationService,
    build_execution_narrative,
    sanitize_assistant_content,
)
from app.tools.contracts import ToolContext
from app.tools.factory import build_tool_registry

router = APIRouter(prefix="/conversations", tags=["chat"])

DIRECT_SEARCH_MARKERS = ("联网", "搜索", "搜一下", "查一下", "检索", "上网查")
ALWAYS_CURRENT_MARKERS = ("天气", "汇率", "股价", "比分", "热搜")
RECENCY_MARKERS = ("今日", "今天", "最新", "近期", "最近", "当前", "实时", "本周", "本月", "今年")
EXTERNAL_INFO_MARKERS = (
    "新闻",
    "资讯",
    "政策",
    "法规",
    "行情",
    "招聘",
    "校招",
    "价格",
    "榜单",
    "发布",
    "动态",
    "事件",
)


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def requires_web_search(content: str) -> bool:
    normalized = content.lower()
    if any(marker in normalized for marker in DIRECT_SEARCH_MARKERS):
        return True
    if any(marker in normalized for marker in ALWAYS_CURRENT_MARKERS):
        return True
    return any(marker in normalized for marker in RECENCY_MARKERS) and any(
        marker in normalized for marker in EXTERNAL_INFO_MARKERS
    )


@router.post("", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    payload: CreateConversationRequest, current_user: CurrentUserDep, session: SessionDep
) -> ConversationResponse:
    return await ConversationService(session).create(current_user.id, payload)


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(
    current_user: CurrentUserDep, session: SessionDep
) -> list[ConversationResponse]:
    return await ConversationService(session).list(current_user.id)


@router.get("/{conversation_id}/messages", response_model=list[MessageResponse])
async def list_messages(
    conversation_id: UUID, current_user: CurrentUserDep, session: SessionDep
) -> list[MessageResponse]:
    return await ConversationService(session).list_messages(current_user.id, conversation_id)


@router.post("/{conversation_id}/messages:stream")
async def stream_message(
    conversation_id: UUID,
    payload: SendMessageRequest,
    request: Request,
    current_user: CurrentUserDep,
    settings: SettingsDep,
    session: SessionDep,
) -> StreamingResponse:
    service = ConversationService(session)
    await service.get_owned(current_user.id, conversation_id)
    await service.add_message(conversation_id, "user", payload.content)
    trace_id = request.state.trace_id
    registry = build_tool_registry(session, settings)

    async def event_stream() -> AsyncIterator[str]:
        started_at = perf_counter()
        response_id = uuid4()
        yield sse("message.started", {"message_id": response_id, "trace_id": trace_id})
        history = await service.recent_messages(conversation_id)
        messages: list[dict] = [
            {
                "role": "system",
                "content": (
                    "你是大学生职场适应助手。先理解问题，再给具体、尊重组织差异的建议。"
                    "沟通场景优先给可直接使用的话术，并说明使用边界。"
                    "遇到最新、当前、政策、招聘行情或用户明确要求搜索的问题，应调用 web.search。"
                    "只引用工具实际返回的来源，不得伪造引用；引用使用 [1]、[2] 编号。"
                    "calendar.create_event_draft 只创建草稿，不得声称已写入外部日历。"
                ),
            },
            *history,
        ]
        full_response = ""
        citations: list[dict] = []
        reasoning_steps: list[dict] = []
        observations: list[str] = []
        tool_call_count = 0
        last_plan_step: dict | None = None

        def update_step(
            step_id: str, title: str, detail: str, status: str, kind: str
        ) -> dict:
            step = {
                "id": step_id,
                "title": title,
                "detail": detail,
                "status": status,
                "kind": kind,
                "elapsed_ms": round((perf_counter() - started_at) * 1000),
            }
            for index, item in enumerate(reasoning_steps):
                if item["id"] == step_id:
                    reasoning_steps[index] = step
                    break
            else:
                reasoning_steps.append(step)
            return step

        try:
            provider = DeepSeekProvider(settings)
            search_required = requires_web_search(payload.content)
            if search_required and not settings.online_search_available:
                raise AppError(
                    "TOOL_UNAVAILABLE",
                    "联网搜索尚未配置，请由管理员设置 TAVILY_API_KEY",
                    status_code=503,
                )
            available_effects = {"draft"}
            if settings.online_search_available:
                available_effects.add("read")
            tool_schemas = registry.model_schemas(effects=available_effects)
            for iteration in range(4):
                if search_required and not settings.deepseek_enabled and iteration == 0:
                    call = {
                        "id": f"call-{uuid4()}",
                        "type": "function",
                        "function": {
                            "name": "web__search",
                            "arguments": json.dumps(
                                {
                                    "query": payload.content,
                                    "max_results": settings.web_search_max_results,
                                },
                                ensure_ascii=False,
                            ),
                        },
                    }
                    decision_message = {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [call],
                    }
                    tool_calls = [call]
                elif not settings.deepseek_enabled:
                    decision_message = None
                    tool_calls = []
                else:
                    decision_message, tool_calls = await provider.select_tool_calls(
                        messages,
                        tool_schemas,
                        force_tool_name=(
                            "web__search" if search_required and iteration == 0 else None
                        ),
                    )
                selected_tools = [
                    str((call.get("function") or {}).get("name") or "").replace("__", ".")
                    for call in tool_calls[:3]
                ]
                narrative = await build_execution_narrative(
                    provider,
                    user_request=payload.content,
                    selected_tools=selected_tools,
                    observations=observations,
                    iteration=iteration,
                )
                if iteration == 0:
                    yield sse(
                        "reasoning.step",
                        update_step(
                            "understand",
                            "当前理解",
                            narrative.understanding,
                            "completed",
                            "analysis",
                        ),
                    )
                plan_step_id = f"plan-{iteration + 1}"
                last_plan_step = update_step(
                    plan_step_id,
                    "下一步计划",
                    narrative.next_action,
                    "completed" if tool_calls else "running",
                    "plan",
                )
                yield sse("reasoning.step", last_plan_step)
                if not tool_calls:
                    break
                messages.append(decision_message)
                for call in tool_calls[:3]:
                    tool_call_count += 1
                    function = call.get("function") or {}
                    tool_name = str(function.get("name") or "").replace("__", ".")
                    try:
                        arguments = json.loads(function.get("arguments") or "{}")
                    except json.JSONDecodeError as exc:
                        raise AppError(
                            "TOOL_VALIDATION_ERROR",
                            "模型生成的工具参数无效",
                            status_code=422,
                        ) from exc
                    definition = registry.get(tool_name)
                    step_id = f"tool-{tool_call_count}"
                    yield sse(
                        "reasoning.step",
                        update_step(
                            step_id,
                            "调用工具",
                            f"正在运行 {definition.name}。",
                            "running",
                            "tool",
                        ),
                    )
                    yield sse(
                        "tool.started",
                        {
                            "tool_call_id": call.get("id"),
                            "tool": definition.name,
                            "effect": definition.effect,
                        },
                    )
                    try:
                        result = await registry.invoke(
                            definition.name,
                            arguments,
                            ToolContext(user_id=current_user.id, trace_id=trace_id),
                        )
                    except AppError:
                        yield sse(
                            "reasoning.step",
                            update_step(
                                step_id,
                                "调用工具",
                                f"运行 {definition.name} 失败。",
                                "failed",
                                "tool",
                            ),
                        )
                        raise
                    result_payload = result.model_dump(mode="json")
                    result_count = len(result_payload.get("results", []))
                    observations.append(
                        f"{definition.name} 返回 {result_count} 条结果"
                        if definition.name == "web.search"
                        else f"{definition.name} 执行完成"
                    )
                    yield sse(
                        "tool.completed",
                        {
                            "tool_call_id": call.get("id"),
                            "tool": definition.name,
                            "result_count": result_count,
                        },
                    )
                    yield sse(
                        "reasoning.step",
                        update_step(
                            step_id,
                            "观察工具结果",
                            (
                                f"运行了 {definition.name}，获得 {result_count} 条结果。"
                                if definition.name == "web.search"
                                else f"运行了 {definition.name}。"
                            ),
                            "completed",
                            "tool",
                        ),
                    )
                    if definition.name == "web.search":
                        known_urls = {item["url"] for item in citations}
                        for item in result_payload["results"]:
                            if item["url"] in known_urls:
                                continue
                            citations.append(
                                {
                                    "id": f"web-{len(citations) + 1}",
                                    "title": item["title"],
                                    "url": item["url"],
                                    "snippet": item["snippet"],
                                    "source": item["source"],
                                    "published_at": item.get("published_at"),
                                }
                            )
                            known_urls.add(item["url"])
                        citations = citations[:8]
                        yield sse("citations", {"items": citations})
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id"),
                            "content": json.dumps(result_payload, ensure_ascii=False),
                        }
                    )

            if search_required and tool_call_count == 0:
                raise AppError(
                    "TOOL_SELECTION_FAILED",
                    "模型未能生成有效的联网搜索调用，请稍后重试",
                    status_code=502,
                    retryable=True,
                )
            async for chunk in provider.stream_chat(messages):
                if await request.is_disconnected():
                    return
                full_response += chunk
                yield sse("message.delta", {"text": chunk})
            full_response = sanitize_assistant_content(full_response)
            if not full_response:
                raise AppError(
                    "MODEL_EMPTY_RESPONSE", "模型未生成可展示的回答", status_code=502
                )
            if last_plan_step is not None:
                yield sse(
                    "reasoning.step",
                    update_step(
                        last_plan_step["id"],
                        last_plan_step["title"],
                        last_plan_step["detail"],
                        "completed",
                        last_plan_step["kind"],
                    ),
                )
            await service.add_message(
                conversation_id,
                "assistant",
                full_response,
                metadata={"citations": citations, "reasoning_steps": reasoning_steps},
            )
            yield sse(
                "message.completed",
                {
                    "message_id": response_id,
                    "finish_reason": "stop",
                    "usage": None,
                    "demo_mode": not settings.deepseek_enabled,
                    "tool_calls": tool_call_count,
                    "citations": len(citations),
                },
            )
        except AppError as exc:
            yield sse(
                "error",
                {
                    "code": exc.code,
                    "message": exc.message,
                    "trace_id": trace_id,
                    "retryable": exc.retryable,
                },
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
