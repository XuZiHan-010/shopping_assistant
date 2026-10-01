"""回合事务内的记忆 outbox 入队边界。"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.session import SessionContext, SessionRole
from app.memory.customer_store import CustomerMemoryStore
from app.models.conversation import Conversation, Message
from app.models.memory_v2 import MemoryExtractionJob
from app.models.session import AgentSession


async def enqueue_turn(
    session: AsyncSession, *, message: Message, ctx: SessionContext
) -> bool:
    """与用户回合写入同事务追加幂等任务；访客及关闭记忆的回合不追加。"""

    if message.role != "USER" or message.session_record_id != ctx.session_record_id:
        raise ValueError("记忆任务必须来自当前可信用户回合")
    agent = await session.get(AgentSession, ctx.session_record_id)
    conversation = await session.get(Conversation, message.conversation_id)
    if (
        agent is None or conversation is None
        or agent.merchant_id != ctx.merchant_id
        or message.merchant_id != ctx.merchant_id
        or conversation.merchant_id != ctx.merchant_id
        or agent.role != ctx.role.value
        or agent.buyer_key != ctx.buyer_key
        or conversation.surface != ("SHOP" if ctx.role is SessionRole.CUSTOMER else "MERCHANT")
    ):
        raise ValueError("记忆任务身份与已落库会话不一致")
    if ctx.role is SessionRole.CUSTOMER:
        if ctx.buyer_key is None:
            return False
        enabled = await CustomerMemoryStore(session).memory_enabled(
            merchant_id=ctx.merchant_id, buyer_key=ctx.buyer_key
        )
        if not enabled:
            return False
    row_id = await session.scalar(
        pg_insert(MemoryExtractionJob)
        .values(id=uuid4(), message_id=message.id)
        .on_conflict_do_nothing(index_elements=["message_id"])
        .returning(MemoryExtractionJob.id)
    )
    return row_id is not None
