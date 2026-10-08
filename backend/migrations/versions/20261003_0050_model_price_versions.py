"""N5 B Task 2：模型价格版本表与用量成本（PRD §10.2）。

- `model_price_versions`：只追加，`BEFORE UPDATE OR DELETE` 触发器拒绝改写（理由同事件账本：历史成本
  按当时价格算好存下，若价格行可改，存下的成本就失去出处）；
- 初始两行价格 2026-10-03 从 DeepSeek 官方文档核实
  （https://api-docs.deepseek.com/quick_start/pricing），
  单位为美元 / 百万 token，分高峰 / 非高峰；`effective_from` 取核实当日 00:00 UTC——
  此前的用量没有价格版本，成本保持 NULL（未定价），不按新价格回算；
- `llm_usage` 加角色、缓存命中 token、价格版本、计价时段与成本列，历史行全部为 NULL。

Revision ID: 20261003_0050
Revises: 20261003_0049
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261003_0050"
down_revision: str | Sequence[str] | None = "20261003_0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 用时间对象而不是字符串：离线生成 SQL（`alembic upgrade --sql`）时字符串无法渲染成时间字面量。
_EFFECTIVE_FROM = datetime(2026, 10, 3, tzinfo=UTC)
_SOURCE = "2026-10-03 核实 https://api-docs.deepseek.com/quick_start/pricing（USD/百万 token）"


def upgrade() -> None:
    op.create_table(
        "model_price_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("peak_cache_hit", sa.Numeric(12, 6), nullable=False),
        sa.Column("peak_cache_miss", sa.Numeric(12, 6), nullable=False),
        sa.Column("peak_output", sa.Numeric(12, 6), nullable=False),
        sa.Column("off_peak_cache_hit", sa.Numeric(12, 6), nullable=False),
        sa.Column("off_peak_cache_miss", sa.Numeric(12, 6), nullable=False),
        sa.Column("off_peak_output", sa.Numeric(12, 6), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_note", sa.String(500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("model", "effective_from", name="uq_model_price_versions_model_from"),
        sa.CheckConstraint(
            "peak_cache_hit >= 0 AND peak_cache_miss >= 0 AND peak_output >= 0 "
            "AND off_peak_cache_hit >= 0 AND off_peak_cache_miss >= 0 AND off_peak_output >= 0",
            name="ck_model_price_versions_nonnegative",
        ),
    )
    op.execute(
        sa.text(
            """
            CREATE FUNCTION model_price_versions_append_only() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'model_price_versions 只允许追加：价格变动请新增一条版本';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_model_price_versions_append_only "
            "BEFORE UPDATE OR DELETE ON model_price_versions "
            "FOR EACH ROW EXECUTE FUNCTION model_price_versions_append_only()"
        )
    )
    prices = sa.table(
        "model_price_versions",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("model", sa.String),
        sa.column("currency", sa.String),
        sa.column("peak_cache_hit", sa.Numeric),
        sa.column("peak_cache_miss", sa.Numeric),
        sa.column("peak_output", sa.Numeric),
        sa.column("off_peak_cache_hit", sa.Numeric),
        sa.column("off_peak_cache_miss", sa.Numeric),
        sa.column("off_peak_output", sa.Numeric),
        sa.column("effective_from", sa.DateTime(timezone=True)),
        sa.column("source_note", sa.String),
    )
    op.bulk_insert(
        prices,
        [
            {
                "id": "6d1f0a52-2b0e-4c6a-9a51-000000000001",
                "model": "deepseek-flash",
                "currency": "USD",
                "peak_cache_hit": "0.006",
                "peak_cache_miss": "0.3",
                "peak_output": "1.2",
                "off_peak_cache_hit": "0.003",
                "off_peak_cache_miss": "0.15",
                "off_peak_output": "0.6",
                "effective_from": _EFFECTIVE_FROM,
                "source_note": _SOURCE,
            },
            {
                "id": "6d1f0a52-2b0e-4c6a-9a51-000000000002",
                "model": "deepseek-v4-pro",
                "currency": "USD",
                "peak_cache_hit": "0.044",
                "peak_cache_miss": "1.32",
                "peak_output": "3.96",
                "off_peak_cache_hit": "0.022",
                "off_peak_cache_miss": "0.66",
                "off_peak_output": "1.98",
                "effective_from": _EFFECTIVE_FROM,
                "source_note": _SOURCE,
            },
        ],
    )

    op.add_column("llm_usage", sa.Column("role", sa.String(16), nullable=True))
    op.add_column("llm_usage", sa.Column("cache_hit_tokens", sa.Integer(), nullable=True))
    op.add_column(
        "llm_usage",
        sa.Column(
            "price_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "model_price_versions.id",
                name="fk_llm_usage_price_version_id",
                ondelete="RESTRICT",
            ),
            nullable=True,
        ),
    )
    op.add_column("llm_usage", sa.Column("price_period", sa.String(16), nullable=True))
    op.add_column("llm_usage", sa.Column("cost", sa.Numeric(18, 8), nullable=True))
    op.add_column("llm_usage", sa.Column("cost_currency", sa.String(8), nullable=True))


def downgrade() -> None:
    for column in (
        "cost_currency",
        "cost",
        "price_period",
        "price_version_id",
        "cache_hit_tokens",
        "role",
    ):
        op.drop_column("llm_usage", column)
    op.execute(sa.text("DROP TRIGGER trg_model_price_versions_append_only ON model_price_versions"))
    op.execute(sa.text("DROP FUNCTION model_price_versions_append_only()"))
    op.drop_table("model_price_versions")
