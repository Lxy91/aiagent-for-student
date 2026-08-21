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
    app_version: str = "0.1.0"
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

    max_upload_bytes: int = 20 * 1024 * 1024

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
