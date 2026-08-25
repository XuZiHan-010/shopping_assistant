"""演示数据滚动任务的最小配置，避免 Cron 读取 Web 服务的无关密钥。"""

from __future__ import annotations

from pydantic import field_validator

from app.core.job_config import JobSettings


class SeedSettings(JobSettings):
    """在通用离线任务配置之上，追加演示数据写权限这一个高风险开关。"""

    allow_demo_data_refresh: bool = False

    @field_validator("allow_demo_data_refresh", mode="before")
    @classmethod
    def require_exact_true(cls, value: object) -> bool:
        return value is True or (isinstance(value, str) and value.lower() == "true")
