"""团队知识文档仓储集成测试。"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.knowledge import KnowledgeRepository


@pytest.mark.asyncio
async def test_upsert_by_source_path_updates_the_existing_document(
    db_session: AsyncSession,
) -> None:
    """若导入重复创建记录，知识检索将返回重复内容。"""

    repository = KnowledgeRepository(db_session)
    await repository.upsert_by_source_path(
        source_path="业务/交易/业务流程/交易业务流程图.md",
        category="TRADE",
        title="交易业务流程图",
        content="下单到履约的流程。",
        source="Borough 团队维护",
        is_complete=True,
    )
    await repository.upsert_by_source_path(
        source_path="业务/交易/业务流程/交易业务流程图.md",
        category="TRADE",
        title="交易业务流程图",
        content="下单到履约的流程（已更新）。",
        source="Borough 团队维护",
        is_complete=True,
    )
    await db_session.flush()

    documents = await repository.list_active()

    assert len(documents) == 1
    assert documents[0].content == "下单到履约的流程（已更新）。"
    assert documents[0].version == 2


@pytest.mark.asyncio
async def test_upsert_preserves_the_incomplete_knowledge_marker(
    db_session: AsyncSession,
) -> None:
    """丢失骨架标记会让后续回答把不完整知识伪装成正式资料。"""

    repository = KnowledgeRepository(db_session)

    await repository.upsert_by_source_path(
        source_path="业务/优惠券/业务名词解释/优惠券名词.md",
        category="COUPON",
        title="优惠券名词",
        content="⚠️ 待团队补充",
        source="Borough 团队维护",
        is_complete=False,
    )
    await db_session.flush()

    documents = await repository.list_active()

    assert documents[0].is_complete is False
