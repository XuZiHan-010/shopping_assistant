"""运维看板的数据库聚合用量。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

DatabaseUsageError = Literal["TIMEOUT", "UNAVAILABLE"]


class TableUsage(BaseModel):
    table_name: str
    total_bytes: int = Field(ge=0)
    estimated_rows: int | None = Field(ge=0)


class MemoryOutboxStatus(BaseModel):
    pending: int = Field(ge=0)
    processing: int = Field(ge=0)
    failed: int = Field(ge=0)
    done: int = Field(ge=0)
    oldest_pending_age_seconds: int | None = Field(ge=0)


class DatabaseUsage(BaseModel):
    collected_at: datetime
    database_size_bytes: int = Field(ge=0)
    storage_limit_bytes: int | None = Field(gt=0)
    storage_used_ratio: float | None = Field(ge=0)
    max_connections: int = Field(ge=0)
    connections_total: int = Field(ge=0)
    connections_active: int = Field(ge=0)
    top_tables: list[TableUsage] = Field(max_length=10)
    memory_outbox: MemoryOutboxStatus
