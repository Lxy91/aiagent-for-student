from test_execution_checkpoints import configure_provider, tool_call

from app.core.config import Settings
from app.infrastructure.search.tavily import TavilyWebSearchProvider
from app.modules.chat.execution_plan import merge_plan
from app.modules.chat.execution_trace import (
    plan_update_detail,
    tool_completed_detail,
    tool_failed_detail,
    tool_started_detail,
)
from app.ports.web_search import SearchResult, WebSearchResponse


def test_search_trace_contains_real_query_and_result_count():
    arguments = {"query": "杭州前端校招", "max_results": 2}
    assert "杭州前端校招" in tool_started_detail("web.search", arguments)
    assert "返回 2 条来源" in tool_completed_detail("web.search", arguments, {"results": [{}, {}]})
    assert "返回 0 条来源" in tool_completed_detail("web.search", arguments, {"results": []})
    assert "个职位" in tool_completed_detail("recruitment.search", arguments, {"results": [{}]})
    failure = tool_failed_detail("web.search", arguments, "搜索超时", "TOOL_TIMEOUT")
    assert "杭州前端校招" in failure and "搜索超时" in failure and "TOOL_TIMEOUT" in failure


def test_fetch_trace_contains_page_url_length_and_no_credentials():
    args = {"url": "https://username:password@example.org/jobs?api_key=secret-value"}
    started = tool_started_detail("web.fetch", args)
    completed = tool_completed_detail(
        "web.fetch", args, {"title": "招聘公告", "content": "真实正文", "truncated": True}
    )
    for detail in (started, completed):
        assert "example.org/jobs" in detail
        assert "secret-value" not in detail
        assert "username:password" not in detail
    assert "招聘公告" in completed and "4 字正文" in completed and "已截取" in completed


def test_plan_trace_explains_actual_step_changes():
    before = merge_plan(
        None,
        {
            "tasks": [
                {"id": "s1", "title": "核对约束", "status": "running"},
                {"id": "s2", "title": "编制日程"},
            ]
        },
    )
    assert "创建 2 项任务" in plan_update_detail(None, before)
    after = merge_plan(
        before,
        {
            "tasks": [
                {"id": "s1", "status": "completed", "result": "已核对"},
                {"id": "s2", "status": "running"},
            ]
        },
    )
    detail = plan_update_detail(before, after)
    assert "完成「核对约束」" in detail
    assert "开始「编制日程」" in detail
    assert "1/2" in detail
    assert "继续「编制日程」" in plan_update_detail(after, after)


def test_tool_trace_is_saved_with_actual_plan_actions_and_search_results(
    client, auth_headers, monkeypatch
):
    async def select(self, messages, tools, **kwargs):
        phase = getattr(self, "phase", 0)
        self.phase = phase + 1
        if phase == 0:
            return tool_call(
                "execution__update_plan",
                {
                    "tasks": [
                        {"id": "s1", "title": "检索岗位", "status": "running"},
                        {"id": "s2", "title": "分析要求"},
                    ]
                },
                "create",
            )
        if phase == 1:
            return tool_call("web__search", {"query": "杭州前端校招", "max_results": 2}, "search")
        if phase == 2:
            return tool_call(
                "execution__update_plan",
                {
                    "tasks": [
                        {"id": "s1", "status": "completed", "result": "已获得两条来源"},
                        {"id": "s2", "status": "running"},
                    ]
                },
                "advance",
            )
        if phase == 3:
            return tool_call(
                "execution__update_plan",
                {
                    "tasks": [
                        {"id": "s2", "status": "completed", "result": "已分析要求"},
                    ]
                },
                "finish",
            )
        return {"role": "assistant", "content": "已基于实际来源分析要求。"}, []

    async def search(self, query, *, max_results):
        return WebSearchResponse(
            query=query,
            results=[
                SearchResult(
                    title=f"岗位{index}",
                    url=f"https://example.org/{index}",
                    snippet="岗位要求",
                    source="example.org",
                )
                for index in range(2)
            ],
        )

    configure_provider(monkeypatch, select)
    monkeypatch.setattr(Settings, "online_search_available", property(lambda self: True))
    monkeypatch.setattr(TavilyWebSearchProvider, "search", search)
    conversation = client.post("/api/v1/conversations", headers=auth_headers, json={}).json()
    base = f"/api/v1/conversations/{conversation['id']}/messages"
    response = client.post(
        base + ":stream", headers=auth_headers, json={"content": "分析前端岗位", "use_plan": True}
    )
    assert "event: error" not in response.text
    saved = client.get(base, headers=auth_headers).json()[-1]
    details = [step["detail"] for step in saved["reasoning_steps"]]
    assert any(
        "web.search" in detail and "杭州前端校招" in detail and "返回 2 条来源" in detail
        for detail in details
    )
    assert any("完成「检索岗位」" in detail and "开始「分析要求」" in detail for detail in details)
    assert any("等待验收" in detail for detail in details)
    assert "我会更新任务计划，再推进当前步骤。" not in details
    assert not any(
        step["kind"] == "tool" and step["status"] == "running" for step in saved["reasoning_steps"]
    )
