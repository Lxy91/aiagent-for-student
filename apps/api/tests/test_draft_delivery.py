import asyncio
import json

import httpx
import pytest
from test_execution_checkpoints import configure_provider, events, tool_call

from app.core.config import Settings
from app.infrastructure.llm.deepseek import DeepSeekProvider
from app.modules.chat.drafts import stream_draft
from app.modules.chat.interrupts import present_question


def test_problem_summary_preserves_actual_missing_sections_for_old_checkpoint():
    issue = "正文在W1对账表的10/30处被截断，关键路径段落与状态快照均未出现，交付不完整。"
    result = present_question(
        {
            "kind": "acceptance",
            "question": "要继续自动调整吗？",
            "reason": "当前方案已保存。",
            "options": [],
        },
        [issue],
    )
    assert "关键路径" in result["problems"][0]
    assert "状态快照" in result["problems"][0]
    assert "断点" in result["question"]
    assert "继续补完" in result["options"][0]


def test_streaming_provider_accepts_usage_only_chunk_and_records_length(monkeypatch):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        chunks = [
            {"choices": [{"delta": {"content": "前半段"}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "length"}]},
            {
                "choices": [],
                "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
            },
        ]
        return httpx.Response(
            200,
            text="".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n",
        )

    factory = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: factory(transport=httpx.MockTransport(handler), **kwargs),
    )
    provider = DeepSeekProvider(Settings(_env_file=None, demo_mode=False, deepseek_api_key="test"))
    provider.chat_output_limit = 8000

    async def collect():
        return "".join(
            [chunk async for chunk in provider.stream_chat([{"role": "user", "content": "任务"}])]
        )

    assert asyncio.run(collect()) == "前半段"
    assert provider.last_finish_reason == "length"
    assert provider.token_usage["total_tokens"] == 18
    assert sent[0]["max_tokens"] == 8000


def test_long_draft_continues_at_breakpoint_without_restarting():
    class Provider:
        chat_output_limit = 8000
        last_finish_reason = None

        async def stream_chat(self, messages):
            assert messages[-2]["content"] == "正文前半段"
            assert "只从断点" in messages[-1]["content"]
            yield "正文后半段"
            self.last_finish_reason = "stop"

    async def collect():
        return [
            event
            async for event in stream_draft(
                Provider(),
                [
                    {"role": "system", "content": "执行任务"},
                    {"role": "user", "content": "写完整方案"},
                ],
                24000,
                plan={},
                original_request="写完整方案",
                citations=[],
                first_text="正文前半段",
                first_truncated=True,
            )
        ]

    data = asyncio.run(collect())
    assert (
        "".join(event["text"] for event in data if event["type"] == "delta")
        == "正文前半段正文后半段"
    )


@pytest.mark.parametrize("during_repair", [False, True])
def test_unchecked_draft_never_reaches_public_stream_and_resume_appends_missing_tail(
    client, auth_headers, monkeypatch, during_repair
):
    continued = False
    selections = []

    async def select(self, messages, tools, **kwargs):
        selections.append(messages)
        if not getattr(self, "planned", False):
            self.planned = True
            return tool_call(
                "execution__update_plan",
                {
                    "tasks": [
                        {
                            "id": "a",
                            "title": "完整交付",
                            "status": "completed",
                            "result": "已形成草稿",
                        }
                    ]
                },
                "plan",
            )
        self.last_selection_finish_reason = "stop" if during_repair else "length"
        return {"role": "assistant", "content": "长方案前半段"}, []

    def review(messages):
        if during_repair and not continued:
            return {"status": "failed", "issues": ["W1工时合计错误，需要修订。"]}
        return {"status": "passed", "issues": []}

    configure_provider(monkeypatch, select, review=review)

    async def stream(self, messages):
        if continued:
            yield "关键路径与状态快照已补完。"
            self.last_finish_reason = "stop"
        else:
            yield "未完的表格"
            self.last_finish_reason = "length"

    monkeypatch.setattr(DeepSeekProvider, "stream_chat", stream)
    conversation = client.post("/api/v1/conversations", headers=auth_headers, json={}).json()
    base = f"/api/v1/conversations/{conversation['id']}/messages"
    response = client.post(
        base + ":stream", headers=auth_headers, json={"content": "写完整方案", "use_plan": True}
    )
    data = events(response)
    assert not any(event in {"message.delta", "message.replaced"} for event, _ in data)
    question = next(item for event, item in data if event == "execution.interrupted")
    saved = client.get(base, headers=auth_headers).json()[-1]
    assert saved["delivery_status"] == "waiting_user"
    assert "长方案前半段" not in saved["content"]
    if during_repair:
        assert "长方案前半段" not in saved["draft_content"]
        assert "未完的表格" in saved["draft_content"]
    else:
        assert "长方案前半段" in saved["draft_content"]
    initial_draft = saved["draft_content"]
    before = len(selections)
    continued = True
    response = client.post(
        base + ":stream",
        headers=auth_headers,
        json={
            "content": "继续补完方案",
            "resume_checkpoint_id": question["id"],
            "resume_action": "continue",
        },
    )
    data = events(response)
    assert len(selections) == before  # No repeated tools or planning; resume the saved draft.
    delivered = "".join(item["text"] for event, item in data if event == "message.delta")
    assert delivered == initial_draft + "关键路径与状态快照已补完。"
    start = next(
        i
        for i, (event, item) in enumerate(data)
        if event == "execution.phase" and item["phase"] == "delivering"
    )
    assert all(i > start for i, (event, _) in enumerate(data) if event == "message.delta")
    assert client.get(base, headers=auth_headers).json()[-1]["delivery_status"] == "final"
