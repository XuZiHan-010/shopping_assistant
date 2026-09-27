"""顾客售后工具只读取资格或准备预览；确认证据只由界面端点签发。"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.db.session import Database
from app.models.after_sales import AfterSale
from app.models.analytics import Order, OrderItem, Refund
from app.models.events import FulfillmentEvent
from app.schemas.v2.after_sales import AfterSaleType
from app.schemas.v2.common import yuan_to_cents
from app.services.v2.after_sale_eligibility import OrderFacts, check_eligibility
from app.services.v2.refund_calc import RefundLine, refundable
from app.tools.errors import FatalToolError, GuardrailRejection
from app.tools.types import (
    ConfirmationPreview,
    ToolContext,
    ToolOutput,
    ToolRole,
    ToolSpec,
    WritePolicy,
)


class CheckAfterSaleArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1, max_length=128)


class PrepareAfterSaleArgs(CheckAfterSaleArgs):
    after_sale_type: AfterSaleType
    order_item_ids: list[str] = Field(default_factory=list, max_length=50)
    reason: str = Field(default="", max_length=1000)


async def _facts(database: Database, ctx: ToolContext, order_id: str) -> tuple[Order, OrderFacts]:
    try:
        target = UUID(order_id)
    except ValueError:
        target = None
    async with database.session() as session:
        order = (
            await session.execute(
                select(Order).where(
                    Order.id == target,
                    Order.merchant_id == ctx.session.merchant_id,
                    Order.buyer_key == ctx.session.buyer_key,
                    Order.lifecycle_origin == "V2",
                )
            )
        ).scalar_one_or_none()
        if order is None or ctx.session.buyer_key is None:
            raise FatalToolError(
                gate="ownership",
                tool_name="check_after_sale_eligibility",
                detail="订单不存在、历史订单或不属于当前顾客",
            )
        delivered_at = await session.scalar(
            select(func.max(FulfillmentEvent.occurred_at)).where(
                FulfillmentEvent.merchant_id == ctx.session.merchant_id,
                FulfillmentEvent.subject_id == order.id,
                FulfillmentEvent.event_type == "DELIVERED",
            )
        )
        in_progress = bool(
            await session.scalar(
                select(AfterSale.id)
                .where(
                    AfterSale.merchant_id == ctx.session.merchant_id,
                    AfterSale.buyer_key == ctx.session.buyer_key,
                    AfterSale.order_id == order.id,
                    AfterSale.state != "CLOSED",
                )
                .limit(1)
            )
        )
        refunded = await session.scalar(
            select(func.coalesce(func.sum(Refund.refund_amount), 0)).where(
                Refund.merchant_id == ctx.session.merchant_id,
                Refund.order_item_id.in_(
                    select(OrderItem.id).where(OrderItem.order_id == order.id)
                ),
                Refund.refund_status == "REFUNDED",
            )
        )
        facts = OrderFacts(
            lifecycle_origin=order.lifecycle_origin,
            payment_status=order.payment_status,
            fulfillment_status=order.fulfillment_status,
            delivered_at=delivered_at,
            already_in_progress=in_progress,
            already_refunded=bool(refunded is not None and refunded >= order.paid_amount),
        )
        return order, facts


def build_after_sale_tools(database: Database) -> tuple[ToolSpec, ...]:
    async def check(ctx: ToolContext, args: CheckAfterSaleArgs) -> ToolOutput:
        _, facts = await _facts(database, ctx, args.order_id)
        from datetime import UTC, datetime

        result = check_eligibility(facts, now=datetime.now(UTC))
        return ToolOutput(
            payload={
                "allowed": result.allowed,
                "allowed_types": sorted(kind.value for kind in result.allowed_types),
                "rule_ref": result.rule_ref,
                "reason_code": result.reason_code,
            },
            summary="售后资格由后端订单事实判定；请如实解释结果，不承诺例外",
            row_count=1,
        )

    async def prepare(ctx: ToolContext, args: PrepareAfterSaleArgs) -> ConfirmationPreview:
        from datetime import UTC, datetime

        order, facts = await _facts(database, ctx, args.order_id)
        eligibility = check_eligibility(facts, now=datetime.now(UTC))
        if args.after_sale_type not in eligibility.allowed_types:
            raise GuardrailRejection(
                code=eligibility.reason_code or "AFTER_SALE_INELIGIBLE",
                current_limit=eligibility.rule_ref,
                remediation="请向顾客说明当前规则允许的售后类型",
            )
        async with database.session() as session:
            lines = list(
                (
                    await session.scalars(
                        select(OrderItem)
                        .where(
                            OrderItem.order_id == order.id,
                            OrderItem.merchant_id == ctx.session.merchant_id,
                        )
                        .order_by(OrderItem.id)
                    )
                ).all()
            )
            paid_refunds = (
                {
                    item_id: amount
                    for item_id, amount in (
                        await session.execute(
                            select(Refund.order_item_id, func.sum(Refund.refund_amount))
                            .where(
                                Refund.merchant_id == ctx.session.merchant_id,
                                Refund.order_item_id.in_([line.id for line in lines]),
                                Refund.refund_status == "REFUNDED",
                            )
                            .group_by(Refund.order_item_id)
                        )
                    ).all()
                }
                if lines
                else {}
            )
        selected = set(args.order_item_ids)
        if selected and selected != {str(line.id) for line in lines if str(line.id) in selected}:
            raise GuardrailRejection(
                code="ORDER_LINE_INVALID",
                current_limit="只能选择本订单的商品行",
                remediation="请重新选择本订单中的商品",
            )
        chosen = [line for line in lines if not selected or str(line.id) in selected]
        refundable_cents = sum(
            yuan_to_cents(
                refundable(RefundLine(line.line_total, paid_refunds.get(line.id, Decimal("0"))))
            )
            for line in chosen
        )
        if args.after_sale_type != AfterSaleType.TICKET and refundable_cents == 0:
            raise GuardrailRejection(
                code="ALREADY_REFUNDED",
                current_limit="平台演示售后规则：已退金额不可再次申请",
                remediation="请核对订单行或联系客服",
            )
        return ConfirmationPreview(
            payload={
                "order_id": str(order.id),
                "after_sale_type": args.after_sale_type.value,
                "order_item_ids": [str(line.id) for line in chosen],
                "reason": args.reason.strip(),
                "estimated_refund_cents": (
                    None if args.after_sale_type == AfterSaleType.TICKET else refundable_cents
                ),
                "rule_ref": eligibility.rule_ref,
                "next_step": "请在售后页面核对并确认，聊天中的确认不生效",
            },
            summary="已准备售后预览；顾客须在页面上核对摘要和金额后亲自确认",
        )

    return (
        ToolSpec(
            name="check_after_sale_eligibility",
            roles=frozenset({ToolRole.CUSTOMER}),
            args_model=CheckAfterSaleArgs,
            write_policy=WritePolicy.READ_ONLY,
            parallelizable=True,
            description="根据本人本店订单事实判定可申请的售后类型与依据，不创建售后单。",
            executor=check,
        ),
        ToolSpec(
            name="prepare_after_sale",
            roles=frozenset({ToolRole.CUSTOMER}),
            args_model=PrepareAfterSaleArgs,
            write_policy=WritePolicy.CUSTOMER_CONFIRMATION,
            parallelizable=False,
            description="准备售后申请预览，顾客仍须在页面核对并确认；不签发确认证据。",
            executor=prepare,
        ),
    )
