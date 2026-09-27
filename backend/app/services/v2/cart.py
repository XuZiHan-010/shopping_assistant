"""顾客购物车（PRD C3、D13，契约 §8.10）与绑定时的访客购物车合并（D7⑥、E9）。

购物车**不占库存**：这里只读 `stock_available` 来判断「是否售罄」与展示档位，
从不写库存列。价格只作展示，提交订单时由结账服务按当时商品重算（D12③）。

主体只从已验证会话解析：已绑定顾客按 `(merchant_id, buyer_key)`，访客按内部会话记录 ID。
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import ColumnElement, and_, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InsufficientStockError, InvalidRequestError, ProductNotInScopeError
from app.core.session import SessionContext
from app.models.analytics import Product
from app.models.cart import CartLine
from app.repositories.protocols import AuditRepositoryProtocol
from app.repositories.v2.catalog import ON_SALE_STATUS
from app.schemas.v2.common import yuan_to_cents
from app.schemas.v2.shop_session import StockBand
from app.schemas.v2.trade import MAX_LINE_QUANTITY, MAX_LINES, CartItem, CartResponse
from app.services.v2.catalog import ALLOWED_IMAGE_HOSTS, trusted_image
from app.services.v2.stock_tier import stock_band

SCOPE_VIOLATION_EVENT: Final = "RESOURCE_SCOPE_VIOLATION"


def parse_product_id(raw: str) -> UUID | None:
    try:
        return UUID(raw)
    except ValueError:
        return None


def owner_filter(ctx: SessionContext) -> ColumnElement[bool]:
    """购物车行的主体条件；已绑定顾客永远不会读到访客行，反之亦然。"""

    if ctx.buyer_key is not None:
        return and_(CartLine.merchant_id == ctx.merchant_id, CartLine.buyer_key == ctx.buyer_key)
    return and_(
        CartLine.merchant_id == ctx.merchant_id,
        CartLine.guest_session_id == ctx.session_record_id,
    )


def line_band(product: Product) -> StockBand:
    """下架商品不静默删行：以「无货」档位展示，提交订单时再明确报 DELISTED。"""

    if product.status != ON_SALE_STATUS:
        return StockBand.OUT_OF_STOCK
    return stock_band(
        available=product.stock_available, low_stock_threshold=product.low_stock_threshold
    )


class CartService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        ctx: SessionContext,
        audits: AuditRepositoryProtocol,
        request_id: str,
        allowed_image_hosts: Collection[str] = ALLOWED_IMAGE_HOSTS,
    ) -> None:
        self._session = session
        self._ctx = ctx
        self._audits = audits
        self._request_id = request_id
        self._allowed_image_hosts = allowed_image_hosts

    async def lines(self) -> list[tuple[CartLine, Product]]:
        """按加入时间升序；结账与展示共用这一次读取。"""

        result = await self._session.execute(
            select(CartLine, Product)
            .join(Product, Product.id == CartLine.product_id)
            .where(owner_filter(self._ctx), Product.merchant_id == self._ctx.merchant_id)
            .order_by(CartLine.created_at, CartLine.id)
        )
        return [(line, product) for line, product in result.tuples().all()]

    async def view(self) -> CartResponse:
        items = [
            CartItem(
                product_id=str(product.id),
                name=product.title,
                image_url=trusted_image(product.image_url, self._allowed_image_hosts),
                quantity=line.quantity,
                unit_price_cents=yuan_to_cents(product.price),
                line_total_cents=yuan_to_cents(product.price) * line.quantity,
                stock_band=line_band(product),
            )
            for line, product in await self.lines()
        ]
        return CartResponse(items=items, subtotal_cents=sum(i.line_total_cents for i in items))

    async def set_quantity(self, raw_product_id: str, quantity: int) -> CartResponse:
        """设置绝对数量；`0` 等价删除且不做商品探测（与 DELETE 同一路径）。"""

        if quantity == 0:
            return await self.remove(raw_product_id)
        product = await self._on_sale_product(raw_product_id)
        if product.stock_available <= 0:
            raise InsufficientStockError
        await self._ensure_capacity(product.id)
        owner: dict[str, Any] = (
            {"buyer_key": self._ctx.buyer_key}
            if self._ctx.buyer_key is not None
            else {"guest_session_id": self._ctx.session_record_id}
        )
        statement = insert(CartLine).values(
            merchant_id=self._ctx.merchant_id, product_id=product.id, quantity=quantity, **owner
        )
        refresh = {"quantity": quantity, "updated_at": func.now()}
        if self._ctx.buyer_key is not None:
            upsert = statement.on_conflict_do_update(
                index_elements=["merchant_id", "buyer_key", "product_id"],
                index_where=CartLine.buyer_key.is_not(None),
                set_=refresh,
            )
        else:
            upsert = statement.on_conflict_do_update(
                index_elements=["guest_session_id", "product_id"],
                index_where=CartLine.guest_session_id.is_not(None),
                set_=refresh,
            )
        await self._session.execute(upsert)
        return await self.view()

    async def remove(self, raw_product_id: str) -> CartResponse:
        """天然幂等：行不存在、商品不存在、标识不合法都同样返回当前购物车。"""

        product_id = parse_product_id(raw_product_id)
        if product_id is not None:
            await self._session.execute(
                delete(CartLine).where(owner_filter(self._ctx), CartLine.product_id == product_id)
            )
        return await self.view()

    async def _on_sale_product(self, raw_product_id: str) -> Product:
        """一次固定形状查询：不存在、非本店、不可售对外同一个 403，并写审计（R5）。"""

        product_id = parse_product_id(raw_product_id)
        product = None
        if product_id is not None:
            product = (
                await self._session.execute(
                    select(Product).where(
                        Product.id == product_id,
                        Product.merchant_id == self._ctx.merchant_id,
                        Product.status == ON_SALE_STATUS,
                    )
                )
            ).scalar_one_or_none()
        if product is None:
            await self._audits.record_event(
                merchant_id=self._ctx.merchant_id,
                event_type=SCOPE_VIOLATION_EVENT,
                resource_type="product",
                resource_id=raw_product_id,
                request_id=self._request_id,
                metadata={"operation": "cart.set_item"},
            )
            raise ProductNotInScopeError
        return product

    async def _ensure_capacity(self, product_id: UUID) -> None:
        existing = await self._session.scalar(
            select(func.count())
            .select_from(CartLine)
            .where(owner_filter(self._ctx), CartLine.product_id == product_id)
        )
        if existing:
            return
        count = await self._session.scalar(
            select(func.count()).select_from(CartLine).where(owner_filter(self._ctx))
        )
        if (count or 0) >= MAX_LINES:
            raise InvalidRequestError("购物车最多 50 种商品")


class DatabaseCartMerge:
    """`CartMergePort` 的生产实现（PRD C3 合并规则，E9）。

    在调用方传入的绑定事务里执行，任何失败都随绑定一起回滚：
    同商品相加并按 99 截顶；已下架或售罄的访客行剔除；超 50 行按加入时间保留最新 50 行；
    访客行合并后全部清空。合并不校验库存数量——可售量在提交订单时重新校验。
    """

    async def merge_guest_into_buyer(
        self,
        *,
        session: AsyncSession,
        merchant_id: UUID,
        buyer_key: str,
        guest_session_id: UUID,
    ) -> bool:
        adjusted = False
        buyer_lines = {
            line.product_id: line
            for line in (
                await session.scalars(
                    select(CartLine)
                    .where(CartLine.merchant_id == merchant_id, CartLine.buyer_key == buyer_key)
                    .with_for_update()
                )
            ).all()
        }
        guest_rows = (
            (
                await session.execute(
                    select(CartLine, Product)
                    .join(Product, Product.id == CartLine.product_id)
                    .where(
                        CartLine.merchant_id == merchant_id,
                        CartLine.guest_session_id == guest_session_id,
                    )
                    .with_for_update(of=CartLine)
                )
            )
            .tuples()
            .all()
        )

        for guest_line, product in guest_rows:
            sellable = product.status == ON_SALE_STATUS and product.stock_available > 0
            existing = buyer_lines.get(guest_line.product_id)
            if not sellable:
                adjusted = True
                await session.delete(guest_line)
            elif existing is None:
                # 原行转给顾客：保留「加入时间」，截断时按它判断新旧。
                guest_line.guest_session_id = None
                guest_line.buyer_key = buyer_key
                buyer_lines[guest_line.product_id] = guest_line
            else:
                total = existing.quantity + guest_line.quantity
                if total > MAX_LINE_QUANTITY:
                    adjusted = True
                    total = MAX_LINE_QUANTITY
                existing.quantity = total
                existing.created_at = _latest(existing.created_at, guest_line.created_at)
                await session.delete(guest_line)
        await session.flush()

        if len(buyer_lines) > MAX_LINES:
            adjusted = True
            newest_first = sorted(
                buyer_lines.values(), key=lambda line: (line.created_at, str(line.id)), reverse=True
            )
            for line in newest_first[MAX_LINES:]:
                await session.delete(line)
            await session.flush()
        return adjusted


def _latest(first: datetime, second: datetime) -> datetime:
    return max(first, second)
