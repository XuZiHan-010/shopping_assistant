"""顾客信号是业务事实的派生提醒；同商品同类按商家与日期聚合。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.session import SessionContext
from app.models.memory_v2 import CustomerSignal as SignalRow
from app.repositories.v2.idempotency import IdempotencyRepository
from app.schemas.v2.after_sales import AfterSaleType
from app.schemas.v2.merchant_ops import (
    CustomerSignal,
    CustomerSignalKind,
    SignalIgnoreRequest,
)
from app.services.v2.idempotency import run_idempotent

_KIND = {
    AfterSaleType.RETURN_REFUND: CustomerSignalKind.RETURN_REQUESTS,
    AfterSaleType.REFUND_ONLY: CustomerSignalKind.REFUND_REQUESTS,
    AfterSaleType.TICKET: CustomerSignalKind.SUPPORT_TICKETS,
}


def to_signal(row: SignalRow) -> CustomerSignal:
    return CustomerSignal(
        id=str(row.id), kind=row.kind, product_id=str(row.product_id) if row.product_id else None,
        product_name=row.product_name, signal_date=row.signal_date, count=row.count,
        derived_from=row.derived_from, is_ignored=row.is_ignored,
        ignore_reason=row.ignore_reason,
    )


async def derive_after_sale_signals(
    session: AsyncSession, *, merchant_id: UUID, kind: AfterSaleType,
    sale_id: UUID, products: list[tuple[UUID, str]], now: datetime,
) -> None:
    """与售后单同事务调用；相同来源重试不重复计数。"""

    signal_kind = _KIND[kind].value
    source = {"source_type": "AFTER_SALE", "source_id": str(sale_id)}
    for product_id, name in dict(products).items():
        key = f"{merchant_id}:{signal_kind}:{product_id}:{now.date()}"
        # 事务级锁将并发 upsert 串行化，唯一索引提供第二道数据库约束。
        await session.scalar(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))
        row = await session.scalar(select(SignalRow).where(
            SignalRow.merchant_id == merchant_id,
            SignalRow.kind == signal_kind,
            SignalRow.product_id == product_id,
            SignalRow.signal_date == now.date(),
        ).with_for_update())
        if row is None:
            session.add(SignalRow(
                merchant_id=merchant_id, kind=signal_kind, product_id=product_id,
                product_name=name, signal_date=now.date(), count=1,
                derived_from=[source], is_ignored=False,
            ))
        elif all(ref["source_id"] != str(sale_id) for ref in row.derived_from):
            row.count += 1
            row.product_name = name
            row.derived_from = [*row.derived_from[-49:], source]
    await session.flush()


async def derive_content_gap_signal(
    session: AsyncSession, *, merchant_id: UUID, product_id: UUID, product_name: str,
    content_version: int, now: datetime,
) -> None:
    """顾客问到某个必填属性、商家没填时调用；与售后信号共用同一张表，但形状不同。

    `CustomerSignal` Schema 校验器（`consistent_signal`）要求 `CONTENT_GAP` 的
    `derived_from` 永远恰好 1 条 `PRODUCT` 来源——不像售后信号那样累积多条来源历史，
    这里改用 `content_version` 去重：同一版本下重复提问只算一次事实（幂等），
    版本变化后如果缺口仍在，才重新计数一次，让信号如实反映"现在还缺"。
    """

    key = f"{merchant_id}:CONTENT_GAP:{product_id}:{now.date()}"
    # 与售后信号同样用事务级锁串行化并发 upsert，唯一索引提供第二道数据库约束。
    await session.scalar(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))
    row = await session.scalar(select(SignalRow).where(
        SignalRow.merchant_id == merchant_id,
        SignalRow.kind == CustomerSignalKind.CONTENT_GAP.value,
        SignalRow.product_id == product_id,
        SignalRow.signal_date == now.date(),
    ).with_for_update())
    source = {
        "source_type": "PRODUCT", "source_id": str(product_id), "content_version": content_version,
    }
    if row is None:
        session.add(SignalRow(
            merchant_id=merchant_id, kind=CustomerSignalKind.CONTENT_GAP.value,
            product_id=product_id, product_name=product_name, signal_date=now.date(),
            count=1, derived_from=[source], is_ignored=False,
        ))
    elif row.derived_from[0].get("content_version") != content_version:
        row.count += 1
        row.product_name = product_name
        row.derived_from = [source]
    await session.flush()


async def list_signals(
    session: AsyncSession, ctx: SessionContext, *, include_ignored: bool = False
) -> list[SignalRow]:
    query = select(SignalRow).where(SignalRow.merchant_id == ctx.merchant_id)
    if not include_ignored:
        query = query.where(SignalRow.is_ignored.is_(False))
    return list((await session.scalars(query.order_by(
        SignalRow.signal_date.desc(), SignalRow.id.desc()
    ))).all())


async def ignore_signal(
    session: AsyncSession, *, ctx: SessionContext, row: SignalRow,
    payload: SignalIgnoreRequest, secret: bytes,
) -> dict[str, object]:
    digest = hashlib.sha256(json.dumps(
        {"signal_id": str(row.id), "reason": payload.reason},
        sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()

    async def execute() -> dict[str, object]:
        locked = await session.scalar(select(SignalRow).where(
            SignalRow.id == row.id, SignalRow.merchant_id == ctx.merchant_id
        ).with_for_update().execution_options(populate_existing=True))
        assert locked is not None
        locked.is_ignored = True
        locked.ignore_reason = payload.reason
        await session.flush()
        return to_signal(locked).model_dump(mode="json")

    return await run_idempotent(
        repo=IdempotencyRepository(session), ctx=ctx, secret=secret,
        operation="merchant.customer_signals.ignore",
        client_request_id=payload.client_request_id,
        request_digest=digest, response_status=200, execute=execute,
    )
