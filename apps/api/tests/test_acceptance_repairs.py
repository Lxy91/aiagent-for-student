import asyncio
import json

import pytest
from test_execution_checkpoints import CAPACITY_REQUEST, configure_provider, events, tool_call

from app.core.config import Settings
from app.core.errors import AppError
from app.modules.chat.acceptance import acceptance_question, capacity_issues, review_acceptance
from app.modules.chat.interrupts import present_question


def test_legacy_audit_report_becomes_short_decision_without_losing_checkpoint_id():
    original = {
        "id": "stored-checkpoint",
        "kind": "acceptance",
        "status": "waiting",
        "question": "验收未通过，是否继续？",
        "reason": "内部检查原文" * 500,
        "options": ["让我修复所有问题", "补充要求"],
    }
    presented = present_question(original)
    assert presented["id"] == original["id"]
    assert len(presented["reason"]) < 100
    assert len(presented["question"]) < 80
    assert "内部检查原文" not in json.dumps(presented, ensure_ascii=False)
    assert "推荐" in presented["options"][0]
    assert presented["recommendation"]
    assert len(original["reason"]) > 2000


@pytest.mark.parametrize("valid_evidence", [False, True])
def test_input_gate_requires_evidence_from_original_request(valid_evidence):
    class Reviewer:
        async def complete_json(self, messages, **kwargs):
            return {
                "status": "needs_input",
                "issues": ["考试日期尚未给出"],
                "question": "考试具体是哪一天？",
                "input_requirement": "missing_information",
                "input_evidence": ["考试日期待定" if valid_evidence else "W4工时超过上限"],
            }

    report = asyncio.run(
        review_acceptance(Reviewer(), "制定复习方案，考试日期待定。", {}, "草稿", [])
    )
    assert report.status == ("needs_input" if valid_evidence else "failed")


def test_old_internal_repair_checkpoint_no_longer_requires_user_decision():
    question = present_question(
        {"kind": "acceptance", "question": "要继续自动调整方案吗？", "reason": "W4加总错误"}
    )
    assert question["requires_input"] is False


def test_only_original_constraint_conflict_requires_user_and_recommendation_is_actionable():
    class Reviewer:
        async def complete_json(self, messages, **kwargs):
            return {"status": "passed", "issues": []}

    report = asyncio.run(review_acceptance(Reviewer(), CAPACITY_REQUEST, {}, "方案正文", []))
    question = acceptance_question(report)
    assert report.status == "needs_input"
    assert "求职每周最低调整为5小时" in question.options[0]
    assert capacity_issues(CAPACITY_REQUEST + "\n" + question.options[0]) == []
    fixed_request = CAPACITY_REQUEST + "\n求职每周最低改为2小时"
    report = asyncio.run(review_acceptance(Reviewer(), fixed_request, {}, "每周安排27小时", []))
    assert report.status == "failed"  # A bad draft is the assistant's responsibility.


def test_temporary_review_error_retries_without_interrupt_or_rewriting(
    client, auth_headers, monkeypatch
):
    reviews = 0

    async def select(self, messages, tools, **kwargs):
        if not getattr(self, "planned", False):
            self.planned = True
            return tool_call(
                "execution__update_plan",
                {
                    "tasks": [
                        {"id": "a", "title": "形成方案", "status": "completed", "result": "已形成"},
                    ]
                },
                "plan",
            )
        return {"role": "assistant", "content": "应当保留的完整方案。"}, []

    def review(messages):
        nonlocal reviews
        reviews += 1
        if reviews == 1:
            raise AppError("MODEL_PROVIDER_ERROR", "暂时不可用", status_code=502)
        return {"status": "passed", "issues": []}

    configure_provider(monkeypatch, select, review=review)
    conversation = client.post("/api/v1/conversations", headers=auth_headers, json={}).json()
    base = f"/api/v1/conversations/{conversation['id']}/messages"
    response = client.post(
        base + ":stream", headers=auth_headers, json={"content": "形成方案", "use_plan": True}
    )
    stream_events = events(response)
    assert reviews == 2
    assert "自动重试" in response.text
    assert not any(
        event in {"execution.interrupted", "message.replaced"} for event, _ in stream_events
    )
    assert client.get(base, headers=auth_headers).json()[-1]["content"] == "应当保留的完整方案。"


@pytest.mark.parametrize("failures", [1, 3, None])
def test_bad_draft_is_repaired_without_asking_user(client, auth_headers, monkeypatch, failures):
    exhausted = failures is None
    reviews = 0
    long_issue = "内部算术错误与排期检查详情" * 100

    async def select(self, messages, tools, **kwargs):
        if not getattr(self, "planned", False):
            self.planned = True
            return tool_call(
                "execution__update_plan",
                {
                    "tasks": [
                        {
                            "id": "a",
                            "title": "形成计划",
                            "status": "completed",
                            "result": "形成初稿",
                        },
                    ]
                },
                "plan",
            )
        return {"role": "assistant", "content": "旧初稿，存在错误。"}, []

    def review(messages):
        nonlocal reviews
        reviews += 1
        if exhausted or reviews <= failures:
            return {"status": "failed", "issues": [long_issue]}
        assert "实际交付内容" in messages[1]["content"]
        return {"status": "passed", "issues": []}

    configure_provider(monkeypatch, select, review=review)
    conversation = client.post("/api/v1/conversations", headers=auth_headers, json={}).json()
    base = f"/api/v1/conversations/{conversation['id']}/messages"
    response = client.post(
        base + ":stream",
        headers=auth_headers,
        json={"content": "制定方案并校验数值", "use_plan": True},
    )
    stream_events = events(response)
    assert reviews == (
        Settings(_env_file=None).task_acceptance_max_revisions + 1 if exhausted else failures + 1
    )
    assert any(
        event == "execution.phase" and data["phase"] == "revising" for event, data in stream_events
    )
    assert not any(event == "message.replaced" for event, _ in stream_events)
    assert all(
        len(data["detail"]) < 200 for event, data in stream_events if event == "reasoning.step"
    )
    assert any(long_issue in str(data) for event, data in stream_events if event == "agent.debug")
    saved = client.get(base, headers=auth_headers).json()[-1]
    assert "旧初稿" not in saved["content"]
    if exhausted:
        assert "实际交付内容" in saved["draft_content"]
        assert not any(event == "message.delta" for event, _ in stream_events)
        assert not any(event == "execution.interrupted" for event, _ in stream_events)
        assert saved["execution_plan"]["status"] == "paused"
        assert saved["execution_plan"]["acceptance_status"] == "failed"
        assert not saved["execution_interrupt"]
    else:
        assert "实际交付内容" in saved["content"]
        delivered = "".join(
            data["text"] for event, data in stream_events if event == "message.delta"
        )
        assert delivered == saved["content"]
        assert "旧初稿" not in delivered
        assert not any(event == "execution.interrupted" for event, _ in stream_events)
        assert saved["execution_plan"]["status"] == "completed"
