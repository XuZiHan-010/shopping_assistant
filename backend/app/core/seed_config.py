"""演示数据滚动任务的最小配置，避免 Cron 读取 Web 服务的无关密钥。"""

from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import AppEnvironment


class SeedSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    database_url: str
    app_env: AppEnvironment = AppEnvironment.DEVELOPMENT
    business_timezone: str = "Asia/Shanghai"
    allow_demo_data_refresh: bool = False
    db_connect_max_attempts: int = Field(default=5, ge=1, le=20)
    db_connect_retry_seconds: float = Field(default=1.0, ge=0, le=60)
    db_statement_timeout_ms: int = Field(default=5_000, ge=100, le=60_000)

    @field_validator("allow_demo_data_refresh", mode="before")
    @classmethod
    def require_exact_true(cls, value: object) -> bool:
        return value is True or (isinstance(value, str) and value.lower() == "true")
