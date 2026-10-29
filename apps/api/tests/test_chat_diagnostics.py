import asyncio
import json

import httpx
import pytest

from app.core.config import Settings
from app.core.diagnostics import error_diagnostic, safe_debug
from app.core.errors import AppError
from app.infrastructure.llm.deepseek import DeepSeekProvider
from app.tools.web_fetch import WebFetchHandler, WebFetchInput, WebFetchOutput


def test_diagnostics_redact_credentials_and_preserve_parameter_errors():
    payload = safe_debug(
        {
            "api_key": "hidden-key",
            "prompt_tokens": 120,
            "nested": {"authorization": "Bearer hidden-auth"},
            "arguments": '{"access_token":"hidden-token","url":"https://example.org"}',
            "body": "Bearer hidden-bearer https://example.org?api_key=hidden-query&limit=3",
            "reasoning_content": "private-reasoning",
        }
    )
    assert "hidden-" not in json.dumps(payload)
    assert "private-reasoning" not in json.dumps(payload)
    assert payload["prompt_tokens"] == 120
    assert "example.org" in payload["arguments"]


@pytest.mark.parametrize("raw", ["{bad-json", "[]", '{"queries":["https://example.org"]}'])
def test_bad_tool_parameters_are_visible_and_can_be_corrected(
    client, auth_headers, monkeypatch, raw
):
    calls = 0
    captured = []

    async def select(self, messages, tools, **kwargs):
        nonlocal calls
        captured.append(list(messages))
        calls += 1
        if calls > 2:
            return None, []
        call = {
            "id": f"fetch-{calls}",
            "type": "function",
            "function": {
                "name": "web__fetch",
                "arguments": raw if calls == 1 else '{"url":"https://example.org"}',
            },
        }
        return {"role": "assistant", "content": None, "tool_calls": [call]}, [call]

    async def narrative(self, messages, **kwargs):
        return {"understanding": "读取指定网页", "next_action": "核对参数后读取正文"}

    async def stream(self, messages):
        yield "已读取网页正文。"

    async def fetch(self, payload, context):
        return WebFetchOutput(
            url=str(payload.url),
            title="示例",
            content="实际返回的网页正文",
            source="example.org",
            truncated=False,
        )

    monkeypatch.setattr(Settings, "deepseek_enabled", property(lambda self: True))
    monkeypatch.setattr(Settings, "online_search_available", property(lambda self: True))
    monkeypatch.setattr(DeepSeekProvider, "select_tool_calls", select)
    monkeypatch.setattr(DeepSeekProvider, "complete_json", narrative)
    monkeypatch.setattr(DeepSeekProvider, "stream_chat", stream)
    monkeypatch.setattr(WebFetchHandler, "__call__", fetch)
    conversation = client.post("/api/v1/conversations", headers=auth_headers, json={}).json()
    response = client.post(
        f"/api/v1/conversations/{conversation['id']}/messages:stream",
        headers=auth_headers,
        json={"content": "读取指定页面并概括内容"},
    )
    events = []
    for block in response.text.strip().split("\n\n"):
        lines = block.splitlines()
        events.append((lines[0][7:], json.loads(lines[1][6:])))
    failure = next(data for event, data in events if event == "tool.failed")
    assert failure["code"] == "TOOL_VALIDATION_ERROR"
    assert failure["status"] == 422
    assert failure["tool_call_id"] == "fetch-1"
    assert failure["arguments"]
    assert failure["input_schema"]["required"] == ["url"]
    assert failure["details"]
    result = next(data for event, data in events if event == "tool.completed")
    assert result["result"]["content"] == "实际返回的网页正文"
    assert result["arguments"]["url"] == "https://example.org"
    assert result["elapsed_ms"] >= 0
    requests = [
        data for event, data in events if event == "agent.debug" and data["kind"] == "model.request"
    ]
    assert len(requests) == 4
    assert any(
        message["role"] == "tool" and "TOOL_VALIDATION_ERROR" in message["content"]
        for message in captured[1]
    )
    assert events[-1][0] == "message.completed"


@pytest.mark.parametrize("status", [403, 429])
def test_web_fetch_reports_upstream_status_and_body(monkeypatch, status):
    def handler(request):
        return httpx.Response(
            status, json={"error": "quota or permission denied", "api_key": "hidden-key"}
        )

    factory = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: factory(transport=httpx.MockTransport(handler), **kwargs),
    )
    with pytest.raises(AppError) as caught:
        asyncio.run(
            WebFetchHandler(Settings(_env_file=None, tavily_api_key="test"))(
                WebFetchInput(url="https://example.org"), None
            )
        )
    error = error_diagnostic(caught.value)
    assert error["details"][0]["provider_status"] == status
    assert "quota or permission denied" in error["details"][0]["body"]
    assert "hidden-key" not in json.dumps(error)
    assert error["retryable"] == (status == 429)


def test_web_fetch_empty_result_includes_upstream_failure_reason(monkeypatch):
    factory = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: factory(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "results": [],
                        "failed_results": [{"url": "https://example.org", "error": "Page blocked"}],
                    },
                )
            ),
            **kwargs,
        ),
    )
    with pytest.raises(AppError) as caught:
        asyncio.run(
            WebFetchHandler(Settings(_env_file=None, tavily_api_key="test"))(
                WebFetchInput(url="https://example.org"), None
            )
        )
    assert caught.value.code == "WEB_FETCH_EMPTY"
    assert caught.value.details[0]["failed_results"][0]["error"] == "Page blocked"
