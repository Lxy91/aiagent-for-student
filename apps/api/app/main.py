from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1.router import router as api_v1_router
from app.core.config import get_settings
from app.core.errors import AppError, app_error_handler
from app.infrastructure.db.session import SessionDep


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="可信职场问答、可控长期记忆、联网检索与行动工具 API。",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.app_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]


@app.middleware("http")
async def attach_trace_id(request: Request, call_next):
    request.state.trace_id = request.headers.get("x-trace-id", str(uuid4()))
    response = await call_next(request)
    response.headers["x-trace-id"] = request.state.trace_id
    return response


@app.get("/api/v1/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok", "version": settings.app_version}


@app.get("/api/v1/ready", tags=["system"])
async def ready(session: SessionDep) -> dict[str, object]:
    await session.execute(text("SELECT 1"))
    return {
        "status": "ready",
        "dependencies": {
            "storage": settings.database_backend,
            "deepseek": "enabled" if settings.deepseek_enabled else "demo-mode",
            "web_search": "enabled" if settings.online_search_available else "not-configured",
        },
    }


app.include_router(api_v1_router)
