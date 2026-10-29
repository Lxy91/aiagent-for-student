import json

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import AppError
from app.infrastructure.llm.deepseek import DeepSeekProvider
from app.modules.chat.execution_plan import ExecutionPlan


def plan_payload(status="running", result=""):
    return {
        "tasks": [
            {"id": "research", "title": "分析现有材料", "status": status, "result": result},
            {"id": "report", "title": "汇总建议", "status": "pending", "result": ""},
        ],
        "explanation": "按步骤完成任务",
    }


@pytest.mark.parametrize(
    "invalid",
    [
        {"tasks": []},
        {"tasks": [{"id": "a", "title": "步骤", "status": "completed"}]},
        {"tasks": [{"id": "a", "title": "步骤", "status": "blocked"}]},
        {"tasks": [{"id": "a", "title": "步骤"}, {"id": "a", "title": "重复"}]},
        {
            "tasks": [
                {"id": "a", "title": "步骤", "status": "running"},
                {"id": "b", "title": "步骤", "status": "running"},
            ]
        },
    ],
)
def test_plan_rejects_invalid_progress(invalid):
    with pytest.raises(ValidationError):
        ExecutionPlan.model_validate(invalid)


@pytest.mark.parametrize("interrupt", [False, True])
def test_plan_stream_checkpoints_and_resume(client, auth_headers, monkeypatch, interrupt):
    calls = 0
    captured = []

    async def select(self, messages, tools, *, force_tool_name=None, **kwargs):
        nonlocal calls
        captured.append(list(messages))
        assert any(tool["function"]["name"] == "execution__update_plan" for tool in tools)
        if calls == 0:
            assert force_tool_name == "execution__update_plan"
        calls += 1
        if calls in {1, 2}:
            payload = (
                plan_payload()
                if calls == 1
                else plan_payload("completed", "材料显示应先准备作品集")
            )
            call = {
                "id": f"plan-{calls}",
                "type": "function",
                "function": {
                    "name": "execution__update_plan",
                    "arguments": json.dumps(payload),
                },
            }
            return {"role": "assistant", "content": None, "tool_calls": [call]}, [call]
        if interrupt:
            raise AppError("MODEL_PROVIDER_ERROR", "模拟规划中断", status_code=502)
        return None, []

    async def narrative(self, messages, **kwargs):
        return {"understanding": "整理材料", "next_action": "汇总已完成内容"}

    async def stream(self, messages):
        yield "已完成材料分析，建议汇总仍待继续。"

    monkeypatch.setattr(Settings, "deepseek_enabled", property(lambda self: True))
    monkeypatch.setattr(DeepSeekProvider, "select_tool_calls", select)
    monkeypatch.setattr(DeepSeekProvider, "complete_json", narrative)
    monkeypatch.setattr(DeepSeekProvider, "stream_chat", stream)
    conversation = client.post("/api/v1/conversations", headers=auth_headers, json={}).json()
    base = f"/api/v1/conversations/{conversation['id']}/messages"
    response = client.post(
        base + ":stream",
        headers=auth_headers,
        json={"content": "分析材料并汇总建议", "use_plan": True},
    )
    assert "event: plan.updated" in response.text
    assert ("event: error" in response.text) == interrupt
    messages = client.get(base, headers=auth_headers).json()
    assert len(messages) == 2  # Each progress update replaces the same checkpoint.
    saved = messages[-1]["execution_plan"]
    assert saved["status"] == "waiting_user"
    assert saved["tasks"][0]["status"] == "completed"
    assert saved["tasks"][1]["status"] == "pending"
    assert "作品集" in saved["tasks"][0]["result"]
    assert any(message.get("role") == "tool" for message in captured[-1])

    monkeypatch.setattr(DeepSeekProvider, "select_tool_calls", select)
    client.post(base + ":stream", headers=auth_headers, json={"content": "继续剩余步骤"})
    assert any("作品集" in str(message.get("content")) for message in captured[-1])
