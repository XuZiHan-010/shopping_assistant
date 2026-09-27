"""商家售后只读查询和经审批才能生效的决定草稿。"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from app.db.session import Database
from app.localization.locales import SupportedLocale
from app.models.after_sales import AfterSale
from app.repositories.audit import AuditRepository
from app.schemas.v2.drafts import DraftKind
from app.services.v2.after_sales import merchant_summary, sale_detail
from app.services.v2.draft_handlers.after_sale_decision import Decision
from app.tools.errors import FatalToolError
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

AFTER_SALE_OBJECT = "AFTER_SALE"


class ListAfterSalesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: str | None = Field(default=None, max_length=32)


class GetAfterSaleArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    after_sale_id: str = Field(min_length=1, max_length=128)


class DraftAfterSaleDecisionArgs(GetAfterSaleArgs):
    decision: Decision
    rule_reference: str | None = Field(default=None, min_length=1, max_length=200)
    sellable: bool | None = None
    reply_text: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def conditional_fields(self) -> DraftAfterSaleDecisionArgs:
        if self.decision is Decision.REJECT and not self.rule_reference:
            raise ValueError("拒绝售后须提供依据条款")
        if (self.decision is Decision.RECEIVE) != (self.sellable is not None):
            raise ValueError("确认收货须明确是否可售")
        return self


def build_after_sale_tools(database: Database, *, alias_secret: bytes) -> tuple[ToolSpec, ...]:
    async def list_after_sales(ctx: ToolContext, args: ListAfterSalesArgs) -> ToolOutput:
        async with database.session() as session:
            query = select(AfterSale).where(AfterSale.merchant_id == ctx.session.merchant_id)
            if args.state:
                query = query.where(AfterSale.state == args.state)
            rows = list((await session.scalars(
                query.order_by(AfterSale.created_at.desc(), AfterSale.id.desc()).limit(20)
            )).all())
            summaries = [merchant_summary(row, alias_secret=alias_secret, locale=ctx_locale(ctx))
                         for row in rows]
        return ToolOutput(
            payload={"items": [item.model_dump(mode="json") for item in summaries]},
            summary=f"本店有 {len(rows)} 条售后事项，请按状态和规则处理",
            row_count=len(rows),
            produced=tuple(ObjectRef(AFTER_SALE_OBJECT, str(row.id)) for row in rows),
        )

    async def get_after_sale(ctx: ToolContext, args: GetAfterSaleArgs) -> ToolOutput:
        record = await _owned(database, ctx, args.after_sale_id)
        await AuditRepository(database).record_event(
            merchant_id=ctx.session.merchant_id,
            event_type="AFTER_SALE_SUMMARY_VIEWED",
            resource_type="after_sale", resource_id=str(record.id),
            request_id=ctx.request_id,
            metadata={"session_record_id": str(ctx.session.session_record_id)},
        )
        async with database.session() as session:
            detail = await sale_detail(
                session, record, customer=False,
                alias_secret=alias_secret, locale=ctx_locale(ctx),
            )
        return ToolOutput(
            payload=detail.model_dump(mode="json"),
            summary="售后详情来自本店业务记录；顾客标识已脱敏",
            row_count=1,
            produced=(ObjectRef(AFTER_SALE_OBJECT, str(record.id)),),
        )

    async def draft_decision(
        ctx: ToolContext, args: DraftAfterSaleDecisionArgs
    ) -> DraftProposal:
        record = await _owned(database, ctx, args.after_sale_id)
        return DraftProposal(
            target=ObjectRef(AFTER_SALE_OBJECT, str(record.id)),
            changes={key: value for key, value in args.model_dump(exclude={"after_sale_id"}).items()
                     if value is not None},
            summary="售后决定已起草，须在审批界面批准后才会生效；退款金额由批准时后端计算。",
        )

    return (
        ToolSpec(
            name="list_after_sales", roles=frozenset({ToolRole.MERCHANT}),
            args_model=ListAfterSalesArgs, write_policy=WritePolicy.READ_ONLY,
            parallelizable=True, description="查询本店售后队列，只返回店铺级顾客别名。",
            executor=list_after_sales,
        ),
        ToolSpec(
            name="get_after_sale", roles=frozenset({ToolRole.MERCHANT}),
            args_model=GetAfterSaleArgs, write_policy=WritePolicy.READ_ONLY,
            parallelizable=True, description="查看本店售后事项、事件及脱敏随单摘要。",
            executor=get_after_sale,
            provenance_refs=(ProvenanceRef(arg="after_sale_id", object_type=AFTER_SALE_OBJECT),),
        ),
        ToolSpec(
            name="draft_after_sale_decision", roles=frozenset({ToolRole.MERCHANT}),
            args_model=DraftAfterSaleDecisionArgs, write_policy=WritePolicy.MERCHANT_DRAFT,
            parallelizable=False, description="起草售后决定供商家审批，不会直接变更状态或退款。",
            executor=draft_decision,
            provenance_refs=(ProvenanceRef(arg="after_sale_id", object_type=AFTER_SALE_OBJECT),),
            draft_kind=DraftKind.AFTER_SALE_DECISION,
        ),
    )


async def _owned(database: Database, ctx: ToolContext, raw_id: str) -> AfterSale:
    try:
        sale_id = UUID(raw_id)
    except ValueError:
        sale_id = None
    async with database.session() as session:
        sale = await session.scalar(select(AfterSale).where(
            AfterSale.id == sale_id, AfterSale.merchant_id == ctx.session.merchant_id
        ))
        if sale is not None:
            # ORM 的简单字段在会话关闭后仍可安全读取。
            return sale
    raise FatalToolError(
        gate="ownership", tool_name="get_after_sale", detail="售后事项不可用"
    )


def ctx_locale(ctx: ToolContext) -> SupportedLocale:
    # 工具上下文暂不带显示语言，按现有商家工具的中文说明口径输出。
    del ctx
    return SupportedLocale.ZH_CN
