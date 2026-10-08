"""与 Chat 写工具同事务保存的请求级提交标记。

Chat 回执在另一事务提交。若回执提交失败，标记仍能阻止同一请求重跑模型与写工具。
标记只保存主体摘要、请求摘要和固定工具标识，不保存顾客标识或工具参数。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import IdempotencyKeyReusedError, RequestInProgressError
from app.models.idempotency import IdempotencyRecord
from app.repositories.v2.idempotency import IdempotencyRepository
from app.tools.types import ToolContext

WRITE_OPERATION = "chat.write_effect"


async def find_committed_write(
    session: AsyncSession, ctx: ToolContext
) -> IdempotencyRecord | None:
    if ctx.client_request_id is None:
        return None
    assert ctx.principal_digest is not None and ctx.request_digest is not None
    record = await IdempotencyRepository(session).find(
        role=ctx.session.role.value,
        principal_digest=ctx.principal_digest,
        merchant_id=ctx.session.merchant_id,
        operation=WRITE_OPERATION,
        client_request_id=ctx.client_request_id,
    )
    if record is not None and record.request_digest != ctx.request_digest:
        raise IdempotencyKeyReusedError
    return record


async def mark_committed_write(
    session: AsyncSession, ctx: ToolContext, *, tool_name: str
) -> None:
    """必须在业务写入的同一 Session、同一次 commit 中调用。"""

    if ctx.client_request_id is None:
        return
    assert ctx.principal_digest is not None and ctx.request_digest is not None
    repo = IdempotencyRepository(session)
    existing = await find_committed_write(session, ctx)
    if existing is not None:
        stored_attempt_id = (
            existing.response_body.get("attempt_id") if existing.response_body else None
        )
        if stored_attempt_id != ctx.request_id:
            raise RequestInProgressError
        return
    candidate = IdempotencyRecord(
        role=ctx.session.role.value,
        principal_digest=ctx.principal_digest,
        merchant_id=ctx.session.merchant_id,
        operation=WRITE_OPERATION,
        client_request_id=ctx.client_request_id,
        request_digest=ctx.request_digest,
    )
    created = await repo.try_create_processing(candidate)
    if created is None:
        raise RequestInProgressError
    await repo.mark_succeeded(
        created,
        response_status=200,
        response_body={
            "attempt_id": ctx.request_id,
            "tool_name": tool_name,
            "call_id": ctx.tool_call_id or "direct",
        },
    )
