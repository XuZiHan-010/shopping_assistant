"""安全审计和 LLM 用量 ORM。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UuidPrimaryKeyMixin


class AuditLog(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_merchant_created", "merchant_id", "created_at"),)

    merchant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )


class LlmUsage(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "llm_usage"
    __table_args__ = (
        Index("ix_llm_usage_usage_date", "usage_date"),
        CheckConstraint("reserved_tokens >= 0", name="ck_llm_usage_reserved_tokens_nonnegative"),
        CheckConstraint(
            "purpose IN ('AGENT', 'LOCALIZATION', 'MEMORY')",
            name="ck_llm_usage_purpose",
        ),
    )

    merchant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="SET NULL"),
        nullable=True,
    )
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    call_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
    )
    input_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    output_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    total_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    reserved_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    usage_known: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    failure_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    # 区分本次调用是 Chat Agent 主流程还是 Task 4 的 Localization 通道，供
    # `/api/admin/ops/status` 分别报告两条预算，不把翻译费用隐藏在 Agent
    # 预算描述里。
    purpose: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'AGENT'"),
    )
    # N5 B Task 2：成本在写入时按当时的价格版本算好并存储，查询不重算（PRD §10.2）。
    # 历史行没有角色、价格版本与成本，保持 NULL，表示「未定价」而不是 0。
    role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    cache_hit_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_version_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("model_price_versions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    price_period: Mapped[str | None] = mapped_column(String(16), nullable=True)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    cost_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)


class ModelPriceVersion(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    """模型价格版本：只追加、不修改（`BEFORE UPDATE OR DELETE` 触发器强制，理由同事件账本）。

    单价均为「每百万 token」。DeepSeek 分高峰 / 非高峰两档（见 `app/llm/pricing.py`）。
    价格从官方文档核实后录入，`source_note` 写明核实日期与出处，不凭记忆填写（O7）。
    """

    __tablename__ = "model_price_versions"
    __table_args__ = (
        UniqueConstraint("model", "effective_from", name="uq_model_price_versions_model_from"),
        CheckConstraint(
            "peak_cache_hit >= 0 AND peak_cache_miss >= 0 AND peak_output >= 0 "
            "AND off_peak_cache_hit >= 0 AND off_peak_cache_miss >= 0 AND off_peak_output >= 0",
            name="ck_model_price_versions_nonnegative",
        ),
    )

    model: Mapped[str] = mapped_column(String(120), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    peak_cache_hit: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    peak_cache_miss: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    peak_output: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    off_peak_cache_hit: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    off_peak_cache_miss: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    off_peak_output: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_note: Mapped[str] = mapped_column(String(500), nullable=False)


class LlmDailyBudget(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    """每日 LLM 预算，按级别分行；原子更新而非先查询再判断。

    `scope_key` 取 `GLOBAL`、`ROLE:CUSTOMER`、`ROLE:MERCHANT` 或 `SHOP:<角色>:<商家>`（N5 三级预算，
    PRD §10.2）。迁移前的历史行都是全局行，默认值 `GLOBAL` 让它们原样成为全局级。
    """

    __tablename__ = "llm_daily_budget"
    __table_args__ = (
        UniqueConstraint("usage_date", "scope_key", name="uq_llm_daily_budget_scope"),
    )

    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
    scope_key: Mapped[str] = mapped_column(
        String(120), nullable=False, server_default=text("'GLOBAL'")
    )
    consumed_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    call_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )


class ExportFile(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    """动态 CSV 的受控重放规格；不保存导出文件本身。"""

    __tablename__ = "export_files"
    __table_args__ = (Index("ix_export_files_merchant_expires", "merchant_id", "expires_at"),)

    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: v1 总在 `Answer` 行落库后才创建导出，恒非空；v2 工具循环内的 `create_export`
    #: 在 `Answer` 行落库前写入（`ToolContext.answer_id` 是本轮预分配的真实值，
    #: 但写入这一刻外键还看不到它），因此放宽为可空（迁移 `20260925_0036`）。
    answer_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("answers.id", ondelete="CASCADE"),
        nullable=True,
    )
    export_spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OperationEvidenceNonce(Base):
    """界面操作证据的一次性消费记录（§8.7.9）。

    没有 `merchant_id`：nonce 本身不是经营数据，主体绑定写在**签名载荷**里并在验证时比对；
    把商家写进这张表只会多一处可被伪造输入影响的判定。
    """

    __tablename__ = "operation_evidence_nonces"
    __table_args__ = (
        CheckConstraint("expires_at > issued_at", name="ck_operation_evidence_nonces_window"),
        Index("ix_operation_evidence_nonces_expires_at", "expires_at"),
    )

    purpose: Mapped[str] = mapped_column(String(64), primary_key=True)
    nonce: Mapped[str] = mapped_column(String(64), primary_key=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ScheduledJobRun(Base):
    """Cron 分发器的任务状态（N5 C Task 4；PRD §10.7）：每个任务一行。

    `last_slot` 是最近一次**成功**完成的时间片起点；失败不推进它，下一次调度会在同一时间片重试。
    没有 `merchant_id`：这是系统级调度状态，不含任何经营数据。`last_error` 只存异常类别，
    不存正文（正文可能带连接串或用户原话）。
    """

    __tablename__ = "scheduled_job_runs"
    __table_args__ = (
        CheckConstraint("run_count >= 0", name="ck_scheduled_job_runs_run_count"),
        CheckConstraint(
            "last_status IN ('OK', 'FAILED')", name="ck_scheduled_job_runs_last_status"
        ),
    )

    job_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_slot: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str] = mapped_column(String(16), nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
