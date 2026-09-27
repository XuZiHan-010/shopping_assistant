"""结账事务（PRD C4、§7.4，契约 §8.10.2–§8.10.4）——交易计划的核心。

在调用方的**同一个数据库事务**里完成全部步骤，任一步失败抛出异常，由调用方整体回滚：

```text
幂等查询 → 读购物车与商品当前价格/状态 → 券适用性 → 逐行条件更新占库（按商品 ID 排序加锁）
→ 逐行舍入的价格快照 → 插入 orders / order_items → 履约事件「已下单」、库存事件「订单占用」
→ 清空已下单的购物车 → 幂等记录写终态
```

第 2 步的条件更新是禁止超卖的应用层防线；`ck_products_reserved_le_on_hand` 是数据库层底线。
金额只由本模块计算（D13）：请求里只有 `client_request_id` 与可选的 `coupon_id`。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any, Final
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InsufficientStockError, InvalidRequestError, ProductNotInScopeError
from app.core.session import SessionContext
from app.domain.order_status_mapping import to_legacy_status
from app.models.analytics import Order, OrderItem, Product
from app.models.cart import CartLine
from app.models.events import FulfillmentEvent, InventoryEvent
from app.models.promotion import Coupon
from app.repositories.v2.catalog import ON_SALE_STATUS
from app.repositories.v2.idempotency import IdempotencyRepository
from app.schemas.v2.common import cents_to_yuan, yuan_to_cents
from app.schemas.v2.shop_session import StockBand
from app.schemas.v2.trade import UnavailableItemDetail
from app.services.v2.cart import owner_filter
from app.services.v2.coupons import CouponNotApplicableError, CouponRow, allocate_discounts
from app.services.v2.idempotency import run_idempotent
from app.services.v2.orders import SOURCE_TIMEZONE, V2_ORIGIN, to_order_detail
from app.services.v2.stock_tier import stock_band

CREATE_OPERATION: Final = "shop.orders.create"
ORDER_PLACED: Final = "ORDER_PLACED"
ORDER_RESERVE: Final = "ORDER_RESERVE"
_BUSINESS_ZONE: Final = ZoneInfo(SOURCE_TIMEZONE)


@dataclass(frozen=True)
class _Line:
    product: Product
    quantity: int

    @property
    def gross_cents(self) -> int:
        return yuan_to_cents(self.product.price) * self.quantity


def request_digest(coupon_id: str | None) -> str:
    """幂等摘要只取规范化后的业务输入（§8.7.3）。"""

    return sha256(f"shop.orders.create\u0000{coupon_id or ''}".encode()).hexdigest()


async def place_order(
    session: AsyncSession,
    *,
    ctx: SessionContext,
    coupon_id: str | None,
    client_request_id: str,
    principal_secret: bytes,
    now: datetime,
) -> dict[str, Any]:
    """同一主体同一 `client_request_id` 重放第一次的响应；不提交事务，提交由调用方决定。"""

    return await run_idempotent(
        repo=IdempotencyRepository(session),
        ctx=ctx,
        secret=principal_secret,
        operation=CREATE_OPERATION,
        client_request_id=client_request_id,
        request_digest=request_digest(coupon_id),
        response_status=201,
        execute=lambda: _create(session, ctx=ctx, coupon_id=coupon_id, now=now),
    )


async def _create(
    session: AsyncSession, *, ctx: SessionContext, coupon_id: str | None, now: datetime
) -> dict[str, Any]:
    assert ctx.buyer_key is not None, "下单要求已绑定顾客，由路由依赖保证"
    lines = await _cart_lines(session, ctx)
    if not lines:
        raise InvalidRequestError("购物车为空", details=[{"field": "cart", "reason": "EMPTY"}])

    # 1. 重新读取当前价格与状态，不沿用购物车或对话里的旧值（D12③）。
    delisted = [line for line in lines if line.product.status != ON_SALE_STATUS]
    if delisted:
        raise ProductNotInScopeError(details=[_unavailable(line, "DELISTED") for line in delisted])
    coupon = await _coupon(session, ctx, coupon_id)
    discounts = _discounts(coupon, lines, now=now)

    # 2. 逐行条件更新占库。按商品 ID 排序取行锁，两单交叉购买同两件商品时不会互相死锁。
    unavailable: list[dict[str, Any]] = []
    for line in sorted(lines, key=lambda item: str(item.product.id)):
        reserved = await session.execute(
            update(Product)
            .where(
                Product.id == line.product.id,
                Product.merchant_id == ctx.merchant_id,
                Product.status == ON_SALE_STATUS,
                Product.stock_on_hand - Product.stock_reserved >= line.quantity,
            )
            .values(stock_reserved=Product.stock_reserved + line.quantity)
        )
        if reserved.rowcount == 0:  # type: ignore[attr-defined]
            unavailable.append(await _stock_failure(session, line))
    if unavailable:
        # 不静默调整：整单拒绝并逐条列出；调用方回滚会撤销本循环里已经成功的占用。
        raise InsufficientStockError(details=unavailable)

    # 3–4. 价格快照：先逐行舍入到分（券分摊已按行完成），再对行结果求和。
    order_id = uuid4()
    totals = [line.gross_cents - discount for line, discount in zip(lines, discounts, strict=True)]
    total_cents = sum(totals)
    business_date = now.astimezone(_BUSINESS_ZONE).date()
    order = Order(
        id=order_id,
        merchant_id=ctx.merchant_id,
        business_date=business_date,
        order_no=f"V2{now.astimezone(_BUSINESS_ZONE):%Y%m%d}{order_id.hex[:12].upper()}",
        buyer_key=ctx.buyer_key,
        order_status=to_legacy_status("PENDING", "NOT_SHIPPED", None),
        total_amount=cents_to_yuan(total_cents),
        paid_amount=Decimal("0.00"),
        placed_at=now,
        paid_at=None,
        payment_status="PENDING",
        fulfillment_status="NOT_SHIPPED",
        after_sale_status="NONE",
        close_reason=None,
        lifecycle_origin=V2_ORIGIN,
        source_timezone=SOURCE_TIMEZONE,
        coupon_id=UUID(coupon.id) if coupon is not None else None,
        closed_at=None,
    )
    session.add(order)
    await session.flush()
    items = [
        OrderItem(
            merchant_id=ctx.merchant_id,
            business_date=business_date,
            order_id=order_id,
            product_id=line.product.id,
            quantity=line.quantity,
            unit_price=line.product.price,
            discount_amount=cents_to_yuan(discount),
            line_total=cents_to_yuan(line_total),
            item_amount=cents_to_yuan(line_total),
            title_snapshot=line.product.title,
        )
        for line, discount, line_total in zip(lines, discounts, totals, strict=True)
    ]
    session.add_all(items)

    # 5. 事件账本与投影同一事务（§7.1 不变量 1、§7.4 不变量 3）。
    session.add(
        FulfillmentEvent(
            merchant_id=ctx.merchant_id,
            subject_id=order_id,
            event_type=ORDER_PLACED,
            occurred_at=now,
            dedupe_key=f"{ORDER_PLACED}:{order_id}",
            payload={"origin": V2_ORIGIN, "source_timezone": SOURCE_TIMEZONE},
        )
    )
    session.add_all(
        InventoryEvent(
            merchant_id=ctx.merchant_id,
            subject_id=line.product.id,
            event_type=ORDER_RESERVE,
            occurred_at=now,
            dedupe_key=f"{ORDER_RESERVE}:{order_id}:{line.product.id}",
            payload={"order_id": str(order_id), "quantity": line.quantity},
        )
        for line in lines
    )

    # 已下单的购物车在同一事务里清空；回滚时购物车原样保留。
    await session.execute(delete(CartLine).where(owner_filter(ctx)))
    await session.flush()
    return to_order_detail(order, items).model_dump(mode="json")


async def _cart_lines(session: AsyncSession, ctx: SessionContext) -> list[_Line]:
    result = await session.execute(
        select(CartLine, Product)
        .join(Product, Product.id == CartLine.product_id)
        .where(owner_filter(ctx), Product.merchant_id == ctx.merchant_id)
        .order_by(CartLine.created_at, CartLine.id)
    )
    return [_Line(product=product, quantity=line.quantity) for line, product in result.tuples()]


async def _coupon(
    session: AsyncSession, ctx: SessionContext, coupon_id: str | None
) -> CouponRow | None:
    """券不存在、非本店、标识不合法与「不可用」同一个 422，不泄露券是否存在。"""

    if coupon_id is None:
        return None
    try:
        target = UUID(coupon_id)
    except ValueError:
        raise _coupon_unavailable() from None
    coupon = (
        await session.execute(
            select(Coupon).where(Coupon.id == target, Coupon.merchant_id == ctx.merchant_id)
        )
    ).scalar_one_or_none()
    if coupon is None:
        raise _coupon_unavailable()
    return CouponRow(
        id=str(coupon.id),
        name=coupon.name,
        kind=coupon.kind,
        threshold_amount=coupon.threshold_amount,
        discount_amount=coupon.discount_amount,
        discount_rate=coupon.discount_rate,
        product_ids=list(coupon.product_ids),
        starts_at=coupon.starts_at,
        ends_at=coupon.ends_at,
        state=coupon.state,
        created_at=coupon.created_at,
    )


def _discounts(coupon: CouponRow | None, lines: list[_Line], *, now: datetime) -> list[int]:
    if coupon is None:
        return [0] * len(lines)
    try:
        return allocate_discounts(
            coupon, [(str(line.product.id), line.gross_cents) for line in lines], now=now
        )
    except CouponNotApplicableError:
        raise _coupon_unavailable() from None


def _coupon_unavailable() -> InvalidRequestError:
    return InvalidRequestError(
        "优惠券不可用", details=[{"field": "coupon_id", "reason": "COUPON_UNAVAILABLE"}]
    )


async def _stock_failure(session: AsyncSession, line: _Line) -> dict[str, Any]:
    """条件更新失败后重读当前档位；只给档位与原因，不给任何数量。"""

    current = await session.get(Product, line.product.id, populate_existing=True)
    assert current is not None
    band = stock_band(
        available=current.stock_available, low_stock_threshold=current.low_stock_threshold
    )
    reason = "OUT_OF_STOCK" if band is StockBand.OUT_OF_STOCK else "INSUFFICIENT_STOCK"
    return _unavailable(_Line(product=current, quantity=line.quantity), reason, band=band)


def _unavailable(line: _Line, reason: str, *, band: StockBand | None = None) -> dict[str, Any]:
    return UnavailableItemDetail(
        product_id=str(line.product.id),
        reason=reason,
        stock_band=band or StockBand.OUT_OF_STOCK,
    ).model_dump(mode="json")
