from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.answer import Answer
from app.models.conversation import Conversation


async def _answer_for_merchant(session: AsyncSession, merchant_id):
    conversation = Conversation(merchant_id=merchant_id, title="导出测试")
    session.add(conversation)
    await session.flush()
    answer = Answer(
        merchant_id=merchant_id,
        conversation_id=conversation.id,
        client_request_id=f"export-{merchant_id}",
        request_digest="a" * 64,
        processing_status="SUCCEEDED",
        response_payload={},
    )
    session.add(answer)
    await session.flush()
    return answer


@pytest.mark.asyncio
async def test_signed_lookup_never_returns_another_merchants_export(
    db_session: AsyncSession,
    merchant_one_id,
    merchant_two_id,
) -> None:
    from app.repositories.export import ExportRepository

    answer = await _answer_for_merchant(db_session, merchant_one_id)
    repository = ExportRepository(db_session)
    created = await repository.create(
        merchant_id=merchant_one_id,
        answer_id=answer.id,
        export_spec={"table": "orders", "columns": ["order_no"], "filters": {}},
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )

    own = await repository.get_for_signed_download(created.id, merchant_one_id)
    other = await repository.get_for_signed_download(created.id, merchant_two_id)

    assert own is not None and own.id == created.id
    assert other is None
