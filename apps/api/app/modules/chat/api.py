import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from time import perf_counter
from uuid import UUID, uuid4

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from app.api.dependencies import SettingsDep
from app.core.diagnostics import error_diagnostic, safe_debug
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
from app.modules.artifacts.quality import review_document
from app.modules.artifacts.service import (
    ArtifactService,
    artifact_generation_instruction,
    requested_artifact_types,
)
from app.modules.chat.acceptance import acceptance_question, review_acceptance
from app.modules.chat.context import sanitize_tool_result, wrap_untrusted_content
from app.modules.chat.drafts import stream_draft
from app.modules.chat.execution_plan import (
    PLAN_INSTRUCTION,
    ExecutionPlan,
    merge_plan,
    plan_tool_schema,
)
from app.modules.chat.execution_trace import (
    plan_update_detail,
    tool_completed_detail,
    tool_failed_detail,
    tool_started_detail,
)
from app.modules.chat.interrupts import (
    ExecutionInterrupt,
    UserQuestion,
    ask_user_schema,
    present_question,
)
from app.modules.chat.runtime_context import compact_runtime_context
from app.modules.chat.schemas import (
    ConversationContextResponse,
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
    estimate_message_tokens,
    estimate_text_tokens,
    sanitize_assistant_content,
)
from app.modules.memory.resume import ResumeService
from app.tools.contracts import ToolContext
from app.tools.factory import build_tool_registry

logger = logging.getLogger("uvicorn.error")

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
    re.compile(
        r"(?:是否支持|支不支持|支持不支持|有没有).{0,20}(?:图片生成|生成图片|绘图).{0,8}(?:能力|功能)?"
    ),
)
PENDING_EDIT_CANCEL_MARKERS = ("算了", "不用了", "取消", "不处理了", "停止编辑")
APPLICATION_TIMEZONE = timezone(timedelta(hours=8), "Asia/Shanghai")


def build_runtime_context(now: datetime | None = None) -> str:
    """Build authoritative, request-scoped time context for the model."""
    current = now or datetime.now(APPLICATION_TIMEZONE)
    if current.tzinfo is None:
        current = current.replace(tzinfo=APPLICATION_TIMEZONE)
    else:
        current = current.astimezone(APPLICATION_TIMEZONE)
    return (
        "\n\n<runtime_context>\n"
        f"当前日期：{current.date().isoformat()}\n"
        "时区：Asia/Shanghai (UTC+08:00)\n"
        "</runtime_context>\n"
        "上述运行时日期是日期相关问题的权威依据。回答‘现在’、‘今天’、"
        "‘今年’、‘明年’等相对时间问题时，必须据此计算，不得依赖模型训练"
        "知识猜测当前日期。如用户或历史消息中的日期与运行时日期冲突，以此处为准。"
    )


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def resolved_token_usage(
    messages: list[dict], response: str, *provider_usages: dict[str, int]
) -> dict[str, int | bool]:
    usage = {
        key: sum(int(item.get(key) or 0) for item in provider_usages)
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    }
    if usage["total_tokens"]:
        return {**usage, "estimated": False}
    prompt_tokens = estimate_text_tokens(json.dumps(messages, ensure_ascii=False, default=str))
    completion_tokens = estimate_text_tokens(response)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "estimated": True,
    }


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


@router.get("/{conversation_id}/context", response_model=ConversationContextResponse)
async def get_conversation_context(
    conversation_id: UUID,
    current_user: CurrentUserDep,
    settings: SettingsDep,
    session: SessionDep,
) -> ConversationContextResponse:
    service = ConversationService(session)
    conversation = await service.get_owned(current_user.id, conversation_id)
    window = await service.context_window(
        conversation_id, token_budget=settings.chat_history_token_budget
    )
    return ConversationContextResponse(
        message_count=window.message_count,
        estimated_tokens=window.estimated_tokens,
        token_budget=settings.chat_history_token_budget,
        trimmed_count=window.trimmed_count,
        compressed_at=conversation.context_cleared_at,
    )


@router.post("/{conversation_id}/context:compress", response_model=ConversationContextResponse)
async def compress_conversation_context(
    conversation_id: UUID,
    current_user: CurrentUserDep,
    settings: SettingsDep,
    session: SessionDep,
) -> ConversationContextResponse:
    service = ConversationService(session)
    conversation = await service.compress_context(current_user.id, conversation_id)
    window = await service.context_window(
        conversation_id, token_budget=settings.chat_history_token_budget
    )
    return ConversationContextResponse(
        message_count=window.message_count,
        estimated_tokens=window.estimated_tokens,
        token_budget=settings.chat_history_token_budget,
        compressed_at=conversation.context_cleared_at,
    )


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
    await service.get_writable(current_user.id, conversation_id)
    resume_state = None
    if payload.resume_checkpoint_id:
        resume_state = await service.claim_execution_checkpoint(
            conversation_id,
            payload.resume_checkpoint_id,
            payload.content,
            payload.resume_action,
        )
    task_content = resume_state["user_request"] if resume_state else payload.content
    pending_edit = None
    generated_edit = None
    attachment_ids = payload.attachment_ids
    if resume_state and not attachment_ids:
        attachment_ids = [UUID(item) for item in resume_state.get("attachment_ids", [])]
    if not attachment_ids and should_resume_pending_edit(payload.content):
        pending_edit = await service.pending_attachment_edit(conversation_id)
        if pending_edit:
            attachment_ids = [UUID(pending_edit["attachment_id"])]
        else:
            candidate = await service.latest_generated_artifact(conversation_id)
            if candidate and editable_attachments(payload.content, [candidate]):
                generated_edit = candidate
    attachments, attachment_context, vision_images = await service.resolve_attachments(
        current_user.id,
        attachment_ids,
        token_budget=settings.chat_attachment_token_budget,
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

        def emit(event: str, data: dict) -> str:
            if settings.agent_trace_enabled and event not in {
                "message.delta",
                "context.prompt_debug",
                "usage.updated",
                "citations",
                "images",
                "artifacts",
                "agent.debug",
            }:
                logger.info(
                    "agent trace=%s conversation=%s elapsed_ms=%s event=%s data=%s",
                    trace_id,
                    conversation_id,
                    round((perf_counter() - started_at) * 1000),
                    event,
                    json.dumps(data, ensure_ascii=False, default=str),
                )
            return sse(event, data)

        response_id = uuid4()
        debug_sequence = 0

        def debug(kind: str, data: dict) -> str:
            nonlocal debug_sequence
            debug_sequence += 1
            return emit(
                "agent.debug",
                {
                    "kind": kind,
                    "sequence": debug_sequence,
                    "trace_id": trace_id,
                    "conversation_id": str(conversation_id),
                    "elapsed_ms": round((perf_counter() - started_at) * 1000),
                    **safe_debug(data),
                },
            )

        reasoning_steps: list[dict] = []
        yield emit("message.started", {"message_id": response_id, "trace_id": trace_id})
        yield debug(
            "user",
            {
                "content": payload.content,
                "attachment_ids": payload.attachment_ids,
                "use_plan": payload.use_plan,
            },
        )
        context_window = await service.context_window(
            conversation_id, token_budget=settings.chat_history_token_budget
        )
        history = context_window.messages
        yield emit(
            "context.usage",
            {
                "message_count": context_window.message_count,
                "estimated_tokens": context_window.estimated_tokens,
                "token_budget": settings.chat_history_token_budget,
                "trimmed_count": context_window.trimmed_count,
            },
        )
        cleanup_detail = ""
        if await service.consume_context_clear_notice(conversation_id):
            cleanup_detail = "已按你的操作将此前对话压缩为摘要，本轮会继续参考摘要内容。"
        elif context_window.trimmed_count:
            await service.persist_context_compression(
                conversation_id, oldest_included_at=context_window.oldest_included_at
            )
            cleanup_detail = (
                f"对话较长，已自动压缩 {context_window.trimmed_count} 条较早消息，"
                f"保留最近 {context_window.message_count} 条继续处理。"
            )
        if cleanup_detail:
            cleanup_step = {
                "id": "context-cleanup",
                "title": "上下文整理",
                "detail": cleanup_detail,
                "status": "completed",
                "kind": "analysis",
                "elapsed_ms": int((perf_counter() - started_at) * 1000),
            }
            reasoning_steps.append(cleanup_step)
            yield emit("reasoning.step", cleanup_step)
        if "附件内容过长，已按上下文预算截取" in attachment_context:
            attachment_step = {
                "id": "attachment-context-limit",
                "title": "附件内容整理",
                "detail": "附件正文较长，已按上下文预算保留开头和结尾，避免生成过程中断。",
                "status": "completed",
                "kind": "analysis",
                "elapsed_ms": int((perf_counter() - started_at) * 1000),
            }
            reasoning_steps.append(attachment_step)
            yield emit("reasoning.step", attachment_step)
        artifact_types = requested_artifact_types(task_content)
        artifact_instruction = artifact_generation_instruction(task_content)
        resume_context = await ResumeService(session).context(current_user.id)
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
                    "搜索摘要不足以确认具体日期、时间、地点或原话时，调用 web.fetch 读取来源正文；"
                    "遇到失败可更换来源或查询，无法核验时明确说明，禁止补造细节。"
                    "calendar.create_event_draft 只创建草稿，不得声称已写入外部日历。"
                    f"{artifact_instruction}"
                    f"{build_runtime_context()}"
                    f"{resume_context}"
                    f"{PLAN_INSTRUCTION}"
                ),
            },
            *history,
        ]
        if resume_state:
            messages = resume_state["messages"]
            messages.append({"role": "user", "content": f"对暂停问题的明确答复：{payload.content}"})
            messages.append(
                {
                    "role": "system",
                    "content": "从已保存的检查点继续。保留原任务、步骤ID和已完成结果，"
                    "根据用户答复更新后续执行；不要重复执行已完成工具。只有用户明确批准的修改才能覆盖原约束。",
                }
            )
        system_tokens = estimate_message_tokens(messages[0])
        yield emit(
            "context.prompt_debug",
            {
                "messages": safe_debug(messages),
                "breakdown": {
                    "system_prompt_tokens": system_tokens,
                    "database_history_tokens": context_window.database_history_tokens,
                    "compressed_summary_tokens": context_window.summary_tokens,
                    "current_input_tokens": context_window.current_input_tokens,
                    "total_prompt_tokens": sum(
                        estimate_message_tokens(message) for message in messages
                    ),
                },
            },
        )
        full_response = ""
        citations: list[dict] = resume_state.get("citations", []) if resume_state else []
        observations: list[str] = resume_state.get("observations", []) if resume_state else []
        tool_call_count = 0
        last_plan_step: dict | None = None
        execution_plan = (
            ExecutionPlan.model_validate(resume_state["plan"])
            if resume_state and resume_state.get("plan")
            else None
        )
        if execution_plan:
            execution_plan.status = "running"
        checkpoint = None
        execution_outputs: list[dict] = resume_state.get("outputs", []) if resume_state else []
        decisions = [*resume_state.get("decisions", []), payload.content] if resume_state else []
        pending_interrupt: dict | None = None
        checkpoint_state: dict | None = None
        answer_candidate = ""
        answer_truncated = False
        defer_delivery = False
        stop_reason = ""

        async def save_progress(content: str = "", metadata: dict | None = None) -> None:
            nonlocal checkpoint
            details = {
                "reasoning_steps": reasoning_steps,
                "execution_outputs": execution_outputs,
                "execution_stop_reason": stop_reason,
                "delivery_status": "draft" if execution_plan else "final",
                **(metadata or {}),
            }
            if execution_plan is not None:
                details["execution_plan"] = execution_plan.snapshot(paused=True)
            if pending_interrupt:
                details["execution_interrupt"] = pending_interrupt
                details["execution_checkpoint"] = checkpoint_state
                details["delivery_status"] = "waiting_user"
            if execution_plan and execution_plan.status == "cancelled":
                details["delivery_status"] = "cancelled"
            is_draft = execution_plan is not None and details["delivery_status"] not in {
                "final",
                "cancelled",
            }
            if is_draft and content:
                details["draft_content"] = content
            saved_content = content or (
                f"任务执行进度已保存。{stop_reason}，可继续完成剩余步骤。"
                if stop_reason
                else "任务执行进度已保存。"
            )
            if is_draft:
                saved_content = (
                    "方案尚未定稿。确认下面的问题后，我会继续处理。"
                    if pending_interrupt
                    else "任务进度已保存，完整方案将在检查通过后展示。"
                )
            if execution_plan is not None:
                summary = "\n".join(
                    f"- [{task.status}] {task.title}：{task.result}"
                    for task in execution_plan.tasks
                )
                context_content = (content or saved_content) + "\n\n任务计划：\n" + summary
                if execution_outputs:
                    context_content += "\n\n已执行步骤的产出：\n" + "\n".join(
                        f"{item['title']}：{item['content'][:2000]}" for item in execution_outputs
                    )
            else:
                context_content = saved_content
            if checkpoint is None:
                checkpoint = await service.add_message(
                    conversation_id, "assistant", saved_content, metadata=details
                )
            else:
                checkpoint.content = saved_content
                checkpoint.metadata_json = details
            checkpoint.sanitized_content = sanitize_assistant_content(context_content)
            await session.commit()

        async def pause_for_user(question: UserQuestion, kind: str, content: str = "") -> dict:
            nonlocal pending_interrupt, checkpoint_state
            if execution_plan:
                execution_plan.status = "waiting_user"
            if checkpoint is None:
                await save_progress(content)
            pending_interrupt = ExecutionInterrupt.model_validate(
                present_question(
                    {
                        **question.model_dump(),
                        "id": str(checkpoint.id),
                        "kind": kind,
                    }
                )
            ).model_dump()
            if content and (not messages or messages[-1].get("content") != content):
                messages.append({"role": "assistant", "content": content})
            messages.append(
                {
                    "role": "system",
                    "content": (
                        f"任务检查点，类型：{kind}。待回答问题：{question.question}\n原因：{question.reason}\n"
                        "恢复后先处理此问题；缺少交付则修订，用户尚未批准的约束不可变更。"
                    ),
                }
            )
            checkpoint_state = {
                "version": 1,
                "user_request": task_content,
                "messages": messages,
                "plan": execution_plan.model_dump() if execution_plan else None,
                "outputs": execution_outputs,
                "citations": citations,
                "observations": observations,
                "decisions": decisions,
                "attachment_ids": [str(item) for item in attachment_ids],
                "draft_content": content,
                "draft_truncated": "MODEL_OUTPUT_TRUNCATED" in stop_reason
                or bool(
                    execution_plan
                    and any("截断" in issue for issue in execution_plan.acceptance_issues)
                ),
            }
            await save_progress(content or f"任务已暂停，等待你的答复：{question.question}")
            return pending_interrupt

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
            if payload.use_plan or resume_state:
                provider.chat_output_limit = settings.task_completion_max_tokens
            bigmodel = BigModelProvider(settings)
            user_request = task_content or f"请结合附件回答：{title_source}"
            if resume_state and execution_plan and payload.resume_action != "cancel":
                execution_plan.acceptance_status = "pending"
                await save_progress()
                yield emit("plan.updated", execution_plan.snapshot())
            if resume_state and payload.resume_action == "cancel":
                if execution_plan:
                    execution_plan.status = "cancelled"
                stop_reason = "用户结束了本次任务"
                await save_progress(stop_reason)
                yield emit("message.delta", {"text": stop_reason})
                if execution_plan:
                    yield emit("plan.updated", execution_plan.snapshot())
                yield emit(
                    "message.completed", {"message_id": response_id, "finish_reason": "cancelled"}
                )
                return
            edit_candidates = (
                []
                if resume_state
                else [generated_edit]
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
                    yield emit("message.delta", {"text": full_response})
                    await service.add_message(conversation_id, "assistant", full_response)
                    yield emit(
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
                yield emit("reasoning.step", edit_step)
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
                    plan_message = "已按你的要求保留无法确认的字段，并完成其余可安全填写的内容。"
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
                    yield emit("artifacts", {"items": generated_artifacts})
                    full_response = (
                        f"{plan_message or '已按你的要求完成文件修改。'}\n\n"
                        f"已生成《{artifact['filename']}》，点击下方链接即可下载。"
                    )
                    detail = f"已完成 {applied_changes} 项修改并生成可下载副本。"
                yield emit("message.delta", {"text": full_response})
                yield emit(
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
                yield emit(
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
                yield emit("reasoning.step", generation_step)
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
                yield emit("images", {"items": generated_images})
                full_response = image_text_response(payload.content, settings.bigmodel_image_model)
                yield emit("message.delta", {"text": full_response})
                generated_artifacts = await ArtifactService(session).create_requested(
                    user_id=current_user.id,
                    conversation_id=conversation_id,
                    prompt=payload.content,
                    content=full_response,
                )
                if generated_artifacts:
                    yield emit("artifacts", {"items": generated_artifacts})
                yield emit(
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
                yield emit(
                    "message.completed",
                    {
                        "message_id": response_id,
                        "finish_reason": "stop",
                        "provider": "bigmodel",
                        "model": settings.bigmodel_image_model,
                    },
                )
                return
            search_required = requires_web_search(task_content)
            if search_required and not settings.online_search_available:
                raise AppError(
                    "TOOL_UNAVAILABLE",
                    "联网搜索尚未配置，请由管理员设置 TAVILY_API_KEY",
                    status_code=503,
                )
            tool_schemas = registry.model_schemas(
                effects={"draft", "read"},
                excluded_names=set()
                if settings.online_search_available
                else {"web.search", "web.fetch"},
            )
            tool_schemas.append(plan_tool_schema())
            tool_schemas.append(ask_user_schema())
            iteration = 0
            iteration_limit = settings.agent_max_iterations
            search_done = (
                (bool(citations) or any(item.startswith("web.search") for item in observations))
                if resume_state
                else False
            )
            force_plan_update = False
            stagnant_rounds = 0
            progress_signature = ""

            def prepare_context() -> tuple[list[dict], dict]:
                context = compact_runtime_context(
                    messages,
                    tool_schemas,
                    settings.agent_context_token_budget,
                    plan=execution_plan.snapshot() if execution_plan else None,
                    citations=citations,
                    observations=observations,
                    original_request=task_content if resume_state else None,
                )
                return context.messages, {
                    "message_count": len(context.messages),
                    "estimated_tokens": context.estimated_tokens,
                    "token_budget": settings.agent_context_token_budget,
                    "trimmed_count": context.removed_messages,
                    "compacted": context.compacted,
                    "before_tokens": context.before_tokens,
                }

            while iteration < iteration_limit:
                if (
                    resume_state
                    and resume_state.get("draft_truncated")
                    and execution_plan
                    and all(task.status == "completed" for task in execution_plan.tasks)
                    and resume_state.get("draft_content")
                    and not any(
                        word in payload.content for word in ("调整输出范围", "精简", "重写")
                    )
                ):
                    answer_candidate = resume_state["draft_content"]
                    answer_truncated = True
                    break
                iteration += 1
                if await request.is_disconnected():
                    return
                messages, live_context = prepare_context()
                yield emit("context.usage", live_context)
                if live_context["compacted"]:
                    yield debug("context.compacted", live_context)
                    yield emit(
                        "reasoning.step",
                        update_step(
                            f"runtime-context-{iteration}",
                            "执行上下文整理",
                            f"已整理本轮工具上下文：{live_context['before_tokens']} → "
                            f"{live_context['estimated_tokens']} Token，"
                            "保留原始任务、计划与来源，继续执行。",
                            "completed",
                            "analysis",
                        ),
                    )
                yield emit(
                    "agent.iteration",
                    {"iteration": iteration, "max_iterations": iteration_limit},
                )
                if search_required and not settings.deepseek_enabled and iteration == 1:
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
                    forced_tool = (
                        "execution__update_plan"
                        if force_plan_update
                        or (payload.use_plan and execution_plan is None and iteration == 1)
                        else "web__search"
                        if search_required and not search_done
                        else None
                    )
                    yield debug(
                        "model.request",
                        {
                            "phase": "工具规划",
                            "iteration": iteration,
                            "model": settings.deepseek_model,
                            "messages": messages,
                            "tools": tool_schemas,
                            "tool_choice": {"type": "function", "function": {"name": forced_tool}}
                            if forced_tool
                            else "auto",
                        },
                    )
                    for attempt in range(3):
                        try:
                            decision_message, tool_calls = await provider.select_tool_calls(
                                messages,
                                tool_schemas,
                                force_tool_name=forced_tool,
                            )
                            if attempt:
                                yield emit(
                                    "reasoning.step",
                                    update_step(
                                        f"model-retry-{iteration}",
                                        "连接恢复",
                                        "模型请求已恢复，继续执行任务。",
                                        "completed",
                                        "analysis",
                                    ),
                                )
                            break
                        except AppError as exc:
                            if not exc.retryable or attempt == 2:
                                raise
                            yield debug(
                                "retry",
                                {
                                    **error_diagnostic(exc),
                                    "attempt": attempt + 1,
                                    "phase": "工具规划",
                                },
                            )
                            yield emit(
                                "reasoning.step",
                                update_step(
                                    f"model-retry-{iteration}",
                                    "连接重试",
                                    f"模型请求暂时失败，正在自动重试（{attempt + 1}/2）："
                                    f"{exc.message}",
                                    "running",
                                    "analysis",
                                ),
                            )
                            await asyncio.sleep(attempt + 1)
                            if await request.is_disconnected():
                                return
                    yield debug(
                        "model.response",
                        {
                            "phase": "工具规划",
                            "iteration": iteration,
                            "content": (decision_message or {}).get("content"),
                            "tool_calls": tool_calls,
                        },
                    )
                selected_tools = [
                    str((call.get("function") or {}).get("name") or "").replace("__", ".")
                    for call in tool_calls
                ]
                progress_only = bool(selected_tools) and all(
                    name == "execution.update_plan" for name in selected_tools
                )
                narrative = (
                    ExecutionNarrative(
                        understanding="准备调用 execution.update_plan，"
                        + ("更新已有计划。" if execution_plan else "建立任务清单。"),
                        next_action="准备核对任务步骤的实际进度。",
                    )
                    if progress_only
                    else artifact_execution_narrative(artifact_types, selected_tools)
                    if artifact_types and iteration == 1
                    else await build_execution_narrative(
                        provider,
                        user_request=user_request,
                        selected_tools=selected_tools,
                        observations=observations,
                        iteration=iteration - 1,
                    )
                )
                if provider.token_usage["total_tokens"]:
                    yield emit(
                        "usage.updated",
                        {"usage": {**provider.token_usage, "estimated": False}},
                    )
                if iteration == 1 and attachments:
                    understanding, next_action = attachment_execution_summary(
                        payload.content, attachments, vision_images
                    )
                    narrative.understanding = understanding
                    narrative.next_action = next_action
                if iteration == 1:
                    yield emit(
                        "reasoning.step",
                        update_step(
                            "understand",
                            "当前理解",
                            narrative.understanding,
                            "completed",
                            "analysis",
                        ),
                    )
                if not progress_only:
                    plan_step_id = f"plan-{iteration}"
                    last_plan_step = update_step(
                        plan_step_id,
                        "下一步计划",
                        narrative.next_action,
                        "completed" if tool_calls else "running",
                        "plan",
                    )
                    yield emit("reasoning.step", last_plan_step)
                if not tool_calls:
                    if last_plan_step:
                        yield emit(
                            "reasoning.step",
                            update_step(
                                last_plan_step["id"],
                                last_plan_step["title"],
                                last_plan_step["detail"],
                                "completed",
                                last_plan_step["kind"],
                            ),
                        )
                    runnable = (
                        [
                            task
                            for task in execution_plan.tasks
                            if task.status in {"pending", "running"}
                        ]
                        if execution_plan
                        else []
                    )
                    if runnable and settings.deepseek_enabled:
                        stagnant_rounds += 1
                        content = str((decision_message or {}).get("content") or "").strip()
                        if content:
                            execution_outputs.append(
                                {
                                    "task_id": runnable[0].id,
                                    "title": runnable[0].title,
                                    "content": content,
                                }
                            )
                            messages.append({"role": "assistant", "content": content})
                            await save_progress()
                        if stagnant_rounds >= 3:
                            stop_reason = "连续多轮未更新任务进度，已停止重复执行"
                            yield emit(
                                "reasoning.step",
                                update_step(
                                    "execution-stalled",
                                    "任务受阻",
                                    stop_reason,
                                    "failed",
                                    "plan",
                                ),
                            )
                            break
                        force_plan_update = True
                        messages.append(
                            {
                                "role": "system",
                                "content": "任务仍有未完成步骤，不得在此结束。"
                                "请依据刚才实际完成的内容调用 execution.update_plan 更新进度，"
                                "并继续下一步；若没有实际产出则继续执行当前步骤。"
                                "确实无法完成的步骤请标记 blocked 并说明原因，不得虚报完成。"
                                f"当前步骤：{runnable[0].title}",
                            }
                        )
                        yield emit(
                            "reasoning.step",
                            update_step(
                                f"auto-continue-{iteration}",
                                "继续执行",
                                f"计划尚未完成，正在推进：{runnable[0].title}。",
                                "completed",
                                "plan",
                            ),
                        )
                        continue
                    if execution_plan and any(
                        task.status == "blocked" for task in execution_plan.tasks
                    ):
                        stop_reason = "剩余步骤受阻：" + "；".join(
                            f"{task.title}：{task.result}"
                            for task in execution_plan.tasks
                            if task.status == "blocked"
                        )
                    answer_candidate = str((decision_message or {}).get("content") or "").strip()
                    answer_truncated = provider.last_selection_finish_reason == "length"
                    break
                messages.append(decision_message)
                for call_index, call in enumerate(tool_calls):
                    tool_call_count += 1
                    function = call.get("function") or {}
                    tool_name = str(function.get("name") or "").replace("__", ".")
                    call_started_at = perf_counter()
                    expected_schema = next(
                        (
                            item["function"]["parameters"]
                            for item in tool_schemas
                            if item["function"]["name"].replace("__", ".") == tool_name
                        ),
                        None,
                    )
                    call_debug = {
                        "tool_call_id": call.get("id"),
                        "tool": tool_name,
                        "trace_id": trace_id,
                        "iteration": iteration,
                    }
                    try:
                        arguments = json.loads(function.get("arguments") or "{}")
                        if not isinstance(arguments, dict):
                            raise ValueError("工具参数必须是 JSON 对象")
                    except (ValueError, TypeError) as exc:
                        failure = {
                            **call_debug,
                            "arguments": safe_debug(function.get("arguments")),
                            "code": "TOOL_VALIDATION_ERROR",
                            "status": 422,
                            "message": "模型生成的工具参数不是有效的 JSON 对象",
                            "details": [{"error": str(exc)}],
                            "retryable": False,
                            "input_schema": expected_schema,
                        }
                        yield emit(
                            "tool.started",
                            safe_debug({**call_debug, "arguments": function.get("arguments")}),
                        )
                        yield emit("tool.failed", safe_debug(failure))
                        yield emit(
                            "reasoning.step",
                            update_step(
                                f"tool-{tool_call_count}",
                                "工具参数错误",
                                f"{tool_name}：参数不是合法 JSON，本次未执行，正在修正。",
                                "failed",
                                "tool",
                            ),
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.get("id"),
                                "content": sanitize_tool_result(tool_name, failure),
                            }
                        )
                        continue
                    call_debug["arguments"] = safe_debug(arguments)
                    yield emit("tool.started", call_debug)
                    step_id = f"tool-{tool_call_count}"
                    yield emit(
                        "reasoning.step",
                        update_step(
                            step_id,
                            "调用工具",
                            tool_started_detail(tool_name, arguments),
                            "running",
                            "tool",
                        ),
                    )
                    if tool_name == "execution.ask_user":
                        try:
                            question = UserQuestion.model_validate(arguments)
                        except ValidationError as exc:
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": call.get("id"),
                                    "content": f"问题参数不合法，请修正：{exc}",
                                }
                            )
                            yield emit(
                                "tool.failed",
                                {
                                    **call_debug,
                                    "code": "TOOL_VALIDATION_ERROR",
                                    "message": str(exc),
                                },
                            )
                            yield emit(
                                "reasoning.step",
                                update_step(
                                    step_id,
                                    "问题参数错误",
                                    "execution.ask_user：问题参数未通过校验，正在修正。",
                                    "failed",
                                    "tool",
                                ),
                            )
                            continue
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.get("id"),
                                "content": "任务已暂停，等待用户答复；答复前不执行其他操作。",
                            }
                        )
                        for deferred in tool_calls[call_index + 1 :]:
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": deferred.get("id"),
                                    "content": "未执行：等待用户决定。恢复后按需要重新选择工具。",
                                }
                            )
                        question_step = update_step(
                            step_id,
                            "等待答复",
                            "execution.ask_user：已保存进度，等待你的答复。",
                            "completed",
                            "tool",
                        )
                        interrupt = await pause_for_user(question, "question")
                        yield emit("reasoning.step", question_step)
                        if execution_plan:
                            yield emit("plan.updated", execution_plan.snapshot())
                        yield emit("execution.interrupted", interrupt)
                        yield emit(
                            "message.completed",
                            {"message_id": response_id, "finish_reason": "interrupt"},
                        )
                        return
                    if tool_name == "execution.update_plan":
                        try:
                            previous_plan = execution_plan
                            execution_plan = merge_plan(execution_plan, arguments)
                            provider.chat_output_limit = settings.task_completion_max_tokens
                            yield emit(
                                "reasoning.step",
                                update_step(
                                    step_id,
                                    "更新计划",
                                    plan_update_detail(previous_plan, execution_plan),
                                    "completed",
                                    "tool",
                                ),
                            )
                            signature = json.dumps(
                                [task.model_dump() for task in execution_plan.tasks],
                                ensure_ascii=False,
                                sort_keys=True,
                            )
                            if signature != progress_signature:
                                stagnant_rounds = 0
                                progress_signature = signature
                            force_plan_update = False
                            iteration_limit = min(
                                50, max(iteration_limit, len(execution_plan.tasks) * 4 + 4)
                            )
                            await save_progress()
                            snapshot = execution_plan.snapshot()
                            yield emit("plan.updated", snapshot)
                            result_text = json.dumps(snapshot, ensure_ascii=False)
                            yield emit(
                                "tool.completed",
                                {
                                    **call_debug,
                                    "result": snapshot,
                                    "elapsed_ms": round((perf_counter() - call_started_at) * 1000),
                                },
                            )
                        except (ValidationError, ValueError) as exc:
                            result_text = "计划更新失败，请修正：" + str(exc)[:1200]
                            yield emit(
                                "reasoning.step",
                                update_step(
                                    step_id,
                                    "计划更新失败",
                                    "execution.update_plan：步骤参数未通过校验，正在修正，原计划保持不变。",
                                    "failed",
                                    "tool",
                                ),
                            )
                            yield emit(
                                "tool.failed",
                                safe_debug(
                                    {
                                        **call_debug,
                                        "code": "TOOL_VALIDATION_ERROR",
                                        "status": 422,
                                        "message": "计划参数不符合约定",
                                        "retryable": False,
                                        "details": exc.errors(
                                            include_url=False, include_context=False
                                        )
                                        if isinstance(exc, ValidationError)
                                        else [{"message": str(exc)}],
                                        "input_schema": expected_schema,
                                    }
                                ),
                            )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.get("id"),
                                "content": result_text,
                            }
                        )
                        continue
                    if tool_name == "web.search":
                        search_done = True
                    try:
                        definition = registry.get(tool_name)
                        result = await registry.invoke(
                            definition.name,
                            arguments,
                            ToolContext(user_id=current_user.id, trace_id=trace_id),
                        )
                    except AppError as exc:
                        yield emit(
                            "tool.failed",
                            {
                                **call_debug,
                                **error_diagnostic(exc),
                                "input_schema": safe_debug(expected_schema),
                                "elapsed_ms": round((perf_counter() - call_started_at) * 1000),
                            },
                        )
                        yield emit(
                            "reasoning.step",
                            update_step(
                                step_id,
                                "调用工具",
                                tool_failed_detail(tool_name, arguments, exc.message, exc.code),
                                "failed",
                                "tool",
                            ),
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.get("id"),
                                "content": sanitize_tool_result(
                                    tool_name,
                                    {
                                        **error_diagnostic(exc),
                                        "input_schema": expected_schema,
                                    },
                                ),
                            }
                        )
                        observations.append(f"{tool_name} 失败：{exc.code}，{exc.message}")
                        continue
                    result_payload = result.model_dump(mode="json")
                    result_count = len(result_payload.get("results", []))
                    observations.append(
                        f"{definition.name} 返回 {result_count} 条结果"
                        if definition.name == "web.search"
                        else f"{definition.name} 执行完成"
                    )
                    yield emit(
                        "tool.completed",
                        {
                            **call_debug,
                            "result_count": result_count,
                            "result": safe_debug(result_payload),
                            "elapsed_ms": round((perf_counter() - call_started_at) * 1000),
                        },
                    )
                    yield emit(
                        "reasoning.step",
                        update_step(
                            step_id,
                            "观察工具结果",
                            tool_completed_detail(definition.name, arguments, result_payload),
                            "completed",
                            "tool",
                        ),
                    )
                    if definition.name in {"web.search", "web.fetch"}:
                        known_urls = {item["url"] for item in citations}
                        source_results = result_payload.get("results", [])
                        if definition.name == "web.fetch":
                            source_results = [
                                {**result_payload, "snippet": result_payload["content"][:1200]}
                            ]
                        for item in source_results:
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
                        yield emit("citations", {"items": citations})
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id"),
                            "content": sanitize_tool_result(definition.name, result_payload),
                        }
                    )

            else:
                stop_reason = "已达到本次执行轮数上限"
                yield emit(
                    "agent.limit_reached",
                    {
                        "max_iterations": iteration_limit,
                        "tool_calls": tool_call_count,
                    },
                )
                yield emit(
                    "reasoning.step",
                    update_step(
                        "iteration-limit",
                        "任务暂停",
                        "已达到本次执行轮数上限，将汇总已完成结果；未完成步骤保留在计划中。",
                        "failed",
                        "plan",
                    ),
                )
                messages.append(
                    {
                        "role": "system",
                        "content": "已达到工具迭代上限。停止调用工具，基于已有结果回答，"
                        "明确说明尚未完成的核验和信息缺口，不得声称任务已经全部完成。",
                    }
                )

            if execution_plan is not None and stop_reason:
                execution_plan.explanation = stop_reason
            yield emit("agent.answer_started", {"tool_calls": tool_call_count})
            if search_required and not search_done:
                raise AppError(
                    "TOOL_SELECTION_FAILED",
                    "模型未能生成有效的联网搜索调用，请稍后重试",
                    status_code=502,
                    retryable=True,
                )
            messages, live_context = prepare_context()
            yield emit("context.usage", live_context)
            if live_context["compacted"]:
                yield debug("context.compacted", live_context)

            def saved_output_text() -> str:
                parts = []
                latest = {
                    item.get("task_id", str(index)): item
                    for index, item in enumerate(execution_outputs)
                }
                for item in [] if resume_state and answer_candidate else latest.values():
                    if item["content"] not in parts:
                        parts.append(item["content"])
                if answer_candidate and answer_candidate not in parts:
                    parts.append(answer_candidate)
                return "\n\n".join(parts)

            reuse_outputs = execution_plan is not None and bool(
                execution_outputs or answer_candidate
            )
            defer_delivery = execution_plan is not None
            yield debug(
                "assistant.output" if reuse_outputs else "model.request",
                {
                    "phase": "生成回答",
                    "messages": messages,
                    "model": settings.bigmodel_vision_model
                    if vision_images
                    else settings.deepseek_model,
                    "max_tokens": provider.chat_output_limit,
                },
            )
            if defer_delivery:
                yield emit(
                    "execution.phase",
                    {"phase": "drafting", "detail": "正在生成草稿，检查通过后展示完整方案。"},
                )
                async for event in stream_draft(
                    provider,
                    messages,
                    settings.agent_context_token_budget,
                    plan=execution_plan.model_dump(),
                    original_request=task_content,
                    citations=citations,
                    first_text=saved_output_text() if reuse_outputs else None,
                    first_truncated=answer_truncated,
                ):
                    if await request.is_disconnected():
                        return
                    if event["type"] == "delta":
                        full_response += event["text"]
                    elif event["type"] == "phase":
                        yield emit(
                            "execution.phase", {"phase": "drafting", "detail": event["detail"]}
                        )
                    else:
                        yield debug("model.request", {"phase": "补完草稿", **event})
            else:
                response_stream = (
                    bigmodel.stream_vision(messages, vision_images)
                    if vision_images
                    else provider.stream_chat(messages)
                )
                async for chunk in response_stream:
                    if await request.is_disconnected():
                        return
                    full_response += chunk
                    yield emit("message.delta", {"text": chunk})
            full_response = sanitize_assistant_content(full_response)
            if not full_response:
                raise AppError("MODEL_EMPTY_RESPONSE", "模型未生成可展示的回答", status_code=502)
            if execution_plan is not None:
                if all(task.status == "completed" for task in execution_plan.tasks):
                    yield emit(
                        "execution.phase",
                        {
                            "phase": "checking",
                            "detail": "草稿已生成，正在检查内容、工时和日期；还不是最终方案。",
                        },
                    )
                    yield emit(
                        "reasoning.step",
                        update_step(
                            "task-acceptance",
                            "任务验收",
                            "正在独立核对交付、用户约束与容量计算。",
                            "running",
                            "analysis",
                        ),
                    )
                    for revision in range(settings.task_acceptance_max_revisions + 1):
                        yield emit(
                            "execution.phase",
                            {
                                "phase": "checking",
                                "detail": "正在检查草稿，正文将在检查通过后展示。",
                            },
                        )
                        report = await review_acceptance(
                            provider,
                            task_content,
                            execution_plan.model_dump(),
                            full_response,
                            decisions,
                        )
                        execution_plan.acceptance_status = report.status
                        execution_plan.acceptance_issues = report.issues
                        yield debug(
                            "task.acceptance", {**report.model_dump(), "revision": revision}
                        )
                        if (
                            report.review_error
                            and revision < settings.task_acceptance_max_revisions
                        ):
                            yield emit(
                                "reasoning.step",
                                update_step(
                                    "task-acceptance",
                                    "重试检查",
                                    f"检查暂时没有完成，正在自动重试（{revision + 1}/"
                                    f"{settings.task_acceptance_max_revisions}）。",
                                    "running",
                                    "analysis",
                                ),
                            )
                            await asyncio.sleep(1)
                            if await request.is_disconnected():
                                return
                            continue
                        if (
                            report.status in {"passed", "needs_input"}
                            or report.review_error
                            or revision >= settings.task_acceptance_max_revisions
                        ):
                            break
                        yield emit(
                            "reasoning.step",
                            update_step(
                                "task-acceptance",
                                "自动修订",
                                f"正在修正计算和排期问题（{revision + 1}/"
                                f"{settings.task_acceptance_max_revisions}），无需你处理。",
                                "running",
                                "analysis",
                            ),
                        )
                        yield emit(
                            "execution.phase",
                            {
                                "phase": "revising",
                                "detail": f"正在修正草稿（{revision + 1}/"
                                f"{settings.task_acceptance_max_revisions}），检查通过后展示。",
                            },
                        )
                        messages.extend(
                            [
                                {"role": "assistant", "content": full_response},
                                {
                                    "role": "system",
                                    "content": (
                                        "内部检查发现以下问题，请自行修订并输出完整方案，不要只解释错误或要求用户排错。"
                                        "保留用户原约束、原计划日期、任务范围和已批准的决定。"
                                        "数字加总、日周上限、截止日期和依赖必须逐项校验；"
                                        "不得把硬约束改成平均值，也不得改休息日或把排程整体后移。"
                                        "只有用户原始要求本身确实互相冲突时，才明确提出一个简短的取舍问题。"
                                        "待修订问题（内部参考，不要原样输出）："
                                        + wrap_untrusted_content(
                                            "repair_findings",
                                            json.dumps(report.issues, ensure_ascii=False),
                                        )
                                    ),
                                },
                            ]
                        )
                        messages, live_context = prepare_context()
                        yield emit("context.usage", live_context)
                        yield debug(
                            "model.request",
                            {
                                "phase": "自动修订",
                                "messages": messages,
                                "model": settings.deepseek_model,
                            },
                        )
                        revised = ""
                        async for event in stream_draft(
                            provider,
                            messages,
                            settings.agent_context_token_budget,
                            plan=execution_plan.model_dump(),
                            original_request=task_content,
                            citations=citations,
                        ):
                            if await request.is_disconnected():
                                return
                            if event["type"] == "delta":
                                revised += event["text"]
                                full_response = revised
                            elif event["type"] == "phase":
                                yield emit(
                                    "execution.phase",
                                    {"phase": "revising", "detail": event["detail"]},
                                )
                            else:
                                yield debug("model.request", {"phase": "补完修订稿", **event})
                        revised = sanitize_assistant_content(revised)
                        if not revised:
                            raise AppError(
                                "MODEL_EMPTY_RESPONSE", "自动修订未生成内容", status_code=502
                            )
                        full_response = revised
                    yield emit(
                        "reasoning.step",
                        update_step(
                            "task-acceptance",
                            "任务验收",
                            "任务验收通过。"
                            if report.status == "passed"
                            else "需要你决定一项安排。"
                            if report.status == "needs_input"
                            else "方案已保存，仍有检查项需要继续处理。",
                            "completed" if report.status == "passed" else "failed",
                            "analysis",
                        ),
                    )
                    if report.status == "failed":
                        stop_reason = (
                            "检查服务暂时不可用，草稿已保存，本次未完成验收。"
                            if report.review_error
                            else "自动修订后仍未通过检查，草稿已保存，本次未能交付合格方案。"
                        )
                        execution_plan.status = "paused"
                        execution_plan.explanation = stop_reason
                        await save_progress(full_response)
                        yield emit("plan.updated", execution_plan.snapshot(paused=True))
                        yield emit("execution.phase", {"phase": "failed", "detail": stop_reason})
                        yield emit(
                            "message.completed",
                            {"message_id": response_id, "finish_reason": "failed"},
                        )
                        return
                    if report.status == "needs_input":
                        question = acceptance_question(report)
                        interrupt = await pause_for_user(
                            question,
                            "error" if report.review_error else "acceptance",
                            full_response,
                        )
                        yield emit("plan.updated", execution_plan.snapshot())
                        yield emit("execution.interrupted", interrupt)
                        yield emit(
                            "message.completed",
                            {"message_id": response_id, "finish_reason": "interrupt"},
                        )
                        return
                elif stop_reason:
                    interrupt = await pause_for_user(
                        UserQuestion(
                            question="任务尚未完成，要继续执行还是调整要求？",
                            reason=stop_reason,
                            options=["继续执行剩余步骤", "调整任务要求"],
                        ),
                        "error",
                        full_response,
                    )
                    yield emit("plan.updated", execution_plan.snapshot())
                    yield emit("execution.interrupted", interrupt)
                    yield emit(
                        "message.completed",
                        {"message_id": response_id, "finish_reason": "interrupt"},
                    )
                    return
            if last_plan_step is not None:
                yield emit(
                    "reasoning.step",
                    update_step(
                        last_plan_step["id"],
                        last_plan_step["title"],
                        last_plan_step["detail"],
                        "completed",
                        last_plan_step["kind"],
                    ),
                )
            document_content = full_response
            document_quality = None
            if "docx" in artifact_types:
                missing_sources = [
                    item for item in citations if item["url"] not in document_content
                ]
                if missing_sources:
                    document_content += "\n\n## 参考来源\n\n" + "\n".join(
                        f"- [{index}] [{item['title']}]({item['url']})"
                        for index, item in enumerate(citations, 1)
                    )
                async for progress in review_document(
                    provider=provider,
                    settings=settings,
                    prompt=task_content,
                    content=document_content,
                    sources=messages,
                ):
                    if await request.is_disconnected():
                        return
                    if progress["stage"] == "completed":
                        document_content = progress["content"]
                        document_quality = progress["report"]
                        yield emit("artifact.quality", document_quality)
                        detail = (
                            f"文档已完成 {document_quality['revisions']} 次修订；"
                            + {
                                "passed": "内容审阅通过。",
                                "warning": "内容仍有待核实或修改之处。",
                                "failed": "内容审阅未能完成，已保留完整草稿。",
                                "skipped": "本次未进行模型内容审阅。",
                            }[document_quality["model_review"]]
                        )
                        if document_quality["render"]["status"] == "passed":
                            detail += "已完成分页和文字边界检查。"
                        if document_quality["structural_issues"]:
                            detail += "；".join(document_quality["structural_issues"])
                        if document_quality["render"].get("issues"):
                            detail += "；".join(document_quality["render"]["issues"])
                        if document_quality.get("warnings"):
                            detail += "；".join(document_quality["warnings"])
                        if document_quality["render"].get("reason"):
                            detail += document_quality["render"]["reason"]
                        status = "completed"
                    else:
                        detail = progress["detail"]
                        status = "running"
                    yield emit(
                        "reasoning.step",
                        update_step(
                            "document-review",
                            "文档检查与修订",
                            detail,
                            status,
                            "tool",
                        ),
                    )
            token_usage = resolved_token_usage(
                messages, full_response, provider.token_usage, bigmodel.token_usage
            )
            generated_artifacts = await ArtifactService(session).create_requested(
                user_id=current_user.id,
                conversation_id=conversation_id,
                prompt=task_content,
                content=document_content,
            )
            if document_quality is not None:
                for artifact in generated_artifacts:
                    if artifact["artifact_type"] == "docx":
                        artifact["quality"] = document_quality
            if generated_artifacts:
                yield emit("artifacts", {"items": generated_artifacts})
            yield emit(
                "reasoning.step",
                update_step(
                    "answer-completed", "结果汇总", "已生成本次回答。", "completed", "answer"
                ),
            )
            await save_progress(
                full_response,
                {
                    "delivery_status": "final",
                    "citations": citations,
                    "reasoning_steps": reasoning_steps,
                    "generated_artifacts": generated_artifacts,
                    "token_usage": token_usage,
                },
            )
            if defer_delivery:
                yield emit(
                    "execution.phase",
                    {"phase": "delivering", "detail": "检查通过，正在展示最终方案。"},
                )
                for offset in range(0, len(full_response), 500):
                    if await request.is_disconnected():
                        return
                    yield emit("message.delta", {"text": full_response[offset : offset + 500]})
            if execution_plan is not None:
                yield emit("plan.updated", execution_plan.snapshot(paused=True))
            yield emit(
                "message.completed",
                {
                    "message_id": response_id,
                    "finish_reason": "stop",
                    "stop_reason": stop_reason or "completed",
                    "usage": token_usage,
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
            stop_reason = f"{exc.message}（{exc.code}）"
            if execution_plan is not None:
                execution_plan.explanation = f"本次执行中断：{stop_reason}"
            yield debug("error", error_diagnostic(exc))
            if full_response:
                messages.append({"role": "assistant", "content": full_response})
            error_question = (
                UserQuestion(
                    question="要接着补完剩余章节吗？",
                    reason="这份方案较长，还没有写完整，草稿已经保存。",
                    problems=["正文尚未输出完整，缺失章节需要从断点补完。"],
                    recommendation="建议从断点继续，不需要重写已完成部分。",
                    options=["继续补完方案（推荐）", "我来调整输出范围"],
                )
                if exc.code == "MODEL_OUTPUT_TRUNCATED"
                else UserQuestion(
                    question="执行发生中断，请选择继续重试，或输入补充说明。",
                    reason=stop_reason,
                    options=["从检查点继续重试", "补充说明后继续"],
                )
            )
            interrupt = await pause_for_user(
                error_question,
                "error",
                full_response,
            )
            yield emit("execution.interrupted", interrupt)
            if full_response:
                interrupted_note = (
                    "\n\n> 本次生成因模型连接波动提前结束，已保留已生成内容，可以继续提问。"
                )
                full_response = sanitize_assistant_content(full_response)
                if not defer_delivery:
                    full_response += interrupted_note
                    yield emit("message.delta", {"text": interrupted_note})
                interrupted_step = update_step(
                    "generation-interrupted",
                    "生成中断",
                    "方案尚未完整输出，已保存草稿和续写断点。"
                    if exc.code == "MODEL_OUTPUT_TRUNCATED"
                    else "模型连接中断，已保留本次已经生成的内容。",
                    "failed",
                    "answer",
                )
                yield emit("reasoning.step", interrupted_step)
                await save_progress(full_response, {"interrupted": True, "citations": citations})
                if execution_plan is not None:
                    yield emit("plan.updated", execution_plan.snapshot(paused=True))
                yield emit(
                    "message.completed",
                    {
                        "message_id": response_id,
                        "finish_reason": "error",
                        "interrupted": True,
                        "provider": "deepseek",
                        "model": settings.deepseek_model,
                    },
                )
                return
            if execution_plan is not None:
                await save_progress(metadata={"interrupted": True, "citations": citations})
                yield emit("plan.updated", execution_plan.snapshot(paused=True))
            yield emit(
                "error",
                {
                    **error_diagnostic(exc),
                    "trace_id": trace_id,
                    "retryable": exc.retryable,
                },
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
