from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import AppError
from app.infrastructure.llm.deepseek import DeepSeekProvider
from app.modules.interview.avatar import create_avatar_wss_token
from app.modules.interview.question_bank import build_interview_prompt
from app.modules.interview.rtc import VolcengineRtcClient, create_rtc_token
from app.modules.interview.schemas import (
    CreateInterviewSessionRequest,
    GenerateInterviewReportRequest,
    InterviewQaReview,
    InterviewReadinessResponse,
    InterviewReportResponse,
    InterviewScoreItem,
    InterviewSessionResponse,
)


@dataclass
class _InterviewSession:
    owner_id: str
    response: InterviewSessionResponse
    report: InterviewReportResponse | None = None


_sessions: dict[UUID, _InterviewSession] = {}


class InterviewService:
    def __init__(self, settings: Settings, rtc: VolcengineRtcClient | None = None) -> None:
        self.settings = settings
        self.rtc = rtc or VolcengineRtcClient(settings)

    def readiness(self) -> InterviewReadinessResponse:
        ready = self.settings.volc_rtc_available
        return InterviewReadinessResponse(
            configured=ready,
            avatar_configured=self.settings.volc_avatar_available,
            message=(
                "火山实时数字人已配置"
                if self.settings.volc_avatar_available
                else "请先完成火山数字人凭证和人物照片配置"
            ),
        )

    def create(
        self, owner_id: UUID, payload: CreateInterviewSessionRequest, resume_context: str = ""
    ) -> InterviewSessionResponse:
        if not self.settings.volc_rtc_available:
            raise AppError(
                "VOLC_RTC_NOT_CONFIGURED",
                "火山实时语音尚未完成配置",
                status_code=503,
            )
        if payload.enable_avatar and not self.settings.volc_avatar_available:
            raise AppError(
                "VOLC_AVATAR_NOT_CONFIGURED", "火山实时数字人尚未完成配置", status_code=503
            )
        session_id = uuid4()
        room_id = f"interview_{session_id.hex}"
        user_id = f"candidate_{owner_id.hex[:12]}_{session_id.hex[:8]}"
        agent_user_id = f"interviewer_{session_id.hex[:12]}"
        task_id = f"task_{session_id.hex}"
        response = InterviewSessionResponse(
            id=session_id,
            app_id=self.settings.volc_rtc_app_id,
            room_id=room_id,
            user_id=user_id,
            agent_user_id=agent_user_id,
            task_id=task_id,
            token=create_rtc_token(
                self.settings.volc_rtc_app_id,
                self.settings.volc_rtc_app_key,
                room_id,
                user_id,
            ),
            avatar_wss_token=(
                create_avatar_wss_token(
                    self.settings.volc_access_key_id,
                    self.settings.volc_secret_access_key,
                )
                if payload.enable_avatar
                else None
            ),
            avatar_image_url=(
                self.settings.volc_avatar_image_url if payload.enable_avatar else None
            ),
            track=payload.track,
            interview_type=payload.interview_type,
            difficulty=payload.difficulty,
            duration_minutes=payload.duration_minutes,
            enable_avatar=payload.enable_avatar,
            interview_prompt=build_interview_prompt(
                payload.track, payload.interview_type, payload.difficulty
            )
            + resume_context,
            status="ready",
        )
        _sessions[session_id] = _InterviewSession(owner_id=str(owner_id), response=response)
        return response

    async def start(self, owner_id: UUID, session_id: UUID) -> InterviewSessionResponse:
        session = self._owned(owner_id, session_id)
        if session.response.status == "active":
            return session.response
        track_name = {
            "react": "React",
            "vue": "Vue",
            "general": "泛前端",
        }.get(session.response.track, "泛前端")
        system_prompt = session.response.interview_prompt
        body = {
            "AppId": session.response.app_id,
            "RoomId": session.response.room_id,
            "TaskId": session.response.task_id,
            "Config": {
                "ASRConfig": {
                    "Provider": "volcano",
                    "ProviderParams": {
                        "Mode": "bigmodel",
                        "Credential": {"ApiResourceId": "volc.seedasr.sauc.duration"},
                        "StreamMode": 2,
                        "VolcanoASRParameters": "{}",
                    },
                    "VADConfig": {},
                    "InterruptConfig": {"InterruptKeywords": []},
                },
                "LLMConfig": {
                    "Mode": "ArkV3",
                    "ModelName": "doubao-seed-2-0-lite-260428",
                    "SystemMessages": [system_prompt],
                    "HistoryLength": 20,
                    "ThinkingType": "disabled",
                },
                "TTSConfig": {
                    "Provider": "volcano_bidirection",
                    "ProviderParams": {
                        "Credential": {"ResourceId": "seed-tts-2.0"},
                        "VolcanoTTSParameters": (
                            '{"req_params":{"speaker":"zh_female_vv_uranus_bigtts",'
                            '"audio_params":{"speech_rate":-5},"additions":'
                            '{"disable_markdown_filter":true}}}'
                        ),
                    },
                },
                "InterruptMode": 0,
                "SubtitleConfig": {"SubtitleMode": 3},
                "FunctionCallingConfig": {},
                "WebSearchAgentConfig": {},
                "MemoryConfig": {},
                "MusicAgentConfig": {},
            },
            "AgentConfig": {
                "TargetUserId": [session.response.user_id],
                "UserId": session.response.agent_user_id,
                "WelcomeMessage": (
                    f"你好，我是本场{track_name}面试官。我们先从自我介绍开始，"
                    "请你用两分钟左右介绍自己，并重点说说最有代表性的前端项目。"
                ),
                "Burst": {},
                "EnableConversationStateCallback": False,
                "VoicePrint": {"Mode": 0},
            },
        }
        await self.rtc.start_voice_chat(body)
        session.response.status = "active"
        return session.response

    async def stop(self, owner_id: UUID, session_id: UUID) -> InterviewSessionResponse:
        session = self._owned(owner_id, session_id)
        if session.response.status == "active":
            await self.rtc.stop_voice_chat(
                {
                    "AppId": session.response.app_id,
                    "RoomId": session.response.room_id,
                    "TaskId": session.response.task_id,
                }
            )
        session.response.status = "stopped"
        return session.response

    async def generate_report(
        self,
        owner_id: UUID,
        session_id: UUID,
        payload: GenerateInterviewReportRequest,
    ) -> InterviewReportResponse:
        session = self._owned(owner_id, session_id)
        if session.report is not None:
            return session.report

        answers = [item for item in payload.answers if item.text.strip()]
        if not self.settings.deepseek_enabled or not answers:
            report = self._fallback_report(session_id, answers)
        else:
            try:
                provider = DeepSeekProvider(self.settings)
                raw = await provider.complete_json(
                    [
                        {
                            "role": "system",
                            "content": (
                                "你是资深前端面试官。根据面试配置和候选人的浏览器语音转写生成严格的JSON面试报告。"
                                "由于数字人SDK未返回面试官字幕，question必须根据回答内容谨慎还原，并在问题末尾标注"
                                "‘（根据回答还原）’。不要虚构回答中没有出现的技术细节。评分范围0到100。"
                                "必须返回overall_score、summary、score_items、qa_reviews、strengths、improvements、next_steps。"
                                "score_items必须恰好包含fundamentals/前端基础、framework/框架能力、"
                                "engineering/工程化、communication/表达沟通、problem_solving/问题分析五项，"
                                "每项包含key、label、score、comment。qa_reviews每项包含question、answer、score、feedback。"
                            ),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "track": session.response.track,
                                    "interview_type": session.response.interview_type,
                                    "difficulty": session.response.difficulty,
                                    "duration_minutes": session.response.duration_minutes,
                                    "answer_transcripts": [item.model_dump() for item in answers],
                                },
                                ensure_ascii=False,
                            ),
                        },
                    ],
                    max_tokens=4000,
                )
                report = InterviewReportResponse(
                    session_id=session_id,
                    created_at=datetime.now(UTC),
                    transcript_source="browser_speech_recognition",
                    **raw,
                )
            except (AppError, ValidationError, TypeError):
                report = self._fallback_report(session_id, answers)
        session.report = report
        return report

    @staticmethod
    def _fallback_report(session_id: UUID, answers: list) -> InterviewReportResponse:
        has_answers = bool(answers)
        base_score = 60 if has_answers else 0
        joined = " ".join(item.text.strip() for item in answers)
        qa_reviews = [
            InterviewQaReview(
                question=f"第 {index + 1} 轮面试问题（根据回答还原）",
                answer=item.text.strip(),
                score=base_score,
                feedback="已记录回答；连接在线模型后可获得更精确的逐题点评。",
            )
            for index, item in enumerate(answers)
        ]
        labels = [
            ("fundamentals", "前端基础"),
            ("framework", "框架能力"),
            ("engineering", "工程化"),
            ("communication", "表达沟通"),
            ("problem_solving", "问题分析"),
        ]
        return InterviewReportResponse(
            session_id=session_id,
            overall_score=base_score,
            summary=(
                f"本次共记录 {len(answers)} 段有效回答，转写约 {len(joined)} 字。"
                if has_answers
                else "本次没有获得有效语音转写，暂时无法评分。"
            ),
            score_items=[
                InterviewScoreItem(
                    key=key,
                    label=label,
                    score=base_score,
                    comment="在线评分模型未启用，当前为基础记录分。"
                    if has_answers
                    else "暂无回答证据。",
                )
                for key, label in labels
            ],
            qa_reviews=qa_reviews,
            strengths=["完成了语音面试并留下回答记录"] if has_answers else [],
            improvements=["回答时使用结论、依据、案例的结构，并补充量化结果"]
            if has_answers
            else ["检查麦克风和浏览器语音识别权限后重新面试"],
            next_steps=["针对报告中的薄弱项准备两个项目案例并再次模拟面试"],
            created_at=datetime.now(UTC),
        )

    @staticmethod
    def _owned(owner_id: UUID, session_id: UUID) -> _InterviewSession:
        session = _sessions.get(session_id)
        if session is None or session.owner_id != str(owner_id):
            raise AppError("INTERVIEW_SESSION_NOT_FOUND", "面试会话不存在", status_code=404)
        return session
