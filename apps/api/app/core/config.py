from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy import URL, make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        extra="ignore",
    )

    app_name: str = "大学生职场适应智能体 API"
    app_version: str = "0.3.0"
    app_env: str = "development"
    app_secret_key: str = "development-only-change-me"
    app_cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    access_token_minutes: int = 24 * 60

    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_timeout_seconds: float = 60.0
    demo_mode: bool = True

    # Estimated-token budget reserved for persisted conversation history. The
    # current message is always retained even when it alone exceeds this value.
    chat_history_token_budget: int = Field(default=12_000, ge=256, le=1_000_000)
    chat_attachment_token_budget: int = Field(default=6_000, ge=256, le=100_000)
    chat_completion_max_tokens: int = Field(default=4_000, ge=256, le=32_000)

    agent_max_iterations: int = Field(default=12, ge=1, le=50)
    # Input budget for the live task, including tool schemas and tool results.
    agent_context_token_budget: int = Field(default=24_000, ge=4096, le=1_000_000)
    agent_trace_enabled: bool = True
    task_acceptance_max_revisions: int = Field(default=6, ge=0, le=12)
    task_completion_max_tokens: int = Field(default=8000, ge=1024, le=32_000)
    document_review_enabled: bool = True
    document_review_max_revisions: int = Field(default=2, ge=0, le=3)
    document_render_enabled: bool = True
    document_renderer_path: str | None = None
    document_render_timeout_seconds: float = Field(default=45, ge=5, le=120)

    bigmodel_api_key: str | None = None
    bigmodel_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    bigmodel_vision_model: str = "glm-5v-turbo"
    bigmodel_image_model: str = "glm-image"
    bigmodel_timeout_seconds: float = 120.0

    web_search_provider: str = "tavily"
    web_search_enabled: bool = True
    tavily_api_key: str | None = None
    tavily_base_url: str = "https://api.tavily.com"
    web_search_timeout_seconds: float = 15.0
    web_search_max_results: int = 5

    qdrant_enabled: bool = True
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "recruitment_job_chunks"
    qdrant_timeout_seconds: float = 10.0
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_cache_dir: str | None = None

    volc_access_key_id: str | None = None
    volc_secret_access_key: str | None = None
    volc_rtc_app_id: str | None = None
    volc_rtc_app_key: str | None = None
    volc_account_id: str | None = None
    volc_avatar_image_url: str | None = None
    volc_rtc_endpoint: str = "https://rtc.volcengineapi.com"
    volc_rtc_region: str = "cn-north-1"
    volc_rtc_api_version: str = "2025-06-01"
    volc_rtc_timeout_seconds: float = 20.0

    max_upload_bytes: int = 20 * 1024 * 1024
    worker_poll_seconds: float = 2.0
    worker_batch_size: int = 50

    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "workplace_agent"
    mysql_password: str = ""
    mysql_database: str = "workplace_agent"
    mysql_echo: bool = False
    database_url_override: str | None = Field(default=None, alias="DATABASE_URL")

    @field_validator("app_cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def deepseek_enabled(self) -> bool:
        return bool(self.deepseek_api_key) and not self.demo_mode

    @property
    def bigmodel_enabled(self) -> bool:
        return bool(self.bigmodel_api_key) and not self.demo_mode

    @property
    def online_search_available(self) -> bool:
        return (
            self.web_search_enabled
            and self.web_search_provider == "tavily"
            and bool(self.tavily_api_key)
        )

    @property
    def qdrant_available(self) -> bool:
        return self.qdrant_enabled and bool(self.qdrant_url)

    @property
    def volc_rtc_available(self) -> bool:
        return all(
            (
                self.volc_access_key_id,
                self.volc_secret_access_key,
                self.volc_rtc_app_id,
                self.volc_rtc_app_key,
            )
        )

    @property
    def volc_avatar_available(self) -> bool:
        return self.volc_rtc_available and bool(
            self.volc_account_id and self.volc_avatar_image_url
        )

    @property
    def database_url(self) -> URL:
        if self.database_url_override:
            return make_url(self.database_url_override)
        return URL.create(
            drivername="mysql+asyncmy",
            username=self.mysql_user,
            password=self.mysql_password,
            host=self.mysql_host,
            port=self.mysql_port,
            database=self.mysql_database,
            query={"charset": "utf8mb4"},
        )

    @property
    def database_backend(self) -> str:
        return self.database_url.get_backend_name()


@lru_cache
def get_settings() -> Settings:
    return Settings()
