import base64
import struct
from uuid import uuid4

from app.core.config import Settings
from app.modules.interview.avatar import create_avatar_wss_token
from app.modules.interview.rtc import create_rtc_token
from app.modules.interview.schemas import (
    CreateInterviewSessionRequest,
    GenerateInterviewReportRequest,
    InterviewTranscriptEntry,
)
from app.modules.interview.service import InterviewService


def configured_settings() -> Settings:
    return Settings(
        volc_access_key_id="test-access-key",
        volc_secret_access_key="test-secret-key",
        volc_rtc_app_id="123456789012345678901234",
        volc_rtc_app_key="0123456789abcdef0123456789abcdef",
        volc_account_id="1234567890",
        volc_avatar_image_url="https://example.com/avatar.jpg",
    )


def test_rtc_token_contains_expected_version_and_app_id() -> None:
    app_id = "123456789012345678901234"
    token = create_rtc_token(app_id, "secret", "room-one", "user-one", now=1_700_000_000)

    assert token.startswith(f"001{app_id}")
    content = base64.b64decode(token[27:])
    message_length = struct.unpack_from("<H", content)[0]
    assert message_length > 20
    assert b"room-one" in content
    assert b"user-one" in content


def test_avatar_wss_token_contains_signed_websocket_config() -> None:
    token = create_avatar_wss_token("test-ak", "test-sk")
    payload = base64.b64decode(token).decode()

    assert "visual.volcengineapi.com?Action=ConnectWebsocket" in payload
    assert '"Authorization":"HMAC-SHA256 Credential=test-ak/' in payload


def test_create_interview_session_returns_scoped_rtc_credentials() -> None:
    service = InterviewService(configured_settings())
    owner_id = uuid4()

    session = service.create(
        owner_id,
        CreateInterviewSessionRequest(
            track="react",
            interview_type="technical",
            difficulty="advanced",
            duration_minutes=30,
            enable_avatar=True,
        ),
    )

    assert session.app_id == "123456789012345678901234"
    assert session.room_id.startswith("interview_")
    assert session.user_id.startswith(f"candidate_{owner_id.hex[:12]}")
    assert session.agent_user_id.startswith("interviewer_")
    assert session.token.startswith("001123456789012345678901234")
    assert session.avatar_image_url == "https://example.com/avatar.jpg"
    assert "ConnectWebsocket" in base64.b64decode(session.avatar_wss_token).decode()
    assert session.status == "ready"


def test_generate_interview_report_falls_back_when_model_is_disabled() -> None:
    service = InterviewService(configured_settings())
    owner_id = uuid4()
    session = service.create(owner_id, CreateInterviewSessionRequest(track="react"))

    import asyncio

    report = asyncio.run(
        service.generate_report(
            owner_id,
            session.id,
            GenerateInterviewReportRequest(
                answers=[
                    InterviewTranscriptEntry(
                        text="我在项目里使用 hooks 拆分状态，并通过 memo 减少重复渲染。",
                        recorded_at_seconds=42,
                    )
                ]
            ),
        )
    )

    assert report.overall_score == 60
    assert len(report.score_items) == 5
    assert report.qa_reviews[0].answer.startswith("我在项目里")
