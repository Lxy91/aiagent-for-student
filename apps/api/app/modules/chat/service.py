from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.infrastructure.db.models import ConversationModel, MessageModel
from app.infrastructure.llm.deepseek import DeepSeekProvider
from app.modules.chat.schemas import (
    ConversationResponse,
    CreateConversationRequest,
    MessageResponse,
    UpdateConversationRequest,
)


def sanitize_assistant_content(content: str) -> str:
    """Remove leaked provider tool-protocol markup from displayable assistant text."""
    lines = [
        line
        for line in content.splitlines()
        if not any(
            marker in line.lower()
            for marker in ("dsml", "<tool_calls", "<invoke name=", "<parameter name=")
        )
    ]
    return "\n".join(lines).strip()


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

    async def add_message(
        self,
        conversation_id: UUID,
        role: str,
        content: str,
        *,
        metadata: dict | None = None,
    ) -> MessageModel:
        item = MessageModel(
            id=str(uuid4()),
            conversation_id=str(conversation_id),
            role=role,
            content=sanitize_assistant_content(content) if role == "assistant" else content,
            metadata_json=metadata or {},
            created_at=datetime.now(UTC),
        )
        self.session.add(item)
        await self.session.commit()
        return item

    async def recent_messages(self, conversation_id: UUID, limit: int = 12) -> list[dict[str, str]]:
        result = await self.session.scalars(
            select(MessageModel)
            .where(MessageModel.conversation_id == str(conversation_id))
            .order_by(MessageModel.created_at.desc())
            .limit(limit)
        )
        items = list(result)
        items.reverse()
        return [
            {
                "role": item.role,
                "content": (
                    sanitize_assistant_content(item.content)
                    if item.role == "assistant"
                    else item.content
                ),
            }
            for item in items
        ]

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
                    sanitize_assistant_content(item.content)
                    if item.role == "assistant"
                    else item.content
                ),
                created_at=item.created_at,
                citations=(item.metadata_json or {}).get("citations", []),
                reasoning_steps=(item.metadata_json or {}).get("reasoning_steps", []),
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
