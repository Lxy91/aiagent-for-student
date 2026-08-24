from fastapi.testclient import TestClient

from app.infrastructure.search.tavily import TavilyWebSearchProvider
from app.modules.chat.api import requires_web_search
from app.ports.web_search import SearchResult, WebSearchResponse


def test_health_and_ready(client: TestClient) -> None:
    assert client.get("/api/v1/health").json()["status"] == "ok"
    ready = client.get("/api/v1/ready")
    assert ready.status_code == 200
    assert ready.json()["dependencies"]["deepseek"] == "demo-mode"


def test_web_search_routing_covers_current_information_without_overmatching() -> None:
    assert requires_web_search("总结一下今日新闻")
    assert requires_web_search("最近有哪些校招政策变化？")
    assert requires_web_search("帮我查一下这家公司")
    assert not requires_web_search("我当前很焦虑，该怎么和领导沟通？")
    assert not requires_web_search("帮我准备第一次周会")


def test_auth_rejects_duplicate_email(client: TestClient, auth_headers: dict[str, str]) -> None:
    del auth_headers
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "student@example.com",
            "password": "another-password",
            "display_name": "另一位同学",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_ALREADY_EXISTS"
    assert response.json()["error"]["trace_id"]


def test_conversation_stream(client: TestClient, auth_headers: dict[str, str]) -> None:
    created = client.post(
        "/api/v1/conversations",
        headers=auth_headers,
        json={"title": "任务澄清", "mode": "standard"},
    )
    assert created.status_code == 201
    conversation_id = created.json()["id"]

    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages:stream",
        headers=auth_headers,
        json={"content": "如何向领导澄清需求？"},
    )
    assert response.status_code == 200
    assert "event: message.started" in response.text
    assert "event: message.delta" in response.text
    assert "event: message.completed" in response.text
    assert '"demo_mode": true' in response.text

    messages = client.get(
        f"/api/v1/conversations/{conversation_id}/messages", headers=auth_headers
    )
    assert messages.status_code == 200
    assert [item["role"] for item in messages.json()] == ["user", "assistant"]


def test_memory_confirmation_and_delete(client: TestClient, auth_headers: dict[str, str]) -> None:
    candidate = client.post(
        "/api/v1/memory-candidates",
        headers=auth_headers,
        json={"type": "goal", "content": "三个月内独立完成需求评审"},
    )
    assert candidate.status_code == 201
    memory = client.post(
        f"/api/v1/memory-candidates/{candidate.json()['id']}:confirm",
        headers=auth_headers,
        json={},
    )
    assert memory.status_code == 201
    memory_id = memory.json()["id"]
    assert len(client.get("/api/v1/memories", headers=auth_headers).json()) == 1
    assert client.delete(f"/api/v1/memories/{memory_id}", headers=auth_headers).status_code == 204


def test_knowledge_upload(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/knowledge/documents",
        headers=auth_headers,
        files={"file": ("guide.md", b"# Workplace guide\nAsk clear questions.", "text/markdown")},
        data={"source": "测试资料"},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "ready"
    assert response.json()["source"] == "测试资料"


def test_plan_confirmation_is_idempotent(client: TestClient, auth_headers: dict[str, str]) -> None:
    draft = client.post(
        "/api/v1/plans:draft",
        headers=auth_headers,
        json={"goal": "三天看懂 React 项目并完成汇报", "deadline": "2026-08-23"},
    )
    assert draft.status_code == 201
    body = draft.json()
    confirmation = {"confirmation_token": body["confirmation_token"]}
    first = client.post(
        f"/api/v1/plan-drafts/{body['id']}:confirm", headers=auth_headers, json=confirmation
    )
    second = client.post(
        f"/api/v1/plan-drafts/{body['id']}:confirm", headers=auth_headers, json=confirmation
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    task_id = first.json()["tasks"][0]["id"]
    updated = client.patch(
        f"/api/v1/tasks/{task_id}", headers=auth_headers, json={"status": "done"}
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "done"


def test_tool_catalog_and_calendar_draft_are_idempotent(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    catalog = client.get("/api/v1/tools", headers=auth_headers)
    assert catalog.status_code == 200
    tools = {item["name"]: item for item in catalog.json()}
    assert tools["web.search"]["effect"] == "read"
    assert tools["calendar.create_event_draft"]["effect"] == "draft"

    payload = {
        "arguments": {
            "title": "准备周会",
            "start_at": "2026-08-24T09:00:00+08:00",
            "end_at": "2026-08-24T09:30:00+08:00",
            "timezone": "Asia/Shanghai",
            "notes": "检查本周进展",
        },
        "idempotency_key": "calendar-test-001",
    }
    first = client.post(
        "/api/v1/tools/calendar.create_event_draft:invoke",
        headers=auth_headers,
        json=payload,
    )
    second = client.post(
        "/api/v1/tools/calendar.create_event_draft:invoke",
        headers=auth_headers,
        json=payload,
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["result"]["action_id"] == second.json()["result"]["action_id"]
    assert first.json()["result"]["status"] == "draft"


def test_web_search_tool_returns_sources_and_audit(
    client: TestClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    async def fake_search(self, query: str, *, max_results: int) -> WebSearchResponse:
        del self, max_results
        return WebSearchResponse(
            query=query,
            results=[
                SearchResult(
                    title="教育部就业服务平台",
                    url="https://www.ncss.cn/example",
                    snippet="公开招聘与就业服务信息。",
                    source="www.ncss.cn",
                    score=0.98,
                )
            ],
        )

    monkeypatch.setattr(TavilyWebSearchProvider, "search", fake_search)
    response = client.post(
        "/api/v1/tools/web.search:invoke",
        headers=auth_headers,
        json={"arguments": {"query": "2026 校招最新信息", "max_results": 3}},
    )
    assert response.status_code == 200
    assert response.json()["result"]["results"][0]["url"] == "https://www.ncss.cn/example"

    runs = client.get("/api/v1/tools/runs", headers=auth_headers)
    assert runs.status_code == 200
    assert runs.json()[0]["tool_name"] == "web.search"
    assert runs.json()[0]["status"] == "succeeded"
    assert runs.json()[0]["input_summary"]["query"] == "2026 校招最新信息"


def test_chat_stream_emits_tool_events_and_persists_citations(
    client: TestClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    from app.core.config import Settings
    from app.infrastructure.llm.deepseek import DeepSeekProvider

    selections = 0

    async def fake_select(
        self, messages, tools, *, force_tool_name=None, allow_tool_calls=True
    ):
        nonlocal selections
        del self, messages, tools, force_tool_name
        if not allow_tool_calls or selections:
            return {
                "role": "assistant",
                "content": "根据检索结果，建议优先查看官方就业信息 [1]。",
            }, []
        selections += 1
        call = {
            "id": "call-search-1",
            "type": "function",
            "function": {
                "name": "web__search",
                "arguments": '{"query":"2026 校招最新政策","max_results":3}',
            },
        }
        return {"role": "assistant", "content": None, "tool_calls": [call]}, [call]

    async def fake_search(self, query: str, *, max_results: int) -> WebSearchResponse:
        del self, max_results
        return WebSearchResponse(
            query=query,
            results=[
                SearchResult(
                    title="官方就业信息",
                    url="https://example.edu.cn/jobs",
                    snippet="最新就业政策摘要。",
                    source="example.edu.cn",
                )
            ],
        )

    async def fake_narrative(self, messages, *, max_tokens=2400):
        del self, max_tokens
        no_tool = "不调用工具，直接回答" in messages[-1]["content"]
        return {
            "understanding": "用户想了解 2026 年校招政策的最新变化和实际影响。",
            "next_action": (
                "我会结合已经取得的就业信息整理政策要点。"
                if no_tool
                else "我会联网检索权威就业来源，再根据结果整理政策要点。"
            ),
        }

    async def fake_stream(self, messages):
        del self, messages
        for chunk in ("根据检索结果，", "建议优先查看", "官方就业信息 [1]。"):
            yield chunk

    monkeypatch.setattr(DeepSeekProvider, "select_tool_calls", fake_select)
    monkeypatch.setattr(DeepSeekProvider, "complete_json", fake_narrative)
    monkeypatch.setattr(DeepSeekProvider, "stream_chat", fake_stream)
    monkeypatch.setattr(TavilyWebSearchProvider, "search", fake_search)
    monkeypatch.setattr(Settings, "deepseek_enabled", property(lambda self: True))
    monkeypatch.setattr(Settings, "online_search_available", property(lambda self: True))

    created = client.post(
        "/api/v1/conversations",
        headers=auth_headers,
        json={"title": "联网检索", "mode": "standard"},
    )
    conversation_id = created.json()["id"]
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages:stream",
        headers=auth_headers,
        json={"content": "2026 校招最新政策有哪些？"},
    )
    assert response.status_code == 200
    assert "event: tool.started" in response.text
    assert "event: tool.completed" in response.text
    assert "event: reasoning.step" in response.text
    assert "event: citations" in response.text
    assert "https://example.edu.cn/jobs" in response.text
    assert "校招政策的最新变化" in response.text
    assert "目标、时效性要求和当前可用工具" not in response.text
    assert "DSML" not in response.text

    messages = client.get(
        f"/api/v1/conversations/{conversation_id}/messages", headers=auth_headers
    ).json()
    assert messages[-1]["citations"][0]["source"] == "example.edu.cn"
    assert messages[-1]["reasoning_steps"][-1]["status"] == "completed"


def test_chat_trace_is_contextual_when_no_tool_is_selected(
    client: TestClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    from app.core.config import Settings
    from app.infrastructure.llm.deepseek import DeepSeekProvider

    async def fake_select(
        self, messages, tools, *, force_tool_name=None, allow_tool_calls=True
    ):
        del self, messages, tools, force_tool_name, allow_tool_calls
        return {
            "role": "assistant",
            "content": "我只能依据当前会话中你主动提供的信息来认识你。",
        }, []

    async def fake_narrative(self, messages, *, max_tokens=2400):
        del self, messages, max_tokens
        return {
            "understanding": "你想确认助手目前能识别哪些关于你的信息。",
            "next_action": "我会依据当前会话说明我能看到的信息，以及无法判断的部分。",
        }

    async def fake_stream(self, messages):
        del self, messages
        for chunk in ("我只能依据当前会话中", "你主动提供的信息", "来认识你。"):
            yield chunk

    monkeypatch.setattr(DeepSeekProvider, "select_tool_calls", fake_select)
    monkeypatch.setattr(DeepSeekProvider, "complete_json", fake_narrative)
    monkeypatch.setattr(DeepSeekProvider, "stream_chat", fake_stream)
    monkeypatch.setattr(Settings, "deepseek_enabled", property(lambda self: True))

    created = client.post(
        "/api/v1/conversations",
        headers=auth_headers,
        json={"title": "身份问题", "mode": "standard"},
    )
    conversation_id = created.json()["id"]
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages:stream",
        headers=auth_headers,
        json={"content": "我是谁"},
    )

    assert response.status_code == 200
    assert "目前能识别哪些关于你的信息" in response.text
    assert "依据当前会话说明" in response.text
    assert "时效性要求和当前可用工具" not in response.text
    assert "运行了 web.search" not in response.text
    assert response.text.count("event: message.delta") == 3


def test_ai_planner_uses_structured_model_breakdown(
    client: TestClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    from app.core.config import Settings
    from app.infrastructure.llm.deepseek import DeepSeekProvider

    async def fake_complete_json(self, messages, *, max_tokens=2400):
        del self, messages, max_tokens
        return {
            "title": "完成首次周会汇报",
            "deliverable": "一份可讲解的周会材料",
            "assumptions": ["每天可投入一小时"],
            "risks": ["数据收集不完整"],
            "tasks": [
                {
                    "title": "收集本周事实",
                    "description": "整理完成事项、问题和数据。",
                    "estimated_minutes": 45,
                    "priority": "high",
                    "due_offset_days": 0,
                    "done_definition": "形成事实清单。",
                    "depends_on_indexes": [],
                },
                {
                    "title": "形成汇报材料",
                    "description": "按结论、进展、风险和下一步组织内容。",
                    "estimated_minutes": 60,
                    "priority": "high",
                    "due_offset_days": 1,
                    "done_definition": "完成可预演的材料。",
                    "depends_on_indexes": [0],
                },
            ],
        }

    monkeypatch.setattr(Settings, "deepseek_enabled", property(lambda self: True))
    monkeypatch.setattr(DeepSeekProvider, "complete_json", fake_complete_json)
    response = client.post(
        "/api/v1/plans:draft",
        headers=auth_headers,
        json={"goal": "准备第一次周会并完成清晰汇报", "deadline": "2026-08-25"},
    )
    assert response.status_code == 201
    assert [task["title"] for task in response.json()["tasks"]] == [
        "收集本周事实",
        "形成汇报材料",
    ]
    assert response.json()["tasks"][1]["depends_on"] == [response.json()["tasks"][0]["id"]]


def test_explicit_search_never_falls_back_to_model_when_unconfigured(
    client: TestClient, auth_headers: dict[str, str], monkeypatch
) -> None:
    from app.core.config import Settings

    monkeypatch.setattr(Settings, "online_search_available", property(lambda self: False))
    created = client.post(
        "/api/v1/conversations",
        headers=auth_headers,
        json={"title": "搜索降级", "mode": "standard"},
    )
    response = client.post(
        f"/api/v1/conversations/{created.json()['id']}/messages:stream",
        headers=auth_headers,
        json={"content": "请联网搜索今天的校招信息"},
    )
    assert response.status_code == 200
    assert "event: error" in response.text
    assert "TOOL_UNAVAILABLE" in response.text
    assert "event: message.delta" not in response.text
