import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from pydantic import BaseModel, Field

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse

from app.api.dependencies import SettingsDep
from app.core.security import CurrentUserDep
from app.infrastructure.db.session import SessionDep
from app.modules.interview.schemas import (
    CreateInterviewSessionRequest,
    GenerateInterviewReportRequest,
    InterviewReadinessResponse,
    InterviewReportResponse,
    InterviewSessionResponse,
)
from app.modules.interview.service import InterviewService
from app.modules.memory.resume import ResumeService

router = APIRouter(prefix="/interviews", tags=["interviews"])


@router.get("/readiness", response_model=InterviewReadinessResponse)
async def readiness(
    current_user: CurrentUserDep, settings: SettingsDep
) -> InterviewReadinessResponse:
    del current_user
    return InterviewService(settings).readiness()


@router.post("/sessions", response_model=InterviewSessionResponse, status_code=201)
async def create_session(
    payload: CreateInterviewSessionRequest,
    current_user: CurrentUserDep,
    settings: SettingsDep,
    session: SessionDep,
) -> InterviewSessionResponse:
    return InterviewService(settings).create(
        current_user.id,
        payload,
        await ResumeService(session).context(current_user.id, allow_lookup=False),
    )


@router.post("/sessions/{session_id}:start", response_model=InterviewSessionResponse)
async def start_session(
    session_id: UUID, current_user: CurrentUserDep, settings: SettingsDep
) -> InterviewSessionResponse:
    return await InterviewService(settings).start(current_user.id, session_id)


@router.post("/sessions/{session_id}:stop", response_model=InterviewSessionResponse)
async def stop_session(
    session_id: UUID, current_user: CurrentUserDep, settings: SettingsDep
) -> InterviewSessionResponse:
    return await InterviewService(settings).stop(current_user.id, session_id)


@router.post("/sessions/{session_id}:report", response_model=InterviewReportResponse)
async def generate_report(
    session_id: UUID,
    payload: GenerateInterviewReportRequest,
    current_user: CurrentUserDep,
    settings: SettingsDep,
) -> InterviewReportResponse:
    return await InterviewService(settings).generate_report(current_user.id, session_id, payload)


class InterviewDiagnostic(BaseModel):
    session_id: UUID
    event: str = Field(max_length=80, pattern=r"^[a-z_]+$")
    request_id: str = Field(default="", max_length=80)
    elapsed_ms: int = Field(default=0, ge=0)
    detail: str = Field(default="", max_length=300)


@router.post("/diagnostics", status_code=204)
async def diagnostic(payload: InterviewDiagnostic, current_user: CurrentUserDep):
    logger = logging.getLogger("interview.diagnostics")
    if not logger.handlers:
        directory = Path(__file__).resolve().parents[3] / "data" / "logs"
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(directory / "interview.jsonl", maxBytes=5_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    from datetime import datetime, timezone
    logger.info(json.dumps({"time": datetime.now(timezone.utc).isoformat(), "user_id": str(current_user.id), **payload.model_dump(mode="json")}, ensure_ascii=False))


_history_dir = Path(__file__).resolve().parents[3] / "data" / "interview_reports"


def _save_history(owner, record):
    directory = _history_dir / str(owner)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (record["id"] + ".json")
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    temporary.replace(target)


@router.get("/history")
async def history(current_user: CurrentUserDep):
    cleanup_interview_history()
    directory = _history_dir / str(current_user.id)
    return sorted([json.loads(path.read_text(encoding="utf-8")) for path in directory.glob("*.json")], key=lambda item: item["created_at"], reverse=True)


@router.post("/sessions/{session_id}:complete", status_code=202)
async def complete_session(session_id: UUID, payload: GenerateInterviewReportRequest,
                           background_tasks: BackgroundTasks, current_user: CurrentUserDep,
                           settings: SettingsDep):
    from datetime import datetime, timezone
    service = InterviewService(settings)
    owned = service._owned(current_user.id, session_id)
    record = {"id": str(session_id), "created_at": datetime.now(timezone.utc).isoformat(),
              "status": "generating", "track": owned.response.track, "report": None, "clips": []}
    manifest = _history_dir / str(current_user.id) / str(session_id) / "clips.json"
    if manifest.exists():
        record["clips"] = json.loads(manifest.read_text(encoding="utf-8"))
    _save_history(current_user.id, record)
    async def generate():
        try:
            await service.stop(current_user.id, session_id)
            report = await service.generate_report(current_user.id, session_id, payload)
            record.update(status="completed", report=report.model_dump(mode="json"))
        except Exception:
            logging.getLogger(__name__).exception("Interview report failed: %s", session_id)
            record.update(status="failed")
        _save_history(current_user.id, record)
    background_tasks.add_task(generate)
    return {"status": "generating"}


def cleanup_interview_history():
    import time
    import shutil
    cutoff = time.time() - 3 * 86400
    for owner in _history_dir.glob("*"):
        if not owner.is_dir():
            continue
        for record in owner.glob("*.json"):
            if record.stat().st_mtime < cutoff:
                media = owner / record.stem
                if media.is_dir() and media.resolve().parent == owner.resolve():
                    shutil.rmtree(media)
                record.unlink()
        for media in owner.iterdir():
            if media.is_dir() and media.stat().st_mtime < cutoff and media.resolve().parent == owner.resolve():
                shutil.rmtree(media)


@router.post("/sessions/{session_id}/clips")
async def upload_clip(session_id: UUID, current_user: CurrentUserDep, settings: SettingsDep,
                      video: UploadFile = File(...), question: str = Form(...),
                      main: int = Form(...), follow_up: bool = Form(False)):
    InterviewService(settings)._owned(current_user.id, session_id)
    from uuid import uuid4
    directory = _history_dir / str(current_user.id) / str(session_id)
    directory.mkdir(parents=True, exist_ok=True)
    clip_id = uuid4().hex
    target = directory / (clip_id + ".webm")
    size = 0
    try:
        with target.open("wb") as stream:
            while chunk := await video.read(1024 * 1024):
                size += len(chunk)
                if size > 150 * 1024 * 1024:
                    raise HTTPException(413, "单段录像不能超过150MB")
                stream.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await video.close()
    import asyncio
    await asyncio.to_thread(normalize_recording, target)
    manifest = directory / "clips.json"
    clips = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else []
    clips.append({"id": clip_id, "question": question[:4000], "main": main, "followUp": follow_up})
    manifest.write_text(json.dumps(clips, ensure_ascii=False), encoding="utf-8")
    return {"id": clip_id}


@router.get("/history/{session_id}/clips/{clip_id}")
async def read_clip(session_id: UUID, clip_id: UUID, current_user: CurrentUserDep):
    cleanup_interview_history()
    target = _history_dir / str(current_user.id) / str(session_id) / (clip_id.hex + ".webm")
    if not target.is_file():
        raise HTTPException(404, "录像不存在或已过三天保留期")
    return FileResponse(target, media_type="video/webm")


def normalize_recording(target: Path):
    """Finalize MediaRecorder WebM duration and seek index without re-encoding."""
    import subprocess
    import imageio_ffmpeg
    temporary = target.with_suffix(".finalizing.webm")
    try:
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", str(target),
                        "-map", "0", "-c", "copy", str(temporary)],
                       check=True, capture_output=True, timeout=60,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
