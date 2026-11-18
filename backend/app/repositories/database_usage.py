"""只读取当前 PostgreSQL 实例的数据库用量和待办箱聚合。"""

from datetime import UTC, datetime

from psycopg.errors import QueryCanceled
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from app.db.session import Database
from app.schemas.ops import DatabaseUsage, DatabaseUsageError, MemoryOutboxStatus, TableUsage

_TOP_TABLES_LIMIT = 10
_DATABASE_USAGE_SQL = text("""
    SELECT pg_database_size(current_database()) AS database_size_bytes,
           current_setting('max_connections')::int AS max_connections
""")
_CONNECTION_USAGE_SQL = text("""
    SELECT count(*) AS connections_total,
           count(*) FILTER (WHERE state = 'active') AS connections_active
    FROM pg_stat_activity
    WHERE datname = current_database()
""")
_TABLE_USAGE_SQL = text("""
    SELECT c.relname AS table_name,
           pg_total_relation_size(c.oid) AS total_bytes,
           CASE WHEN c.reltuples < 0 THEN NULL ELSE c.reltuples::bigint END AS estimated_rows
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind = 'r' AND n.nspname = 'public'
    ORDER BY total_bytes DESC NULLS LAST, table_name
    LIMIT :limit
""")
_MEMORY_OUTBOX_SQL = text("""
    SELECT count(*) FILTER (WHERE status = 'PENDING') AS pending,
           count(*) FILTER (WHERE status = 'PROCESSING') AS processing,
           count(*) FILTER (WHERE status = 'FAILED') AS failed,
           count(*) FILTER (WHERE status = 'DONE') AS done,
           min(created_at) FILTER (WHERE status = 'PENDING') AS oldest_pending
    FROM public.memory_extraction_jobs
""")


class DatabaseUsageCollectionError(Exception):
    def __init__(self, reason: DatabaseUsageError) -> None:
        super().__init__(reason)
        self.reason = reason


class DatabaseUsageRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def collect(self, limit_bytes: int | None) -> DatabaseUsage:
        try:
            async with self._database.session() as session, session.begin():
                await session.execute(text("SET TRANSACTION READ ONLY"))
                await session.execute(text("SET LOCAL statement_timeout = '2s'"))
                database = (await session.execute(_DATABASE_USAGE_SQL)).mappings().one()
                connections = (await session.execute(_CONNECTION_USAGE_SQL)).mappings().one()
                tables = (
                    await session.execute(_TABLE_USAGE_SQL, {"limit": _TOP_TABLES_LIMIT})
                ).mappings().all()
                outbox = (await session.execute(_MEMORY_OUTBOX_SQL)).mappings().one()
        except DBAPIError as exc:
            reason: DatabaseUsageError = (
                "TIMEOUT" if isinstance(exc.orig, QueryCanceled) else "UNAVAILABLE"
            )
            raise DatabaseUsageCollectionError(reason) from None
        except (SQLAlchemyError, OSError):
            raise DatabaseUsageCollectionError("UNAVAILABLE") from None

        collected_at = datetime.now(UTC)
        oldest_pending = outbox["oldest_pending"]
        return DatabaseUsage(
            collected_at=collected_at,
            database_size_bytes=database["database_size_bytes"],
            storage_limit_bytes=limit_bytes,
            storage_used_ratio=None,
            max_connections=database["max_connections"],
            connections_total=connections["connections_total"],
            connections_active=connections["connections_active"],
            # 并发删除的表可能已无大小。其余表按大小排序并照常返回。
            top_tables=[
                TableUsage.model_validate(row) for row in tables if row["total_bytes"] is not None
            ],
            memory_outbox=MemoryOutboxStatus(
                pending=outbox["pending"],
                processing=outbox["processing"],
                failed=outbox["failed"],
                done=outbox["done"],
                oldest_pending_age_seconds=(
                    max(0, int((collected_at - oldest_pending).total_seconds()))
                    if oldest_pending is not None
                    else None
                ),
            ),
        )
