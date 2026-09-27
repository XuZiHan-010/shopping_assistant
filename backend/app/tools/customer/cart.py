"""顾客导购的唯一写工具：`set_cart_item`（`CUSTOMER_DIRECT`，交易计划 Task 6）。

设置**绝对数量**，天然幂等；和顾客在界面加购走同一个 `CartService`，不另写一套规则。
来源闸门要求商品先在本对话里由工具返回过（D12②）；归属与在售再核一次，失败是致命错误。
售罄或购物车已满不是安全事件，作为护栏结果交还模型，由它如实转告顾客。

这里没有、也不会有下单或支付工具（PRD C2，注册表自检兜底）。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import InsufficientStockError, InvalidRequestError
from app.db.session import Database
from app.repositories.audit import AuditRepository
from app.schemas.v2.trade import MAX_LINE_QUANTITY, MAX_LINES
from app.services.v2.cart import CartService
from app.services.v2.chat_write_marker import mark_committed_write
from app.tools.customer.catalog import PRODUCT_OBJECT, on_sale_product
from app.tools.errors import GuardrailRejection
from app.tools.types import (
    ObjectRef,
    ProvenanceRef,
    ToolContext,
    ToolOutput,
    ToolRole,
    ToolSpec,
    WritePolicy,
)


class SetCartItemArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1, max_length=128)
    quantity: int = Field(
        strict=True, ge=0, le=MAX_LINE_QUANTITY, description="绝对数量，0 表示移出"
    )


def build_cart_tools(database: Database) -> tuple[ToolSpec, ...]:
    async def set_cart_item(ctx: ToolContext, args: SetCartItemArgs) -> ToolOutput:
        if args.quantity > 0:
            await on_sale_product(database, ctx, args.product_id, tool_name="set_cart_item")
        async with database.session() as session:
            await mark_committed_write(session, ctx, tool_name="set_cart_item")
            service = CartService(
                session,
                ctx=ctx.session,
                audits=AuditRepository(database),
                request_id=ctx.request_id,
            )
            try:
                cart = await service.set_quantity(args.product_id, args.quantity)
            except InsufficientStockError:
                raise GuardrailRejection(
                    code="OUT_OF_STOCK",
                    current_limit="该商品当前已售罄",
                    remediation="告知顾客已售罄，可以推荐本店其他在售商品",
                ) from None
            except InvalidRequestError:
                raise GuardrailRejection(
                    code="CART_FULL",
                    current_limit=f"购物车最多 {MAX_LINES} 种商品",
                    remediation="请顾客先移出部分商品再加购",
                ) from None
            await session.commit()
        return ToolOutput(
            payload={
                "items": [
                    {
                        "product_id": item.product_id,
                        "name": item.name,
                        "quantity": item.quantity,
                        "unit_price_cents": item.unit_price_cents,
                        "stock_band": item.stock_band.value,
                    }
                    for item in cart.items
                ],
                "subtotal_cents": cart.subtotal_cents,
            },
            summary=(
                "购物车已更新；价格仅供展示，结算以提交订单时后端重算为准，"
                "下单与支付只能由顾客在界面上操作"
            ),
            row_count=len(cart.items),
            produced=(ObjectRef(PRODUCT_OBJECT, args.product_id),),
        )

    return (
        ToolSpec(
            name="set_cart_item",
            roles=frozenset({ToolRole.CUSTOMER}),
            args_model=SetCartItemArgs,
            write_policy=WritePolicy.CUSTOMER_DIRECT,
            parallelizable=False,
            description=(
                "把本对话中查到的某个商品在购物车里的数量设为给定值（0 表示移出）。"
                "不会下单或扣款，也不占库存。"
            ),
            executor=set_cart_item,
            provenance_refs=(ProvenanceRef(arg="product_id", object_type=PRODUCT_OBJECT),),
        ),
    )
