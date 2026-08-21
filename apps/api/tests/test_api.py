from fastapi.testclient import TestClient


def test_health_and_ready(client: TestClient) -> None:
    assert client.get("/api/v1/health").json()["status"] == "ok"
    ready = client.get("/api/v1/ready")
    assert ready.status_code == 200
    assert ready.json()["dependencies"]["deepseek"] == "demo-mode"


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
