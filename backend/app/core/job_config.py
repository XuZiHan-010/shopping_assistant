"""离线任务的最小数据库配置。

Cron 任务只需要连库，不该因为 Web 服务的 `EXPORT_SIGNING_SECRET`、
`FRONTEND_ORIGIN` 等字段缺失就起不来，更不该为了起得来而被注入这些密钥
（`docs/deployment.md`「演示数据的每日滚动」已为滚动 Seed 确立该原则）。
`SeedSettings` 在此基础上追加它自己的写权限开关。
"""

from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import AppEnvironment


class JobSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    database_url: str
    app_env: AppEnvironment = AppEnvironment.DEVELOPMENT
    business_timezone: str = "Asia/Shanghai"
    db_connect_max_attempts: int = Field(default=5, ge=1, le=20)
    db_connect_retry_seconds: float = Field(default=1.0, ge=0, le=60)
    db_statement_timeout_ms: int = Field(default=5_000, ge=100, le=60_000)

    @field_validator("business_timezone")
    @classmethod
    def require_business_timezone(cls, value: str) -> str:
        # 与 `Settings` 同一口径：汇总按业务时区切日，时区漂移会让同一批回答
        # 落进不同的 stat_date，重刷也纠正不回来。
        if value != "Asia/Shanghai":
            raise ValueError("BUSINESS_TIMEZONE 必须固定为 Asia/Shanghai")
        return value
