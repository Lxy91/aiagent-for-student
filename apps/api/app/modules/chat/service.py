from __future__ import annotations

import base64
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.infrastructure.db.models import ConversationModel, MessageModel, WorkMaterialModel
from app.infrastructure.llm.deepseek import DeepSeekProvider
from app.modules.chat.context import (
    normalize_role,
    sanitize_assistant_protocol,
    sanitize_message_content,
    wrap_untrusted_content,
)
from app.modules.chat.schemas import (
    ConversationResponse,
    CreateConversationRequest,
    MessageResponse,
    UpdateConversationRequest,
)

_CJK_CHARACTER_PATTERN = re.compile(
    "[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]"
)


def estimate_text_tokens(content: str) -> int:
    """Conservatively estimate tokens without coupling to one provider tokenizer."""
    if not content:
        return 0
    cjk_count = len(_CJK_CHARACTER_PATTERN.findall(content))
    non_cjk_count = len(content) - cjk_count
    return cjk_count + math.ceil(non_cjk_count / 4)


def estimate_message_tokens(message: dict[str, str]) -> int:
    """Include a small allowance for role and message framing tokens."""
    return 4 + estimate_text_tokens(message.get("role", "")) + estimate_text_tokens(
        message.get("content", "")
    )


def truncate_text_to_token_budget(content: str, token_budget: int) -> tuple[str, bool]:
    """Keep representative head/tail text while bounding attachment prompt size."""
    if estimate_text_tokens(content) <= token_budget:
        return content, False
    marker = "\n\n[附件内容过长，已按上下文预算截取；中间部分未发送给模型]\n\n"
    low, high = 0, len(content)
    best = marker.strip()
    while low <= high:
        length = (low + high) // 2
        head_length = math.ceil(length * 0.7)
        tail_length = length - head_length
        tail = content[-tail_length:] if tail_length else ""
        candidate = f"{content[:head_length]}{marker}{tail}"
        if estimate_text_tokens(candidate) <= token_budget:
            best = candidate
            low = length + 1
        else:
            high = length - 1
    return best, True


def sanitize_assistant_content(content: str) -> str:
    """Remove leaked provider tool-protocol markup from displayable assistant text."""
    return sanitize_assistant_protocol(content)


def summarize_conversation_title(content: str, max_length: int = 24) -> str:
    """Build a stable sidebar title from the first user question."""
    normalized = " ".join(content.split()).strip()
    for prefix in ("请问", "请帮我", "帮我", "我想问一下", "我想问"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :].lstrip("，,:： ")
            break
    normalized = normalized.strip("#*` ")
    normalized = normalized.rstrip("。！？!?~ ")
    if not normalized:
        return "新对话"
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[:max_length].rstrip()}…"


class ExecutionNarrative(BaseModel):
    understanding: str = Field(min_length=1, max_length=240)
    next_action: str = Field(min_length=1, max_length=240)


@dataclass
class ContextWindow:
    messages: list[dict[str, str]]
    estimated_tokens: int
    message_count: int
    trimmed_count: int
    oldest_included_at: datetime | None
    database_history_tokens: int
    current_input_tokens: int
    summary_tokens: int


async def build_execution_narrative(
    provider: DeepSeekProvider,
    *,
    user_request: str,
    selected_tools: list[str],
    observations: list[str],
    iteration: int,
) -> ExecutionNarrative:
    """Generate a safe, user-facing summary of the observable execution plan."""
    tool_text = "、".join(selected_tools) if selected_tools else "不调用工具，直接回答"
    observation_text = "；".join(observations[-3:]) if observations else "暂无工具观察结果"
    prompt = (
        f"用户请求：{user_request[:2000]}\n"
        f"当前是第 {iteration + 1} 轮规划。\n"
        f"已经确定的下一动作：{tool_text}\n"
        f"已获得的观察结果：{observation_text}"
    )
    try:
        raw = await provider.complete_json(
            [
                {
                    "role": "system",
                    "content": (
                        "你负责生成可展示给用户的执行摘要，不回答用户问题，也不输出隐藏思维链。"
                        '只输出 JSON：{"understanding":"...","next_action":"..."}。'
                        "understanding 用一句自然中文具体概括当前问题重点；next_action 用第一人称"
                        "具体说明已经决定的下一步。两项都不超过 80 个汉字。只有已确定动作包含"
                        " web.search 时，才能提到联网、最新、时效性或来源核对；没有选择工具时，"
                        "不要解释为什么不使用工具。结合已获得的观察结果描述后续动作，不得虚构"
                        "未执行的操作，避免使用‘目标、时效性要求和可用工具’等通用模板。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=500,
        )
        narrative = ExecutionNarrative.model_validate(raw)
        forbidden_web_markers = (
            "联网",
            "web.search",
            "检索网页",
            "搜索网络",
            "时效性",
            "最新信息",
            "核对来源",
        )
        if "web.search" not in selected_tools and any(
            marker in narrative.next_action for marker in forbidden_web_markers
        ):
            raise ValueError("Narrative mentions web work that was not selected")
        stale_planning_markers = (
            "询问用户",
            "请用户",
            "明确范围",
            "明确主题",
            "具体范围",
            "具体主题",
            "决定是否",
            "进一步搜索",
        )
        if (
            observations
            and not selected_tools
            and any(marker in narrative.next_action for marker in stale_planning_markers)
        ):
            raise ValueError("Narrative ignores completed tool observations")
        return narrative
    except (AppError, ValidationError, ValueError):
        topic = " ".join(user_request.split())[:80]
        if selected_tools:
            next_action = f"我准备运行 {'、'.join(selected_tools)}，获取回答所需的信息。"
        elif observations:
            next_action = f"我会结合已经取得的结果（{observations[-1]}）整理回答。"
        else:
            next_action = "我会基于当前对话直接回答这个问题。"
        return ExecutionNarrative(
            understanding=f"当前需要处理的是“{topic}”。",
            next_action=next_action,
        )


class ConversationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self, user_id: UUID, payload: CreateConversationRequest
    ) -> ConversationResponse:
        item = ConversationModel(
            id=str(uuid4()),
            user_id=str(user_id),
            title=payload.title,
            mode=payload.mode,
            created_at=datetime.now(UTC),
        )
        self.session.add(item)
        await self.session.commit()
        return self._conversation_response(item)

    async def list(self, user_id: UUID) -> list[ConversationResponse]:
        result = await self.session.scalars(
            select(ConversationModel)
            .where(
                ConversationModel.user_id == str(user_id),
                ConversationModel.is_archived.is_(False),
            )
            .order_by(ConversationModel.is_pinned.desc(), ConversationModel.created_at.desc())
        )
        return [self._conversation_response(item) for item in result]

    async def update(
        self,
        user_id: UUID,
        conversation_id: UUID,
        payload: UpdateConversationRequest,
    ) -> ConversationResponse:
        item = await self.get_owned(user_id, conversation_id)
        changes = payload.model_dump(exclude_unset=True)
        if "title" in changes:
            title = (changes["title"] or "").strip()
            if not title:
                raise AppError("INVALID_CONVERSATION_TITLE", "会话名称不能为空", status_code=422)
            changes["title"] = title
        for field, value in changes.items():
            setattr(item, field, value)
        await self.session.commit()
        await self.session.refresh(item)
        return self._conversation_response(item)

    async def apply_first_message_title(
        self, user_id: UUID, conversation_id: UUID, content: str
    ) -> ConversationResponse:
        """Replace the placeholder title once, without overwriting a manual rename."""
        item = await self.get_owned(user_id, conversation_id)
        first_message_id = await self.session.scalar(
            select(MessageModel.id)
            .where(MessageModel.conversation_id == str(conversation_id))
            .limit(1)
        )
        if item.title == "新对话" and first_message_id is None:
            item.title = summarize_conversation_title(content)
            await self.session.commit()
            await self.session.refresh(item)
        return self._conversation_response(item)

    async def get_owned(self, user_id: UUID, conversation_id: UUID) -> ConversationModel:
        item = await self.session.scalar(
            select(ConversationModel).where(
                ConversationModel.id == str(conversation_id),
                ConversationModel.user_id == str(user_id),
            )
        )
        if item is None:
            raise AppError("CONVERSATION_NOT_FOUND", "会话不存在", status_code=404)
        return item

    async def get_writable(self, user_id: UUID, conversation_id: UUID) -> ConversationModel:
        item = await self.get_owned(user_id, conversation_id)
        if item.is_archived:
            raise AppError(
                "CONVERSATION_ARCHIVED",
                "已归档会话不能继续发送消息,请先取消归档",
                status_code=409,
            )
        return item

    async def add_message(
        self,
        conversation_id: UUID,
        role: str,
        content: str,
        *,
        metadata: dict | None = None,
    ) -> MessageModel:
        normalized_role = normalize_role(role, persisted=True)
        item = MessageModel(
            id=str(uuid4()),
            conversation_id=str(conversation_id),
            role=normalized_role,
            content=content,
            sanitized_content=sanitize_message_content(content, normalized_role),
            metadata_json=metadata or {},
            created_at=datetime.now(UTC),
        )
        self.session.add(item)
        await self.session.commit()
        return item

    async def resolve_attachments(
        self,
        user_id: UUID,
        attachment_ids: list[UUID],
        *,
        token_budget: int = 6_000,
    ) -> tuple[list[dict[str, str]], str, list[dict[str, str]]]:
        if not attachment_ids:
            return [], "", []
        requested = [str(item) for item in attachment_ids]
        result = await self.session.scalars(
            select(WorkMaterialModel).where(
                WorkMaterialModel.user_id == str(user_id),
                WorkMaterialModel.id.in_(requested),
            )
        )
        by_id = {item.id: item for item in result}
        if len(by_id) != len(requested):
            raise AppError("ATTACHMENT_NOT_FOUND", "部分附件不存在或无权访问", status_code=404)

        attachments: list[dict[str, str]] = []
        context_sections: list[str] = []
        vision_images: list[dict[str, str]] = []
        remaining_tokens = token_budget
        for material_id in requested:
            item = by_id[material_id]
            if item.status == "blocked":
                raise AppError(
                    "ATTACHMENT_REVIEW_REQUIRED",
                    f"附件“{item.title}”包含高风险隐私信息，请先处理后再发送",
                    status_code=422,
                )
            attachments.append(
                {
                    "id": item.id,
                    "title": item.title,
                    "material_type": item.material_type,
                    "mime_type": item.mime_type,
                    "status": item.status,
                }
            )
            if item.material_type == "image" and item.binary_content:
                vision_images.append(
                    {
                        "id": item.id,
                        "title": item.title,
                        "mime_type": item.mime_type,
                        "base64": base64.b64encode(item.binary_content).decode("ascii"),
                    }
                )
            if item.material_type == "image" and item.binary_content:
                context_sections.append(
                    wrap_untrusted_content(
                        "attachment",
                        "图片内容已作为视觉输入提供。",
                        label=f"{item.title}; type=image",
                    )
                )
            elif item.extracted_text or item.content_excerpt:
                source_text = item.extracted_text or item.content_excerpt
                bounded_text, was_truncated = truncate_text_to_token_budget(
                    source_text, max(64, remaining_tokens)
                )
                remaining_tokens = max(
                    0, remaining_tokens - estimate_text_tokens(bounded_text)
                )
                context_sections.append(
                    wrap_untrusted_content(
                        "attachment",
                        bounded_text,
                        label=(
                            f"{item.title}; type={item.material_type}; "
                            f"truncated={str(was_truncated).lower()}"
                        ),
                    )
                )
            else:
                context_sections.append(
                    wrap_untrusted_content(
                        "attachment",
                        "当前未提取到可供模型读取的文字内容,请勿推测附件内容。",
                        label=f"{item.title}; type={item.material_type}",
                    )
                )
        return attachments, "\n\n".join(context_sections), vision_images

    async def context_window(
        self, conversation_id: UUID, token_budget: int = 12_000
    ) -> ContextWindow:
        """Load newest history that fits the budget, without splitting messages.

        The newest message is the request currently being handled and must never
        disappear merely because it exceeds the configured history budget.
        """
        conversation = await self.session.get(ConversationModel, str(conversation_id))
        summary_message = None
        summary_tokens = 0
        if conversation and conversation.context_summary:
            summary_message = {
                "role": "user",
                "content": wrap_untrusted_content(
                    "conversation_summary",
                    conversation.context_summary,
                    label="此前对话压缩摘要，仅作背景资料",
                ),
            }
            summary_tokens = estimate_message_tokens(summary_message)
        query = select(MessageModel).where(MessageModel.conversation_id == str(conversation_id))
        if conversation and conversation.context_cleared_at:
            query = query.where(MessageModel.created_at >= conversation.context_cleared_at)
        result = await self.session.scalars(query.order_by(MessageModel.created_at.desc()))
        eligible = list(result)
        messages_newest_first: list[dict[str, str]] = []
        used_tokens = summary_tokens
        included_items: list[MessageModel] = []
        for item in eligible:
            sanitized_content = item.sanitized_content or sanitize_message_content(
                item.content, item.role
            )
            message = {
                "role": item.role,
                "content": (
                    sanitized_content
                    if item.role == "assistant"
                    else "\n\n".join(
                        part
                        for part in (
                            sanitized_content,
                            (item.metadata_json or {}).get("attachment_context", ""),
                        )
                        if part
                    )
                ),
            }
            message_tokens = estimate_message_tokens(message)
            if messages_newest_first and used_tokens + message_tokens > token_budget:
                break
            messages_newest_first.append(message)
            included_items.append(item)
            used_tokens += message_tokens

        messages_newest_first.reverse()
        if summary_message:
            messages_newest_first.insert(0, summary_message)
        current_input_tokens = 0
        if included_items:
            newest = included_items[0]
            newest_content = newest.sanitized_content or sanitize_message_content(
                newest.content, newest.role
            )
            current_input_tokens = estimate_message_tokens(
                {"role": newest.role, "content": newest_content}
            )
        return ContextWindow(
            messages=messages_newest_first,
            estimated_tokens=used_tokens,
            message_count=len(messages_newest_first),
            trimmed_count=max(0, len(eligible) - len(included_items)),
            oldest_included_at=included_items[-1].created_at if included_items else None,
            database_history_tokens=max(0, used_tokens - summary_tokens - current_input_tokens),
            current_input_tokens=current_input_tokens,
            summary_tokens=summary_tokens,
        )

    async def recent_messages(
        self, conversation_id: UUID, token_budget: int = 12_000
    ) -> list[dict[str, str]]:
        return (await self.context_window(conversation_id, token_budget)).messages

    async def compress_context(self, user_id: UUID, conversation_id: UUID) -> ConversationModel:
        item = await self.get_writable(user_id, conversation_id)
        result = await self.session.scalars(
            select(MessageModel)
            .where(
                MessageModel.conversation_id == str(conversation_id),
                *(
                    [MessageModel.created_at >= item.context_cleared_at]
                    if item.context_cleared_at
                    else []
                ),
            )
            .order_by(MessageModel.created_at.asc())
        )
        item.context_summary = self._compressed_summary(item.context_summary, list(result))
        item.context_cleared_at = datetime.now(UTC).replace(tzinfo=None)
        item.context_clear_notice_pending = True
        await self.session.commit()
        return item

    async def persist_context_compression(
        self, conversation_id: UUID, *, oldest_included_at: datetime | None
    ) -> None:
        item = await self.session.get(ConversationModel, str(conversation_id))
        if item is None or oldest_included_at is None:
            return
        if item.context_cleared_at is None or oldest_included_at > item.context_cleared_at:
            result = await self.session.scalars(
                select(MessageModel)
                .where(
                    MessageModel.conversation_id == str(conversation_id),
                    MessageModel.created_at < oldest_included_at,
                    *(
                        [MessageModel.created_at >= item.context_cleared_at]
                        if item.context_cleared_at
                        else []
                    ),
                )
                .order_by(MessageModel.created_at.asc())
            )
            item.context_summary = self._compressed_summary(item.context_summary, list(result))
            item.context_cleared_at = oldest_included_at
        await self.session.commit()

    @staticmethod
    def _compressed_summary(existing: str, messages: list[MessageModel]) -> str:
        lines = [existing.strip()] if existing.strip() else []
        for message in messages:
            content = message.sanitized_content or sanitize_message_content(
                message.content, message.role
            )
            compact = " ".join(content.split())
            if compact:
                label = "用户" if message.role == "user" else "助手"
                lines.append(f"{label}：{compact[:500]}")
        summary = "\n".join(lines)
        return summary[-4000:]

    async def consume_context_clear_notice(self, conversation_id: UUID) -> bool:
        item = await self.session.get(ConversationModel, str(conversation_id))
        if item is None or not item.context_clear_notice_pending:
            return False
        item.context_clear_notice_pending = False
        await self.session.commit()
        return True

    async def pending_attachment_edit(self, conversation_id: UUID) -> dict[str, str] | None:
        result = await self.session.scalars(
            select(MessageModel)
            .where(MessageModel.conversation_id == str(conversation_id))
            .order_by(MessageModel.created_at.desc())
            .limit(12)
        )
        recent = list(result)
        latest = recent[0] if recent else None
        if latest is None or latest.role != "assistant":
            return None
        pending = (latest.metadata_json or {}).get("pending_attachment_edit")
        if isinstance(pending, dict) and pending.get("attachment_id"):
            return {
                "attachment_id": str(pending["attachment_id"]),
                "filename": str(pending.get("filename") or "附件"),
                "original_request": str(pending.get("original_request") or "补全附件"),
            }

        legacy_resume_markers = (
            "请补充",
            "暂无法填写",
            "已保持空白",
            "无法直接修改并返回",
            "无法直接生成",
            "复制并粘贴",
        )
        latest_content = latest.sanitized_content or sanitize_message_content(
            latest.content, latest.role
        )
        if not any(marker in latest_content for marker in legacy_resume_markers):
            return None
        for item in recent:
            metadata = item.metadata_json or {}
            if metadata.get("generated_artifacts"):
                return None
            if item.role != "user":
                continue
            editable = [
                attachment
                for attachment in metadata.get("attachments", [])
                if str(attachment.get("title") or "").lower().endswith((".docx", ".xlsx"))
            ]
            if len(editable) == 1:
                attachment = editable[0]
                return {
                    "attachment_id": str(attachment["id"]),
                    "filename": str(attachment.get("title") or "附件"),
                    "original_request": item.content or "补全附件",
                }
        return None

    async def latest_generated_artifact(self, conversation_id: UUID) -> dict[str, str] | None:
        result = await self.session.scalars(
            select(MessageModel)
            .where(MessageModel.conversation_id == str(conversation_id))
            .order_by(MessageModel.created_at.desc())
            .limit(20)
        )
        for item in result:
            artifacts = (item.metadata_json or {}).get("generated_artifacts", [])
            for artifact in reversed(artifacts):
                filename = str(artifact.get("filename") or "")
                if filename.lower().endswith((".docx", ".xlsx")) and artifact.get("id"):
                    return {
                        "id": str(artifact["id"]),
                        "title": filename,
                        "material_type": "document",
                        "mime_type": str(artifact.get("mime_type") or ""),
                        "status": "ready",
                    }
        return None

    async def list_messages(self, user_id: UUID, conversation_id: UUID) -> list[MessageResponse]:
        await self.get_owned(user_id, conversation_id)
        result = await self.session.scalars(
            select(MessageModel)
            .where(MessageModel.conversation_id == str(conversation_id))
            .order_by(MessageModel.created_at.asc())
        )
        return [
            MessageResponse(
                id=item.id,
                conversation_id=item.conversation_id,
                role=item.role,
                content=(
                    item.sanitized_content if item.role == "assistant" else item.content
                ),
                created_at=item.created_at,
                citations=(item.metadata_json or {}).get("citations", []),
                reasoning_steps=(item.metadata_json or {}).get("reasoning_steps", []),
                attachments=(item.metadata_json or {}).get("attachments", []),
                generated_images=(item.metadata_json or {}).get("generated_images", []),
                generated_artifacts=(item.metadata_json or {}).get("generated_artifacts", []),
                token_usage=(item.metadata_json or {}).get("token_usage"),
            )
            for item in result
        ]

    @staticmethod
    def _conversation_response(item: ConversationModel) -> ConversationResponse:
        return ConversationResponse(
            id=item.id,
            title=item.title,
            mode=item.mode,
            is_pinned=item.is_pinned,
            is_archived=item.is_archived,
            created_at=item.created_at,
        )
