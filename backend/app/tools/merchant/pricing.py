"""定价与促销工具（N3 阶段 C Task 4，PRD M6）。

三个工具：`list_coupons`（`READ_ONLY`）、`draft_price_change`、`draft_coupon`
（均为 `MERCHANT_DRAFT`）。护栏预检复用 `check_price_change`/`check_coupon`，
应用时的复检在 `PriceChangeHandler`/`CouponHandler` 里再跑一次同一函数（D9②）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from app.db.session import Database
from app.models.analytics import Product
from app.models.promotion import Coupon
from app.schemas.v2.drafts import DraftKind
from app.services.v2.coupons import CouponRow, to_coupon_summary
from app.services.v2.guardrails import check_coupon, check_price_change, load_limits
from app.tools.errors import FatalToolError, GuardrailRejection
from app.tools.types import (
    DraftProposal,
    ObjectRef,
    ProvenanceRef,
    ToolContext,
    ToolOutput,
    ToolRole,
    ToolSpec,
    WritePolicy,
)

PRODUCT_OBJECT = "PRODUCT"


class ListCouponsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DraftPriceChangeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1, max_length=128)
    new_price: Decimal = Field(gt=0, le=Decimal("999999999999.99"))


class DraftCouponArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(pattern=r"^(FULL_REDUCTION|DISCOUNT)$")
    threshold_amount: Decimal | None = Field(default=None, ge=0)
    discount_amount: Decimal | None = Field(default=None, gt=0)
    discount_rate: Decimal | None = Field(default=None, gt=0, le=1)
    product_ids: list[str] = Field(default_factory=list)
    starts_at: datetime
    ends_at: datetime

    @model_validator(mode="after")
    def _shape_matches_kind(self) -> Self:
        if self.ends_at <= self.starts_at:
            raise ValueError("促销必须有晚于开始时间的结束日期")
        if self.kind == "FULL_REDUCTION" and self.discount_amount is None:
            raise ValueError("满减券需要 discount_amount")
        if self.kind == "DISCOUNT" and self.discount_rate is None:
            raise ValueError("折扣券需要 discount_rate")
        return self


def build_pricing_tools(database: Database) -> tuple[ToolSpec, ...]:
    async def list_coupons(ctx: ToolContext, args: ListCouponsArgs) -> ToolOutput:
        del args
        async with database.session() as session:
            rows = (
                (
                    await session.execute(
                        select(Coupon)
                        .where(Coupon.merchant_id == ctx.session.merchant_id)
                        .order_by(Coupon.created_at.desc(), Coupon.id.desc())
                    )
                )
                .scalars()
                .all()
            )
        summaries = [
            to_coupon_summary(
                CouponRow(
                    id=str(row.id),
                    name=row.name,
                    kind=row.kind,
                    threshold_amount=row.threshold_amount,
                    discount_amount=row.discount_amount,
                    discount_rate=row.discount_rate,
                    product_ids=list(row.product_ids),
                    starts_at=row.starts_at,
                    ends_at=row.ends_at,
                    state=row.state,
                    created_at=row.created_at,
                )
            ).model_dump(mode="json")
            for row in rows
        ]
        return ToolOutput(
            payload={"coupons": summaries},
            summary=f"本店当前共有 {len(summaries)} 张券",
            row_count=len(summaries),
        )

    async def price_change_guardrail(ctx: ToolContext, args: DraftPriceChangeArgs) -> None:
        product = await _owned_product(database, ctx, args.product_id)
        async with database.session() as session:
            limits = await load_limits(session, ctx.session.merchant_id)
        checks = check_price_change(
            current_price=product.price, new_price=args.new_price, limits=limits
        )
        for check in checks:
            if not check.passed:
                assert check.current_limit is not None and check.remediation is not None
                raise GuardrailRejection(
                    code=check.code,
                    current_limit=check.current_limit,
                    remediation=check.remediation,
                )

    async def draft_price_change(ctx: ToolContext, args: DraftPriceChangeArgs) -> DraftProposal:
        product = await _owned_product(database, ctx, args.product_id)
        async with database.session() as session:
            limits = await load_limits(session, ctx.session.merchant_id)
        checks = check_price_change(
            current_price=product.price, new_price=args.new_price, limits=limits
        )
        return DraftProposal(
            target=ObjectRef(PRODUCT_OBJECT, str(product.id)),
            changes={
                "new_price": str(args.new_price),
                "guardrail_snapshot": {
                    "checks": [check.model_dump(mode="json") for check in checks],
                    "checked_at": datetime.now(UTC).isoformat(),
                },
            },
            summary=(
                f"已为「{product.title}」起草调价至 {args.new_price} 元，"
                "请到审批界面确认后生效；我无法代为批准。"
            ),
        )

    async def coupon_guardrail(ctx: ToolContext, args: DraftCouponArgs) -> None:
        async with database.session() as session:
            limits = await load_limits(session, ctx.session.merchant_id)
        checks = check_coupon(
            discount_rate=args.discount_rate if args.kind == "DISCOUNT" else None,
            threshold_amount=args.threshold_amount if args.kind == "FULL_REDUCTION" else None,
            discount_amount=args.discount_amount if args.kind == "FULL_REDUCTION" else None,
            limits=limits,
        )
        for check in checks:
            if not check.passed:
                assert check.current_limit is not None and check.remediation is not None
                raise GuardrailRejection(
                    code=check.code,
                    current_limit=check.current_limit,
                    remediation=check.remediation,
                )

    async def draft_coupon(ctx: ToolContext, args: DraftCouponArgs) -> DraftProposal:
        async with database.session() as session:
            limits = await load_limits(session, ctx.session.merchant_id)
        checks = check_coupon(
            discount_rate=args.discount_rate if args.kind == "DISCOUNT" else None,
            threshold_amount=args.threshold_amount if args.kind == "FULL_REDUCTION" else None,
            discount_amount=args.discount_amount if args.kind == "FULL_REDUCTION" else None,
            limits=limits,
        )
        return DraftProposal(
            # 券是新建对象，此刻还没有真实 id；用占位符，真正的 id 由
            # `DatabaseDraftSink._stage_coupon()` 预先分配（草稿暂存层的职责，见 D9）。
            target=ObjectRef("COUPON", "PENDING"),
            changes={
                "name": args.name,
                "kind": args.kind,
                "threshold_amount": str(args.threshold_amount) if args.threshold_amount else None,
                "discount_amount": str(args.discount_amount) if args.discount_amount else None,
                "discount_rate": str(args.discount_rate) if args.discount_rate else None,
                "scope": "ALL" if not args.product_ids else "PRODUCTS",
                "product_ids": args.product_ids,
                "starts_at": args.starts_at.isoformat(),
                "ends_at": args.ends_at.isoformat(),
                "guardrail_snapshot": {
                    "checks": [check.model_dump(mode="json") for check in checks],
                    "checked_at": datetime.now(UTC).isoformat(),
                },
            },
            summary=f"已起草促销券「{args.name}」，请到审批界面确认后生效；我无法代为批准。",
        )

    return (
        ToolSpec(
            name="list_coupons",
            roles=frozenset({ToolRole.MERCHANT, ToolRole.MCP_READONLY}),
            args_model=ListCouponsArgs,
            write_policy=WritePolicy.READ_ONLY,
            parallelizable=True,
            description="列出本店当前全部促销券及其生效状态。",
            executor=list_coupons,
        ),
        ToolSpec(
            name="draft_price_change",
            roles=frozenset({ToolRole.MERCHANT}),
            args_model=DraftPriceChangeArgs,
            write_policy=WritePolicy.MERCHANT_DRAFT,
            parallelizable=False,
            description=(
                "为某个商品起草调价草稿。只生成待审批草稿，不会直接修改售价；"
                "生效必须由商家在审批界面批准。"
            ),
            executor=draft_price_change,
            provenance_refs=(ProvenanceRef(arg="product_id", object_type=PRODUCT_OBJECT),),
            guardrail=price_change_guardrail,
            draft_kind=DraftKind.PRICE_CHANGE,
        ),
        ToolSpec(
            name="draft_coupon",
            roles=frozenset({ToolRole.MERCHANT}),
            args_model=DraftCouponArgs,
            write_policy=WritePolicy.MERCHANT_DRAFT,
            parallelizable=False,
            description=(
                "起草一张满减券或折扣券。只生成待审批草稿，不会直接生效；"
                "生效必须由商家在审批界面批准。"
            ),
            executor=draft_coupon,
            guardrail=coupon_guardrail,
            draft_kind=DraftKind.COUPON,
        ),
    )


async def _owned_product(database: Database, ctx: ToolContext, product_id: str) -> Product:
    try:
        target = UUID(product_id)
    except ValueError as exc:
        raise _forbidden("商品标识不是合法 UUID") from exc
    async with database.session() as session:
        product = (
            await session.execute(
                select(Product).where(
                    Product.id == target, Product.merchant_id == ctx.session.merchant_id
                )
            )
        ).scalar_one_or_none()
    if product is None:
        raise _forbidden("商品不存在或不属于当前商家")
    return product


def _forbidden(detail: str) -> FatalToolError:
    return FatalToolError(gate="ownership", tool_name="draft_price_change", detail=detail)
