"""集中管理环境变量与环境安全约束。"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Any
from uuid import UUID

from pydantic import AliasChoices, AnyHttpUrl, Field, field_validator, model_validator
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
        populate_by_name=True,
    )

    app_env: AppEnvironment = AppEnvironment.DEVELOPMENT
    app_version: str = "0.1.0"
    database_url: str
    frontend_origin: AnyHttpUrl
    business_timezone: str = "Asia/Shanghai"
    demo_merchant_tokens: dict[str, UUID] = Field(default_factory=dict)
    demo_merchants_endpoint_enabled: bool = True
    # 生产环境默认关闭演示端点。演示部署（对外展示用）必须显式开启这一项，
    # 而不是靠把 APP_ENV 降级成非生产来绕过——后者会同时关掉导出签名密钥必填、
    # 管理员令牌必填等一整组生产校验。
    demo_deployment_mode: bool = False
    db_connect_max_attempts: int = Field(default=5, ge=1, le=20)
    db_connect_retry_seconds: float = Field(default=1.0, ge=0, le=60)
    db_statement_timeout_ms: int = Field(default=5_000, ge=100, le=60_000)
    llm_api_key: str | None = None
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-v4-flash"
    llm_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    llm_max_calls_per_request: int = Field(
        default=6,
        ge=1,
        le=20,
        validation_alias=AliasChoices("MAX_LLM_CALLS_PER_REQUEST", "llm_max_calls_per_request"),
    )
    llm_max_tokens_per_request: int = Field(
        default=8_000,
        ge=100,
        le=200_000,
        validation_alias=AliasChoices("MAX_LLM_TOKENS_PER_REQUEST", "llm_max_tokens_per_request"),
    )
    llm_daily_budget_tokens: int = Field(default=20_000, ge=1_000, le=100_000_000)
    llm_max_output_tokens_per_call: int = Field(default=1_024, ge=64, le=8_000)
    rate_limit_per_minute: int = Field(default=10, ge=1, le=10_000)
    trusted_proxy_hops: int = Field(default=0, ge=0, le=4)
    trusted_proxy_ips: str = ""
    admin_token: str | None = None
    export_signing_secret: str | None = None
    export_url_ttl_minutes: int = Field(default=15, ge=1, le=60)

    @property
    def trusted_proxy_ip_set(self) -> frozenset[str]:
        return frozenset(item.strip() for item in self.trusted_proxy_ips.split(",") if item.strip())

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
            self.demo_merchants_endpoint_enabled = self.demo_deployment_mode
            if not self.export_signing_secret:
                raise ValueError("生产环境必须配置 EXPORT_SIGNING_SECRET")
            if self._is_weak_secret(self.export_signing_secret):
                raise ValueError("EXPORT_SIGNING_SECRET 不可使用弱占位值")
            if self.llm_api_key and not self.admin_token:
                raise ValueError("生产环境配置 LLM_API_KEY 时必须设置 ADMIN_TOKEN")
            if self.admin_token and self._is_weak_secret(self.admin_token):
                raise ValueError("ADMIN_TOKEN 不可使用弱占位值")
        return self

    @staticmethod
    def _is_weak_secret(value: str) -> bool:
        normalized = value.strip().lower()
        placeholder_markers = ("<", "placeholder", "change-me", "example", "development")
        return len(value) < 16 or any(marker in normalized for marker in placeholder_markers)


@lru_cache
def get_settings() -> Settings:
    """读取并缓存进程级配置。"""

    return Settings()
