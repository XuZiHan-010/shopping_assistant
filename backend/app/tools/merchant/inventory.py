"""库存相关的商家工具：只读告警与补货草稿。

两个工具共用同一个判定服务与同一套护栏函数，路由也用它们——这样「Agent 看到的库存」
与「工作台看到的库存」不可能因为各算各的而对不上。
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.db.session import Database
from app.models.analytics import Product
from app.repositories.v2.inventory import InventoryReadRepository
from app.schemas.v2.drafts import DraftKind, GuardrailCheckResult
from app.schemas.v2.merchant_ops import InventoryAlertKind
from app.services.v2.guardrails import check_restock, load_limits
from app.services.v2.inventory_alerts import AlertRules, alerts_for
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

#: 商家工具也要走来源闸门：模型只能为**本对话里工具返回过**的商品起草补货。
PRODUCT_OBJECT = "PRODUCT"


class InventoryAlertsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: InventoryAlertKind | None = None


class DraftRestockArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1, max_length=128)
    #: 按**增量**起草：只有增量才能在应用时与变更基数比对（D9⑧）。
    delta: int = Field(strict=True, ge=1, le=100_000)


def build_inventory_tools(database: Database, *, rules: AlertRules) -> tuple[ToolSpec, ...]:
    async def get_inventory_alerts(ctx: ToolContext, args: InventoryAlertsArgs) -> ToolOutput:
        now = datetime.now(UTC)
        async with database.session() as session:
            facts = await InventoryReadRepository(session).facts_for_merchant(
                ctx.session.merchant_id, now=now
            )
        alerts = alerts_for(facts, rules=rules, now=now, kind=args.kind)
        return ToolOutput(
            payload={"alerts": [alert.model_dump(mode="json") for alert in alerts]},
            summary=f"当前有 {len(alerts)} 条库存告警",
            row_count=len(alerts),
            # 告警里出现过的商品，模型才可以在后续调用里引用（来源闸门）。
            produced=tuple(ObjectRef(PRODUCT_OBJECT, alert.product_id) for alert in alerts),
        )

    async def restock_guardrail(ctx: ToolContext, args: DraftRestockArgs) -> None:
        checks = await _restock_checks(database, ctx, args)
        for check in checks:
            if not check.passed:
                assert check.current_limit is not None and check.remediation is not None
                raise GuardrailRejection(
                    code=check.code,
                    current_limit=check.current_limit,
                    remediation=check.remediation,
                )

    async def draft_restock(ctx: ToolContext, args: DraftRestockArgs) -> DraftProposal:
        product = await _owned_product(database, ctx, args.product_id)
        checks = await _restock_checks(database, ctx, args)
        return DraftProposal(
            target=ObjectRef(PRODUCT_OBJECT, str(product.id)),
            changes={
                "delta": args.delta,
                "guardrail_snapshot": {
                    "checks": [check.model_dump(mode="json") for check in checks],
                    "checked_at": datetime.now(UTC).isoformat(),
                },
            },
            summary=(
                f"已为「{product.title}」起草补货 +{args.delta} 件，"
                "请到审批界面确认后生效；我无法代为批准。"
            ),
        )

    return (
        ToolSpec(
            name="get_inventory_alerts",
            roles=frozenset({ToolRole.MERCHANT, ToolRole.MCP_READONLY}),
            args_model=InventoryAlertsArgs,
            write_policy=WritePolicy.READ_ONLY,
            parallelizable=True,
            description=(
                "查询本店当前的库存告警（售罄、低库存、滞销），返回精确的在库、占用与可售数量。"
            ),
            executor=get_inventory_alerts,
        ),
        ToolSpec(
            name="draft_restock",
            roles=frozenset({ToolRole.MERCHANT}),
            args_model=DraftRestockArgs,
            write_policy=WritePolicy.MERCHANT_DRAFT,
            parallelizable=False,
            description=(
                "为某个商品起草补货草稿，按增量提交。只生成待审批草稿，不会直接修改库存；"
                "生效必须由商家在审批界面批准。"
            ),
            executor=draft_restock,
            provenance_refs=(ProvenanceRef(arg="product_id", object_type=PRODUCT_OBJECT),),
            guardrail=restock_guardrail,
            draft_kind=DraftKind.RESTOCK,
        ),
    )


async def _restock_checks(
    database: Database, ctx: ToolContext, args: DraftRestockArgs
) -> list[GuardrailCheckResult]:
    async with database.session() as session:
        limits = await load_limits(session, ctx.session.merchant_id)
    return list(check_restock(args.delta, limits=limits))


async def _owned_product(database: Database, ctx: ToolContext, product_id: str) -> Product:
    """归属检查是最后一道，也是致命错误：来源闸门之外再核一次商家范围（R5）。"""

    try:
        target = UUID(product_id)
    except ValueError as exc:
        raise _forbidden(ctx, "商品标识不是合法 UUID") from exc
    async with database.session() as session:
        product = (
            await session.execute(
                select(Product).where(
                    Product.id == target, Product.merchant_id == ctx.session.merchant_id
                )
            )
        ).scalar_one_or_none()
    if product is None:
        raise _forbidden(ctx, "商品不存在或不属于当前商家")
    return product


def _forbidden(ctx: ToolContext, detail: str) -> FatalToolError:
    del ctx
    return FatalToolError(gate="ownership", tool_name="draft_restock", detail=detail)
