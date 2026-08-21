"""后台沉淀必须把该商家该分类的历史问答真的喂给压缩。

回归覆盖一次静默退化：`MemoryAgent._consolidate` 曾把 `history=[]` 硬编码传给
`MemoryService.consolidate()`，而参考实现 `MemoryConsolidationService` 是取
`recentAnswers(merchantId, 80)` 按分类过滤后一并压缩。缺陷存活的原因是当时全部
记忆测试要么 `database=None`、要么只断言"没抛异常"，没有一条检查沉淀的**输入内容**。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database
from app.models.answer import Answer
from app.models.conversation import Conversation, Message
from app.models.merchant import Merchant
from app.services import memory_service as memory_service_module
from app.services.memory_agent import MemoryAgent

MERCHANT_ID = UUID("00000000-0000-0000-0000-000000000031")
OTHER_MERCHANT_ID = UUID("00000000-0000-0000-0000-000000000032")


class _RecordingBackground:
    def __init__(self) -> None:
        self.tasks: list[tuple] = []

    def add_task(self, func, *args, **kwargs) -> None:
        self.tasks.append((func, args, kwargs))

    async def run_all(self) -> None:
        for func, args, kwargs in self.tasks:
            await func(*args, **kwargs)


async def _seed_round(
    session: AsyncSession,
    *,
    merchant_id: UUID,
    question: str,
    answer_text: str,
    category: str,
    minutes_ago: int,
) -> None:
    """直接写 ORM 并显式指定 created_at，避免同事务 now() 让排序失去意义。"""

    created = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    conversation = Conversation(id=uuid4(), merchant_id=merchant_id, title=question[:20])
    session.add(conversation)
    await session.flush()
    message = Message(
        id=uuid4(),
        merchant_id=merchant_id,
        conversation_id=conversation.id,
        role="USER",
        content=question,
        created_at=created,
    )
    session.add(message)
    await session.flush()
    payload: dict[str, Any] = {"answer": answer_text, "category": category}
    session.add(
        Answer(
            id=uuid4(),
            merchant_id=merchant_id,
            conversation_id=conversation.id,
            user_message_id=message.id,
            client_request_id=f"{merchant_id}-{question}-{minutes_ago}",
            request_digest="0" * 64,
            processing_status="SUCCEEDED",
            response_payload=payload,
            created_at=created,
        )
    )
    await session.flush()


@pytest.mark.asyncio
async def test_consolidation_receives_same_merchant_same_category_history(
    db_session: AsyncSession,  # 仅为触发 TRUNCATE 清理，本用例自开会话写数据
    integration_database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with integration_database.session() as session:
        session.add_all(
            [
                Merchant(
                    id=MERCHANT_ID,
                    merchant_code="memory-history-merchant-one",
                    display_name="记忆历史商家一",
                ),
                Merchant(
                    id=OTHER_MERCHANT_ID,
                    merchant_code="memory-history-merchant-two",
                    display_name="记忆历史商家二",
                ),
            ]
        )
        await session.flush()
        await _seed_round(
            session,
            merchant_id=MERCHANT_ID,
            question="上周成交额多少",
            answer_text="上周成交额 12 万元",
            category="TRADE",
            minutes_ago=30,
        )
        await _seed_round(
            session,
            merchant_id=MERCHANT_ID,
            question="上周退款多少",
            answer_text="上周退款 3 千元",
            category="REFUND",
            minutes_ago=20,
        )
        await _seed_round(
            session,
            merchant_id=OTHER_MERCHANT_ID,
            question="别家成交额",
            answer_text="别家成交额 99 万元",
            category="TRADE",
            minutes_ago=10,
        )
        await session.commit()

    recorded: dict[str, Any] = {}
    original = memory_service_module.MemoryService.consolidate

    async def _spy(self, **kwargs):  # type: ignore[no-untyped-def]
        recorded.update(kwargs)
        return await original(self, **kwargs)

    monkeypatch.setattr(memory_service_module.MemoryService, "consolidate", _spy)

    background = _RecordingBackground()
    agent = MemoryAgent(
        background=background,
        database=integration_database,
        settings=None,
        merchant_id=MERCHANT_ID,
        merchant_display="记忆历史商家一",
        request_id="test-request",
    )
    agent.submit(
        category="TRADE",
        question="这个月成交额呢",
        answer="这个月成交额 15 万元",
        source_tables=["orders"],
        quality_notes=[],
        suggestions=[],
        export_id=None,
    )
    await background.run_all()

    history = recorded.get("history")
    assert history, "沉淀输入的 history 不能为空——参考实现会带上同分类历史问答"
    serialized = str(history)
    assert "上周成交额 12 万元" in serialized
    assert "上周成交额多少" in serialized
    # 其他分类、其他商家一个字都不能进入沉淀输入。
    assert "退款" not in serialized
    assert "别家" not in serialized
    assert "99 万元" not in serialized
