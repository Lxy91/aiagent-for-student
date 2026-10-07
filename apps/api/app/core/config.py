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
        default_factory=lambda: ["http://localhost:5173"]
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
