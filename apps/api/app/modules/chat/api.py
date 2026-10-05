import json
import re
from collections.abc import AsyncIterator
from time import perf_counter
from uuid import UUID, uuid4

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.api.dependencies import SettingsDep
from app.core.errors import AppError
from app.core.security import CurrentUserDep
from app.infrastructure.db.session import SessionDep
from app.infrastructure.llm.bigmodel import BigModelProvider
from app.infrastructure.llm.deepseek import DeepSeekProvider
from app.modules.artifacts.editor import (
    AttachmentEditor,
    allows_unfilled_fields,
    build_edit_plan_messages,
    editable_attachments,
    normalize_edit_plan,
    requested_docx_formatting,
    select_edit_target,
)
from app.modules.artifacts.service import (
    ArtifactService,
    artifact_generation_instruction,
    requested_artifact_types,
)
from app.modules.chat.schemas import (
    ConversationResponse,
    CreateConversationRequest,
    MessageResponse,
    SendMessageRequest,
    UpdateConversationRequest,
)
from app.modules.chat.service import (
    ConversationService,
    ExecutionNarrative,
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
IMAGE_GENERATION_MARKERS = (
    "生成图片",
    "生成一张图",
    "生成一幅图",
    "画一张",
    "画一幅",
    "创建图片",
    "制作图片",
    "文生图",
    "图文说明",
    "图文版",
    "图文展示",
    "图文形式",
    "配一张图",
    "配张图",
)
IMAGE_GENERATION_PATTERN = re.compile(
    r"(?:生成|画|绘制|创作|制作|设计|创建).{0,40}"
    r"(?:图片|图像|配图|海报|头像|插画|封面|壁纸|图)"
)
IMAGE_DIRECT_DRAW_PATTERN = re.compile(r"(?:请|帮我|给我|麻烦).{0,8}(?:画|绘制|创作).{1,60}")
IMAGE_COLLOQUIAL_PATTERN = re.compile(r"(?:给我)?来(?:一|1)?(?:张|幅).{1,60}")
IMAGE_GENERATION_CONSULTATION_PATTERNS = (
    re.compile(r"(?:如何|怎么|怎样).{0,20}(?:生成|画|绘制|制作|设计).{0,20}(?:图片|图像|图)"),
    re.compile(r"(?:生成|画|绘制|制作|设计).{0,20}(?:图片|图像|图).{0,8}(?:方法|教程|原理)"),
    re.compile(r"(?:是否支持|支不支持|支持不支持|有没有).{0,20}(?:图片生成|生成图片|绘图).{0,8}(?:能力|功能)?"),
)
PENDING_EDIT_CANCEL_MARKERS = ("算了", "不用了", "取消", "不处理了", "停止编辑")


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


def requires_image_generation(content: str) -> bool:
    normalized = re.sub(r"\s+", "", content).lower()
    if any(pattern.search(normalized) for pattern in IMAGE_GENERATION_CONSULTATION_PATTERNS):
        return False
    if any(marker in normalized for marker in IMAGE_GENERATION_MARKERS):
        return True
    return any(
        pattern.search(normalized)
        for pattern in (
            IMAGE_GENERATION_PATTERN,
            IMAGE_DIRECT_DRAW_PATTERN,
            IMAGE_COLLOQUIAL_PATTERN,
        )
    )


def image_text_response(content: str, model: str) -> str:
    topic = " ".join(content.split()).strip()[:240]
    return (
        "已为你生成图文内容。\n\n"
        f"图片主题：{topic}\n\n"
        f"生成方式：图片由 {model} 根据上述主题生成，文字说明保留在本次对话中，"
        "便于后续继续修改画面、文案或风格。"
    )


def artifact_execution_narrative(
    artifact_types: tuple[str, ...], selected_tools: list[str]
) -> ExecutionNarrative:
    labels = ["Word 文档" if item == "docx" else "Excel 表格" for item in artifact_types]
    file_label = "和".join(labels)
    if selected_tools:
        next_action = (
            f"我会先运行 {'、'.join(selected_tools)} 获取所需信息，"
            f"再整理正文并生成可下载的{file_label}。"
        )
    else:
        next_action = f"我会整理适合写入文件的完整内容，并生成可下载的{file_label}。"
    return ExecutionNarrative(
        understanding=f"你希望把本次内容整理成{file_label}并直接下载。",
        next_action=next_action,
    )


def should_resume_pending_edit(content: str) -> bool:
    normalized = re.sub(r"\s+", "", content).lower()
    return bool(normalized) and not any(
        marker in normalized for marker in PENDING_EDIT_CANCEL_MARKERS
    )


def attachment_execution_summary(
    content: str,
    attachments: list[dict[str, str]],
    vision_images: list[dict[str, str]],
) -> tuple[str, str]:
    vision_ids = {item["id"] for item in vision_images}
    descriptions: list[str] = []
    readable_count = 0
    for item in attachments:
        if item["id"] in vision_ids:
            state = "可由视觉模型读取"
            readable_count += 1
        elif item["status"] == "ready":
            state = "已解析文字内容"
            readable_count += 1
        else:
            state = "已收到，但暂未提取到文字"
        descriptions.append(f"{item['title']}（{state}）")

    request_label = content.strip() or "处理附件"
    understanding = (
        f"你希望我处理“{request_label}”。当前消息已收到 {len(attachments)} 个附件："
        f"{'；'.join(descriptions)}。"
    )
    next_action = (
        "我会结合已成功读取的附件内容完成回答，并明确区分附件原文与推断。"
        if readable_count
        else "当前附件尚无可读取内容，我会明确说明限制，不会猜测附件内容。"
    )
    return understanding, next_action


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


@router.patch("/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    conversation_id: UUID,
    payload: UpdateConversationRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> ConversationResponse:
    return await ConversationService(session).update(current_user.id, conversation_id, payload)


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
    pending_edit = None
    generated_edit = None
    attachment_ids = payload.attachment_ids
    if not attachment_ids and should_resume_pending_edit(payload.content):
        pending_edit = await service.pending_attachment_edit(conversation_id)
        if pending_edit:
            attachment_ids = [UUID(pending_edit["attachment_id"])]
        else:
            candidate = await service.latest_generated_artifact(conversation_id)
            if candidate and editable_attachments(payload.content, [candidate]):
                generated_edit = candidate
    attachments, attachment_context, vision_images = await service.resolve_attachments(
        current_user.id, attachment_ids
    )
    title_source = payload.content or "、".join(item["title"] for item in attachments)
    await service.apply_first_message_title(current_user.id, conversation_id, title_source)
    await service.add_message(
        conversation_id,
        "user",
        payload.content,
        metadata={"attachments": attachments, "attachment_context": attachment_context},
    )
    trace_id = request.state.trace_id
    registry = build_tool_registry(session, settings)

    async def event_stream() -> AsyncIterator[str]:
        started_at = perf_counter()
        response_id = uuid4()
        yield sse("message.started", {"message_id": response_id, "trace_id": trace_id})
        history = await service.recent_messages(conversation_id)
        artifact_types = requested_artifact_types(payload.content)
        artifact_instruction = artifact_generation_instruction(payload.content)
        messages: list[dict] = [
            {
                "role": "system",
                "content": (
                    "你是大学生职场适应助手。先理解问题，再给具体、尊重组织差异的建议。"
                    "沟通场景优先给可直接使用的话术，并说明使用边界。"
                    "回答使用结构清晰的 Markdown：小标题使用 ## 或 ###，重点可使用粗体，"
                    "步骤使用列表，适合对比的信息使用 GFM 表格。表格表头、分隔行和"
                    "数据行之间不要插入空行，不要将整段回答包在代码块中。"
                    "遇到最新、当前、政策、招聘行情或用户明确要求搜索的问题，应调用 web.search。"
                    "只引用工具实际返回的来源，不得伪造引用；引用使用 [1]、[2] 编号。"
                    "calendar.create_event_draft 只创建草稿，不得声称已写入外部日历。"
                    f"{artifact_instruction}"
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

        def update_step(step_id: str, title: str, detail: str, status: str, kind: str) -> dict:
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
            bigmodel = BigModelProvider(settings)
            user_request = payload.content or f"请结合附件回答：{title_source}"
            edit_candidates = (
                [generated_edit]
                if generated_edit
                else attachments
                if pending_edit
                else editable_attachments(payload.content, attachments)
            )
            if edit_candidates:
                edit_target = select_edit_target(payload.content, edit_candidates)
                if edit_target is None:
                    full_response = (
                        "检测到多个可编辑文件，请说明要修改哪一个，例如“补全文档1”，"
                        "其余文件会作为参考资料读取。"
                    )
                    yield sse("message.delta", {"text": full_response})
                    await service.add_message(conversation_id, "assistant", full_response)
                    yield sse(
                        "message.completed",
                        {
                            "message_id": response_id,
                            "finish_reason": "stop",
                            "provider": "system",
                            "model": None,
                        },
                    )
                    return
                edit_step = update_step(
                    "attachment-edit",
                    "编辑附件",
                    "正在识别文件结构并生成最小修改计划。",
                    "running",
                    "tool",
                )
                yield sse("reasoning.step", edit_step)
                source = edit_target
                editor = AttachmentEditor(session)
                filename, descriptor = await editor.describe(current_user.id, UUID(source["id"]))
                edit_request = (
                    f"原始要求：{pending_edit['original_request']}\n用户补充：{payload.content}"
                    if pending_edit
                    else payload.content
                )
                conversation_context = "\n".join(
                    f"{item.get('role', '')}: {item.get('content', '')}" for item in history[-8:]
                )
                formatting = requested_docx_formatting(edit_request, filename)
                if formatting:
                    plan_message = "已将文档中的字体颜色统一为黑色。"
                    missing_information: list[str] = []
                    changes: list[dict[str, str]] = []
                else:
                    plan_payload = await provider.complete_json(
                        build_edit_plan_messages(
                            user_request=edit_request,
                            filename=filename,
                            descriptor=descriptor,
                            conversation_context=conversation_context,
                        ),
                        max_tokens=4000,
                    )
                    plan_message, missing_information, changes = normalize_edit_plan(plan_payload)
                allow_unfilled = allows_unfilled_fields(edit_request)
                if missing_information and allow_unfilled:
                    missing_information = []
                    plan_message = (
                        "已按你的要求保留无法确认的字段，并完成其余可安全填写的内容。"
                    )
                generated_artifacts: list[dict] = []
                pending_metadata: dict[str, str] | None = None
                if missing_information:
                    questions = "\n".join(f"- {item}" for item in missing_information)
                    full_response = (
                        f"{plan_message or '补全文件前还需要确认一些信息。'}\n\n"
                        f"请补充：\n{questions}"
                    )
                    detail = "已识别模板，但关键信息不足，暂未修改原文件。"
                    pending_metadata = {
                        "attachment_id": source["id"],
                        "filename": filename,
                        "original_request": edit_request,
                    }
                else:
                    artifact, applied_changes = await editor.apply(
                        user_id=current_user.id,
                        conversation_id=conversation_id,
                        attachment_id=UUID(source["id"]),
                        user_request=edit_request,
                        changes=changes,
                        formatting=formatting,
                        allow_unchanged=allow_unfilled,
                    )
                    generated_artifacts = [artifact]
                    yield sse("artifacts", {"items": generated_artifacts})
                    full_response = (
                        f"{plan_message or '已按你的要求完成文件修改。'}\n\n"
                        f"已生成《{artifact['filename']}》，点击下方链接即可下载。"
                    )
                    detail = f"已完成 {applied_changes} 项修改并生成可下载副本。"
                yield sse("message.delta", {"text": full_response})
                yield sse(
                    "reasoning.step",
                    update_step(
                        "attachment-edit",
                        "编辑附件",
                        detail,
                        "completed",
                        "tool",
                    ),
                )
                await service.add_message(
                    conversation_id,
                    "assistant",
                    full_response,
                    metadata={
                        "reasoning_steps": reasoning_steps,
                        "generated_artifacts": generated_artifacts,
                        "pending_attachment_edit": pending_metadata,
                    },
                )
                yield sse(
                    "message.completed",
                    {
                        "message_id": response_id,
                        "finish_reason": "stop",
                        "provider": "deepseek",
                        "model": settings.deepseek_model,
                    },
                )
                return
            if requires_image_generation(payload.content) and not vision_images:
                generation_step = update_step(
                    "image-generation",
                    "生成图片",
                    f"正在使用 {settings.bigmodel_image_model} 生成图片。",
                    "running",
                    "tool",
                )
                yield sse("reasoning.step", generation_step)
                urls = await bigmodel.generate_image(payload.content)
                generated_images = [
                    {
                        "id": f"generated-{index + 1}",
                        "url": url,
                        "prompt": payload.content,
                        "model": settings.bigmodel_image_model,
                    }
                    for index, url in enumerate(urls)
                ]
                yield sse("images", {"items": generated_images})
                full_response = image_text_response(payload.content, settings.bigmodel_image_model)
                yield sse("message.delta", {"text": full_response})
                generated_artifacts = await ArtifactService(session).create_requested(
                    user_id=current_user.id,
                    conversation_id=conversation_id,
                    prompt=payload.content,
                    content=full_response,
                )
                if generated_artifacts:
                    yield sse("artifacts", {"items": generated_artifacts})
                yield sse(
                    "reasoning.step",
                    update_step(
                        "image-generation",
                        "生成图片",
                        f"已使用 {settings.bigmodel_image_model} 完成图片生成。",
                        "completed",
                        "tool",
                    ),
                )
                await service.add_message(
                    conversation_id,
                    "assistant",
                    full_response,
                    metadata={
                        "reasoning_steps": reasoning_steps,
                        "generated_images": generated_images,
                        "generated_artifacts": generated_artifacts,
                    },
                )
                yield sse(
                    "message.completed",
                    {
                        "message_id": response_id,
                        "finish_reason": "stop",
                        "provider": "bigmodel",
                        "model": settings.bigmodel_image_model,
                    },
                )
                return
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
                narrative = (
                    artifact_execution_narrative(artifact_types, selected_tools)
                    if artifact_types and iteration == 0
                    else await build_execution_narrative(
                        provider,
                        user_request=user_request,
                        selected_tools=selected_tools,
                        observations=observations,
                        iteration=iteration,
                    )
                )
                if iteration == 0 and attachments:
                    understanding, next_action = attachment_execution_summary(
                        payload.content, attachments, vision_images
                    )
                    narrative.understanding = understanding
                    narrative.next_action = next_action
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
            response_stream = (
                bigmodel.stream_vision(messages, vision_images)
                if vision_images
                else provider.stream_chat(messages)
            )
            async for chunk in response_stream:
                if await request.is_disconnected():
                    return
                full_response += chunk
                yield sse("message.delta", {"text": chunk})
            full_response = sanitize_assistant_content(full_response)
            if not full_response:
                raise AppError("MODEL_EMPTY_RESPONSE", "模型未生成可展示的回答", status_code=502)
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
            generated_artifacts = await ArtifactService(session).create_requested(
                user_id=current_user.id,
                conversation_id=conversation_id,
                prompt=payload.content,
                content=full_response,
            )
            if generated_artifacts:
                yield sse("artifacts", {"items": generated_artifacts})
            await service.add_message(
                conversation_id,
                "assistant",
                full_response,
                metadata={
                    "citations": citations,
                    "reasoning_steps": reasoning_steps,
                    "generated_artifacts": generated_artifacts,
                },
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
                    "provider": "bigmodel" if vision_images else "deepseek",
                    "model": (
                        settings.bigmodel_vision_model if vision_images else settings.deepseek_model
                    ),
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
