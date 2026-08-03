"""集中管理环境变量与环境安全约束。"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Any
from uuid import UUID

from pydantic import AnyHttpUrl, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnvironment(StrEnum):
    """应用运行环境。"""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Borough 后端配置。

    真实密钥和连接信息只从环境变量或未纳入版本控制的 `.env` 读取。
    """

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: AppEnvironment = AppEnvironment.DEVELOPMENT
    app_version: str = "0.1.0"
    database_url: str
    frontend_origin: AnyHttpUrl
    business_timezone: str = "Asia/Shanghai"
    demo_merchant_tokens: dict[str, UUID] = Field(default_factory=dict)
    demo_merchants_endpoint_enabled: bool = True
    db_connect_max_attempts: int = Field(default=5, ge=1, le=20)
    db_connect_retry_seconds: float = Field(default=1.0, ge=0, le=60)
    db_statement_timeout_ms: int = Field(default=5_000, ge=100, le=60_000)

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: Any) -> Any:
        if isinstance(value, str) and value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    @field_validator("frontend_origin", mode="before")
    @classmethod
    def reject_wildcard_origin(cls, value: Any) -> Any:
        if value == "*":
            raise ValueError("FRONTEND_ORIGIN 必须是精确 Origin，不能使用 *")
        return value

    @field_validator("frontend_origin")
    @classmethod
    def require_origin_only(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if (
            value.path not in (None, "/")
            or value.query is not None
            or value.fragment is not None
            or value.username is not None
            or value.password is not None
        ):
            raise ValueError("FRONTEND_ORIGIN 只能包含 scheme、host 和 port")
        return value

    @field_validator("business_timezone")
    @classmethod
    def require_business_timezone(cls, value: str) -> str:
        if value != "Asia/Shanghai":
            raise ValueError("BUSINESS_TIMEZONE 必须固定为 Asia/Shanghai")
        return value

    @model_validator(mode="after")
    def enforce_environment_safety(self) -> Settings:
        if self.app_env is AppEnvironment.PRODUCTION:
            self.demo_merchants_endpoint_enabled = False
        return self


@lru_cache
def get_settings() -> Settings:
    """读取并缓存进程级配置。"""

    return Settings()
