import asyncio
import json

import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.infrastructure.llm.deepseek import DeepSeekProvider
from app.modules.chat.acceptance import capacity_issues, review_acceptance
from app.modules.chat.execution_plan import merge_plan


def tasks(count=7):
    return [
        {"id": f"s{i}", "title": f"任务{i}", "status": "running" if i == 1 else "pending"}
        for i in range(1, count + 1)
    ]


def events(response):
    return [
        (block.splitlines()[0][7:], json.loads(block.splitlines()[1][6:]))
        for block in response.text.strip().split("\n\n")
    ]


def test_partial_updates_keep_all_seven_tasks_and_completed_results():
    plan = merge_plan(None, {"tasks": tasks()})
    plan = merge_plan(
        plan,
        {
            "tasks": [
                {"id": "s1", "status": "completed", "result": "实际产出一"},
                {"id": "s2", "status": "running"},
            ]
        },
    )
    plan = merge_plan(
        plan,
        {
            "tasks": [
                {"id": "s2", "status": "completed", "result": "实际产出二"},
                {"id": "s3", "status": "running"},
            ]
        },
    )
    assert len(plan.tasks) == 7
    assert [task.id for task in plan.tasks] == [f"s{i}" for i in range(1, 8)]
    assert plan.tasks[0].result == "实际产出一"
    assert sum(task.status == "completed" for task in plan.tasks) == 2
    with pytest.raises(ValueError):
        merge_plan(plan, {"tasks": [{"id": "new-id", "title": "替换全部任务"}]})
    with pytest.raises(ValueError):
        merge_plan(plan, {"tasks": [{"id": "s1", "title": "悄悄改变任务范围"}]})


def test_completed_steps_require_acceptance_before_showing_complete():
    plan = merge_plan(
        None, {"tasks": [{"id": "a", "title": "交付", "status": "completed", "result": "结果"}]}
    )
    assert plan.snapshot()["status"] == "running"
    plan.acceptance_status = "passed"
    assert plan.snapshot()["status"] == "completed"
    plan.status = "waiting_user"
    assert plan.snapshot()["status"] == "waiting_user"


@pytest.mark.parametrize("case", ["invalid_response", "unavailable", "contradictory_pass"])
def test_acceptance_failure_does_not_silently_pass(case):
    class Reviewer:
        async def complete_json(self, messages, **kwargs):
            if case == "unavailable":
                raise AppError("MODEL_PROVIDER_ERROR", "验收服务不可用", status_code=502)
            if case == "contradictory_pass":
                return {"status": "passed", "issues": ["缺少实际交付物"]}
            return {"unrelated": "not an acceptance report"}

    report = asyncio.run(review_acceptance(Reviewer(), "形成真实交付物", {}, "只有完成声明", []))
    assert report.status == "failed"
    assert report.issues


CAPACITY_REQUEST = (
    "工作日每天最多3小时。\n周六最多7小时。\n周日全天休息。\n"
    "毕业设计每周至少10小时；课程每周至少7小时；求职每周至少6小时。"
)


def test_weekly_minimums_cannot_exceed_capacity_and_only_user_can_change_them():
    issues = capacity_issues(CAPACITY_REQUEST)
    assert "22h" in issues[0] and "23h" in issues[0]
    assert capacity_issues(CAPACITY_REQUEST + "\n求职每周最低改为2小时") == []
    assert (
        "27h" in capacity_issues(CAPACITY_REQUEST + "\n求职每周最低改为2小时", "每周安排27小时")[0]
    )
    assert capacity_issues("工作日最多3h，周六最多7h，周日休息。每周最低：毕设10h、课程7h、求职6h")
    assert (
        capacity_issues(
            "工作日最多3h，周六最多7h，周日休息。毕设总共至少10h，课程总共至少7h，求职总共至少6h"
        )
        == []
    )


def configure_provider(monkeypatch, select, *, review=None):
    async def complete(self, messages, **kwargs):
        if "[TASK_ACCEPTANCE]" in messages[0]["content"]:
            if review:
                return review(messages)
            return {"status": "passed", "issues": []}
        return {"understanding": "按计划推进", "next_action": "完成当前步骤"}

    async def stream(self, messages):
        yield "实际交付内容。"

    monkeypatch.setattr(Settings, "deepseek_enabled", property(lambda self: True))
    monkeypatch.setattr(DeepSeekProvider, "select_tool_calls", select)
    monkeypatch.setattr(DeepSeekProvider, "complete_json", complete)
    monkeypatch.setattr(DeepSeekProvider, "stream_chat", stream)


def tool_call(name, arguments, index):
    call = {
        "id": f"call-{index}",
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments, ensure_ascii=False),
        },
    }
    return {"role": "assistant", "content": None, "tool_calls": [call]}, [call]


@pytest.mark.parametrize("cancel", [False, True])
def test_question_checkpoint_survives_reload_resumes_once_and_keeps_original_plan(
    client, auth_headers, monkeypatch, cancel
):
    captured = []

    async def select(self, messages, tools, **kwargs):
        captured.append(list(messages))
        resumed = any("对暂停问题的明确答复" in str(item.get("content")) for item in messages)
        step = getattr(self, "test_step", 0)
        self.test_step = step + 1
        if resumed:
            if step == 0:
                assert any("实际产出一" in str(item.get("content")) for item in messages)
                assert any("我的自定义安排" in str(item.get("content")) for item in messages)
                expected_ids = {
                    call["id"] for item in messages for call in item.get("tool_calls", [])
                }
                actual_ids = {item["tool_call_id"] for item in messages if item["role"] == "tool"}
                assert expected_ids == actual_ids
                return tool_call(
                    "execution__update_plan",
                    {
                        "tasks": [
                            {
                                "id": "s2",
                                "status": "completed",
                                "result": "按用户明确答复形成了实际产出二",
                            },
                        ]
                    },
                    "resume",
                )
            return {
                "role": "assistant",
                "content": "实际产出一与实际产出二，已采用你的自定义安排。",
            }, []
        if step == 0:
            return tool_call("execution__update_plan", {"tasks": tasks(2)}, "create")
        if step == 1:
            return tool_call(
                "execution__update_plan",
                {
                    "tasks": [
                        {"id": "s1", "status": "completed", "result": "实际产出一"},
                        {"id": "s2", "status": "running"},
                    ]
                },
                "partial",
            )
        message, calls = tool_call(
            "execution__ask_user",
            {
                "question": "请决定第二步的安排",
                "reason": "需要明确约束",
                "options": ["保留约束", "调整约束"],
            },
            "question",
        )
        calls.append(
            {
                "id": "deferred-read",
                "type": "function",
                "function": {
                    "name": "unknown__must_not_run",
                    "arguments": "{}",
                },
            }
        )
        message["tool_calls"] = calls
        return message, calls

    configure_provider(monkeypatch, select)
    conversation = client.post("/api/v1/conversations", headers=auth_headers, json={}).json()
    base = f"/api/v1/conversations/{conversation['id']}/messages"
    response = client.post(
        base + ":stream",
        headers=auth_headers,
        json={"content": "形成两份具体产出", "use_plan": True},
    )
    question = next(data for event, data in events(response) if event == "execution.interrupted")
    saved = client.get(base, headers=auth_headers).json()[-1]
    assert saved["execution_interrupt"]["id"] == question["id"]
    assert saved["execution_plan"]["status"] == "waiting_user"
    assert len(saved["execution_plan"]["tasks"]) == 2
    before = len(captured)
    other = client.post(
        "/api/v1/auth/register",
        json={
            "email": "other-checkpoint@example.com",
            "password": "safe-password-123",
            "display_name": "其他用户",
        },
    ).json()
    assert (
        client.post(
            base + ":stream",
            headers={"Authorization": f"Bearer {other['access_token']}"},
            json={"content": "未授权恢复", "resume_checkpoint_id": question["id"]},
        ).status_code
        == 404
    )
    body = {
        "content": "结束任务" if cancel else "我的自定义安排：保留所有约束，采用方案B",
        "resume_checkpoint_id": question["id"],
        "resume_action": "cancel" if cancel else "continue",
        "use_plan": True,
    }
    response = client.post(base + ":stream", headers=auth_headers, json=body)
    saved_messages = client.get(base, headers=auth_headers).json()
    assert saved_messages[1]["execution_interrupt"]["status"] == (
        "cancelled" if cancel else "resolved"
    )
    assert saved_messages[-1]["execution_plan"]["status"] == (
        "cancelled" if cancel else "completed"
    )
    assert len(captured) == before + (0 if cancel else 2)
    assert client.post(base + ":stream", headers=auth_headers, json=body).status_code == 409


def test_claimed_completion_with_conflicting_capacity_pauses_for_user(
    client, auth_headers, monkeypatch
):
    async def select(self, messages, tools, **kwargs):
        if not getattr(self, "planned", False):
            self.planned = True
            return tool_call(
                "execution__update_plan",
                {
                    "tasks": [
                        {
                            "id": "a",
                            "title": "时间容量校验",
                            "status": "completed",
                            "result": "声称全部满足",
                        },
                    ]
                },
                "claim",
            )
        return {"role": "assistant", "content": "声称每周安排27小时且全部满足要求。"}, []

    configure_provider(monkeypatch, select)
    conversation = client.post("/api/v1/conversations", headers=auth_headers, json={}).json()
    base = f"/api/v1/conversations/{conversation['id']}/messages"
    response = client.post(
        base + ":stream", headers=auth_headers, json={"content": CAPACITY_REQUEST, "use_plan": True}
    )
    question = next(data for event, data in events(response) if event == "execution.interrupted")
    assert question["kind"] == "acceptance"
    assert "22h" in question["reason"] and "23h" in question["reason"]
    saved = client.get(base, headers=auth_headers).json()[-1]
    assert saved["execution_plan"]["acceptance_status"] == "needs_input"
    assert saved["execution_plan"]["status"] == "waiting_user"


def test_prose_pending_confirmation_is_not_accepted_as_completed(client, auth_headers, monkeypatch):
    async def select(self, messages, tools, **kwargs):
        if not getattr(self, "planned", False):
            self.planned = True
            return tool_call(
                "execution__update_plan",
                {
                    "tasks": [
                        {
                            "id": "a",
                            "title": "形成方案",
                            "status": "completed",
                            "result": "方案已形成",
                        },
                    ]
                },
                "claim",
            )
        return {"role": "assistant", "content": "需要你确认的事项：是否同意降低求职投入？"}, []

    def review(messages):
        assert "actual_output" in messages[1]["content"]
        return {
            "status": "needs_input",
            "issues": ["擅自降低求职投入仍待确认"],
            "question": "是否允许降低求职投入？",
            "options": ["保持原要求", "调整（填写新要求）"],
        }

    configure_provider(monkeypatch, select, review=review)
    conversation = client.post("/api/v1/conversations", headers=auth_headers, json={}).json()
    base = f"/api/v1/conversations/{conversation['id']}/messages"
    response = client.post(
        base + ":stream", headers=auth_headers, json={"content": "制定求职方案", "use_plan": True}
    )
    assert not any(event == "execution.interrupted" for event, _ in events(response))
    assert client.get(base, headers=auth_headers).json()[-1]["execution_plan"]["status"] == "paused"
