from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.db.session import Database
from app.models.conversation import Conversation, Message
from app.models.memory_v2 import MemoryExtractionJob
from app.models.merchant import Merchant
from app.repositories.database_usage import DatabaseUsageCollectionError, DatabaseUsageRepository
from tests.postgres import truncate_all_tables


@pytest.mark.asyncio
async def test_collect_reports_database_size_connections_and_memory_outbox(
    integration_database: Database,
) -> None:
    database = integration_database
    oldest = datetime.now(UTC) - timedelta(minutes=10)
    async with database.session() as session, session.begin():
        await truncate_all_tables(session)
        merchant = Merchant(merchant_code="database-usage", display_name="Database usage")
        session.add(merchant)
        await session.flush()
        conversation = Conversation(merchant_id=merchant.id, surface="MERCHANT")
        session.add(conversation)
        await session.flush()
        messages = [
            Message(
                merchant_id=merchant.id,
                conversation_id=conversation.id,
                role="USER",
                source_locale="en-US",
                content="database usage example " * 50,
            )
            for _ in range(256)
        ]
        session.add_all(messages)
        await session.flush()
        for message, status, created_at in zip(
            messages[:3],
            ("PENDING", "PENDING", "FAILED"),
            (oldest, oldest + timedelta(minutes=3), oldest - timedelta(minutes=5)),
            strict=True,
        ):
            session.add(
                MemoryExtractionJob(message_id=message.id, status=status, created_at=created_at)
            )
        await session.execute(text("ANALYZE messages"))

    usage = await DatabaseUsageRepository(database).collect(limit_bytes=None)
    assert usage.database_size_bytes > 0
    assert usage.max_connections > 0
    assert 1 <= usage.connections_active <= usage.connections_total
    assert usage.storage_limit_bytes is None
    assert usage.storage_used_ratio is None
    assert 1 <= len(usage.top_tables) <= 10
    sizes = [table.total_bytes for table in usage.top_tables]
    assert all(size >= 0 for size in sizes)
    assert sizes == sorted(sizes, reverse=True)
    assert all(
        table.estimated_rows is None or table.estimated_rows >= 0 for table in usage.top_tables
    )
    (messages_usage,) = [table for table in usage.top_tables if table.table_name == "messages"]
    assert messages_usage.estimated_rows == len(messages)
    assert usage.memory_outbox.pending == 2
    assert usage.memory_outbox.failed == 1
    assert usage.memory_outbox.processing == usage.memory_outbox.done == 0
    assert usage.memory_outbox.oldest_pending_age_seconds == pytest.approx(
        (usage.collected_at - oldest).total_seconds(), abs=2
    )


@pytest.mark.asyncio
async def test_collect_maps_statement_timeout_when_outbox_is_locked(
    integration_database: Database,
) -> None:
    database = integration_database
    async with database.session() as session, session.begin():
        await session.execute(text("LOCK TABLE memory_extraction_jobs IN ACCESS EXCLUSIVE MODE"))
        with pytest.raises(DatabaseUsageCollectionError) as error:
            await DatabaseUsageRepository(database).collect(limit_bytes=None)
    assert error.value.reason == "TIMEOUT"
    await database.ping()
