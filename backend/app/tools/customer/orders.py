"""顾客只读订单工具：只从可信会话解析本店本人订单。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.db.session import Database
from app.models.analytics import Order
from app.services.v2.orders import (
    fulfillment_events,
    order_items,
    order_uuid,
    owned_order_filter,
    pay_by,
)
from app.tools.errors import FatalToolError
from app.tools.types import ToolContext, ToolOutput, ToolRole, ToolSpec, WritePolicy


class GetMyOrderArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1, max_length=128)


def _reject() -> FatalToolError:
    return FatalToolError(
        gate="ownership",
        tool_name="get_my_order",
        detail="订单不存在、历史订单或不属于当前顾客",
    )


def build_order_tools(database: Database) -> tuple[ToolSpec, ...]:
    async def get_my_order(ctx: ToolContext, args: GetMyOrderArgs) -> ToolOutput:
        target = order_uuid(args.order_id)
        if ctx.session.buyer_key is None or target is None:
            raise _reject()
        async with database.session() as session:
            order = (
                await session.execute(select(Order).where(*owned_order_filter(ctx.session, target)))
            ).scalar_one_or_none()
            if order is None:
                raise _reject()
            items = await order_items(session, order.id)
            events = await fulfillment_events(session, order)
        return ToolOutput(
            payload={
                "payment_status": order.payment_status,
                "fulfillment_status": order.fulfillment_status,
                "after_sale_status": order.after_sale_status,
                "pay_by": pay_by(order).isoformat(),
                "items": [
                    {"name": item.title_snapshot or "—", "quantity": item.quantity}
                    for item in items
                ],
                "recent_events": [
                    {
                        "event_type": event.event_type.value,
                        "occurred_at": event.occurred_at.isoformat(),
                    }
                    for event in events[-5:]
                ],
            },
            summary="订单状态与履约事件来自后端订单事实；请如实转述，不推测送达时间",
            row_count=1,
        )

    return (
        ToolSpec(
            name="get_my_order",
            roles=frozenset({ToolRole.CUSTOMER}),
            args_model=GetMyOrderArgs,
            write_policy=WritePolicy.READ_ONLY,
            parallelizable=True,
            description="查询本人本店一笔订单的支付、履约状态与最近履约事件；只读，不能修改订单。",
            executor=get_my_order,
        ),
    )
