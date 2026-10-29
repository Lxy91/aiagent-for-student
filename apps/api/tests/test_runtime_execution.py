import json

import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.infrastructure.llm.deepseek import DeepSeekProvider
from app.modules.chat.runtime_context import compact_runtime_context, runtime_tokens


def test_runtime_compaction_retains_request_plan_sources_and_complete_tool_pairs():
    request = {"role": "user", "content": "必须比较三个城市，并保留全部用户约束。"}
    messages = [{"role": "system", "content": "执行任务"}, request]
    for index in range(8):
        calls = [
            {"id": f"call-{index}-{j}", "function": {"name": "web__fetch", "arguments": "{}"}}
            for j in range(2)
        ]
        messages.append({"role": "assistant", "content": None, "tool_calls": calls})
        messages.extend(
            {"role": "tool", "tool_call_id": call["id"], "content": "网页正文" * 3000}
            for call in calls
        )
    plan = {"tasks": [{"id": "a", "status": "completed", "result": "已核验来源，不要重复"}]}
    context = compact_runtime_context(
        messages, [], 6000, plan=plan, citations=[{"url": "https://example.org/evidence"}]
    )
    assert context.compacted
    assert context.estimated_tokens <= 6000
    assert context.estimated_tokens < context.before_tokens
    assert request in context.messages
    serialized = json.dumps(context.messages, ensure_ascii=False)
    assert "已核验来源" in serialized
    assert "https://example.org/evidence" in serialized
    expected = {call["id"] for item in context.messages for call in item.get("tool_calls", [])}
    actual = {item["tool_call_id"] for item in context.messages if item["role"] == "tool"}
    assert expected == actual


def test_runtime_compaction_counts_tool_arguments_and_rejects_oversized_required_input():
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "请求" * 5000}]
    assert runtime_tokens(messages, [{"parameters": "工具描述" * 200}]) > runtime_tokens(
        messages, []
    )
    with pytest.raises(AppError, match="原始任务"):
        compact_runtime_context(messages, [], 4096)


@pytest.mark.parametrize("stalled", [False, True])
def test_pending_plan_automatically_continues_and_stalls_have_reason(
    client, auth_headers, monkeypatch, stalled
):
    selections = 0
    completed = False
    captured = []

    async def select(self, messages, tools, *, force_tool_name=None, **kwargs):
        nonlocal selections, completed
        selections += 1
        captured.append(list(messages))
        if selections == 1 or force_tool_name == "execution__update_plan":
            completed = selections > 1 and not stalled
            call = {
                "id": f"plan-{selections}",
                "type": "function",
                "function": {
                    "name": "execution__update_plan",
                    "arguments": json.dumps(
                        {
                            "tasks": [
                                {
                                    "id": "analysis",
                                    "title": "分析并给出方案",
                                    "status": "completed" if completed else "running",
                                    "result": "先完成作品集，再安排面试练习" if completed else "",
                                }
                            ]
                        }
                    ),
                },
            }
            return {"role": "assistant", "content": None, "tool_calls": [call]}, [call]
        return {"role": "assistant", "content": "分析结果：先完成作品集，再安排面试练习。"}, []

    async def narrative(self, messages, **kwargs):
        if "[TASK_ACCEPTANCE]" in messages[0]["content"]:
            return {"status": "passed", "issues": []}
        return {"understanding": "逐步完成任务", "next_action": "继续当前分析"}

    async def stream(self, messages):
        yield "已汇总本次执行结果。"

    monkeypatch.setattr(Settings, "deepseek_enabled", property(lambda self: True))
    monkeypatch.setattr(DeepSeekProvider, "select_tool_calls", select)
    monkeypatch.setattr(DeepSeekProvider, "complete_json", narrative)
    monkeypatch.setattr(DeepSeekProvider, "stream_chat", stream)
    conversation = client.post("/api/v1/conversations", headers=auth_headers, json={}).json()
    base = f"/api/v1/conversations/{conversation['id']}/messages"
    response = client.post(
        base + ":stream", headers=auth_headers, json={"content": "分析并给出方案", "use_plan": True}
    )
    assert "auto-continue" in response.text
    messages = client.get(base, headers=auth_headers).json()
    assert len(messages) == 2
    saved = messages[-1]
    assert saved["execution_plan"]["status"] == ("waiting_user" if stalled else "completed")
    assert (
        "任务计划：" not in saved["content"]
    )  # Internal checkpoints stay out of the visible answer.
    assert any("先完成作品集" in str(item) for turn in captured[2:] for item in turn)
    if stalled:
        assert "连续多轮未更新" in saved["execution_plan"]["explanation"]
        assert selections <= 8
    else:
        assert saved["execution_plan"]["tasks"][0]["result"]


def test_transient_model_selection_error_is_retried(client, auth_headers, monkeypatch):
    calls = 0

    async def select(self, messages, tools, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise AppError("MODEL_PROVIDER_ERROR", "连接暂时失败", status_code=502, retryable=True)
        return None, []

    async def narrative(self, messages, **kwargs):
        return {"understanding": "回答问题", "next_action": "汇总答案"}

    async def stream(self, messages):
        yield "恢复后完成回答。"

    monkeypatch.setattr(Settings, "deepseek_enabled", property(lambda self: True))
    monkeypatch.setattr(DeepSeekProvider, "select_tool_calls", select)
    monkeypatch.setattr(DeepSeekProvider, "complete_json", narrative)
    monkeypatch.setattr(DeepSeekProvider, "stream_chat", stream)
    conversation = client.post("/api/v1/conversations", headers=auth_headers, json={}).json()
    response = client.post(
        f"/api/v1/conversations/{conversation['id']}/messages:stream",
        headers=auth_headers,
        json={"content": "你好"},
    )
    assert calls == 2
    assert "自动重试" in response.text
    assert "连接恢复" in response.text
    assert "event: message.completed" in response.text
    assert "event: error" not in response.text
