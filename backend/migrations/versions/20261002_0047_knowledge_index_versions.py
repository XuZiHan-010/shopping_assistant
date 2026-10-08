"""N4-C：pgvector 扩展、知识索引版本、分块与生效指针（PRD A7、§7.6，契约 §6.14）。

- `knowledge_index_versions`：每次构建一行，状态只走 BUILDING → VALIDATING → READY / FAILED；
  「生效」不是状态，而是 `knowledge_index_state` 指针指向的那个 READY 版本；
- `knowledge_chunks`：分块与向量**只按版本写入、不原地更新**，查询按指针过滤；
- `knowledge_index_state`：单行指针，原子切换就是在一个事务里改这一行；
- 同一时刻只允许一个版本处于构建/验证中：部分唯一索引由数据库强制，不靠应用层自觉。

向量列不声明维度：语料只有几十个分块，精确扫描足够，不建 ANN 索引；
换嵌入模型（维度变化）时新版本可直接写入。语料到数千块再评估 HNSW（届时须固定维度）。

外部 Neon 与本地 `pgvector/pgvector:pg16` 均已确认 `vector` 0.8.6 可用（2026-10-02）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261002_0047"
down_revision: str | Sequence[str] | None = "20261001_0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


class _Vector(sa.types.UserDefinedType[object]):
    """迁移自带的最小列类型：不依赖应用代码，日后模型改动不会改写历史迁移。"""

    cache_ok = True

    def get_col_spec(self, **_kw: object) -> str:
        return "vector"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "knowledge_index_versions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("embedding_model", sa.String(200), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=True),
        sa.Column("corpus_fingerprint", sa.String(64), nullable=True),
        sa.Column("document_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("recall_at_5", sa.Float(), nullable=True),
        sa.Column("baseline_recall_at_5", sa.Float(), nullable=True),
        sa.Column("failure_reason", sa.String(64), nullable=True),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('BUILDING', 'VALIDATING', 'READY', 'FAILED')",
            name="ck_knowledge_index_versions_status",
        ),
        sa.CheckConstraint(
            "(status = 'FAILED') = (failure_reason IS NOT NULL)",
            name="ck_knowledge_index_versions_failure_reason",
        ),
    )
    op.create_index(
        "uq_knowledge_index_versions_single_build",
        "knowledge_index_versions",
        [sa.text("(true)")],
        unique=True,
        postgresql_where=sa.text("status IN ('BUILDING', 'VALIDATING')"),
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "version_id",
            sa.BigInteger(),
            sa.ForeignKey("knowledge_index_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", _Vector(), nullable=False),
        sa.UniqueConstraint(
            "version_id", "source_path", "chunk_index", name="uq_knowledge_chunks_version_chunk"
        ),
    )

    op.create_table(
        "knowledge_index_state",
        sa.Column("id", sa.SmallInteger(), primary_key=True),
        sa.Column(
            "active_version_id",
            sa.BigInteger(),
            sa.ForeignKey("knowledge_index_versions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("stale", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("stale_reason", sa.String(64), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("id = 1", name="ck_knowledge_index_state_single_row"),
        sa.CheckConstraint(
            "stale = (stale_reason IS NOT NULL)", name="ck_knowledge_index_state_stale_reason"
        ),
    )


def downgrade() -> None:
    op.drop_table("knowledge_index_state")
    op.drop_table("knowledge_chunks")
    op.drop_index("uq_knowledge_index_versions_single_build", "knowledge_index_versions")
    op.drop_table("knowledge_index_versions")
    # 不 DROP EXTENSION：扩展可能已被库里其他对象使用，降级只撤销本迁移建的表。
