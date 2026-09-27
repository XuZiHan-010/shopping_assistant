"""商品内容工具（N3 阶段 C Task 3，PRD M4、D11，S2）。

一个只读工具 `get_product_content`、一个起草工具 `draft_content_change`。

**属性值三来源**（D11①）：商家已填（`MERCHANT_FILLED`）、商家在对话中明确给出
（`MERCHANT_STATED`）、可从描述原文直接读出（`DESCRIPTION_EXTRACT`，必须指向原文片段，D11②）。
**缺失属性列为"待补"，不由模型补全**（Q5）：起草时按品类必填清单
（`services/v2/content_completeness.py`）计算 `pending_attributes`，不接受模型自己判断"缺什么"。

**批量起草**：模型对同一批次的多个商品分别调用本工具，用同一个 `batch_key`（商家能看懂的
批次说明文字，例如"秋季女装补充资料"）而不是自己编造一个标识——`derive_batch_id()` 从
`(conversation_id, batch_key)` 确定性派生 UUID，同一对话同一批次说明总是落到同一个
`batch_id`，不同对话/不同说明互不相同（对话本身已按会话隔离商家，见 `derive_batch_id` 文档）。
"""

from __future__ import annotations

from typing import Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from app.db.session import Database
from app.models.analytics import Product
from app.schemas.v2.drafts import DraftKind
from app.services.v2.content_completeness import missing_required_attributes
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

PRODUCT_OBJECT = "PRODUCT"
_ALLOWED_SOURCE_TYPES = ("MERCHANT_FILLED", "MERCHANT_STATED", "DESCRIPTION_EXTRACT")


def derive_batch_id(*, conversation_id: str, batch_key: str) -> str:
    """从会话与批次说明确定性派生 `batch_id`；模型不直接提供标识本身。

    用 `uuid5`（基于内容的确定性 UUID，不是随机的 `uuid4`）而不是简单拼接哈希，
    是为了产出的值本身仍然是合法 `PublicId`/UUID 格式，能直接存进 `drafts.batch_id`
    这一 UUID 列，不需要额外的映射表。命名空间用固定的 URL 命名空间加前缀字符串，
    保证同输入永远同输出、跨进程重启也一致。
    """

    seed = f"borough:content-change-batch:{conversation_id}:{batch_key}"
    return str(uuid5(NAMESPACE_URL, seed))


class AttributeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(min_length=1, max_length=500)
    source_type: str = Field(pattern="^(" + "|".join(_ALLOWED_SOURCE_TYPES) + ")$")
    #: `DESCRIPTION_EXTRACT` 必须指向原文片段（D11②）；其余来源不需要。
    source_span: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _description_extract_needs_span(self) -> Self:
        if self.source_type == "DESCRIPTION_EXTRACT" and not self.source_span:
            raise ValueError("DESCRIPTION_EXTRACT 必须提供 source_span 指向描述原文片段")
        return self


class DraftContentChangeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1, max_length=128)
    attributes: dict[str, AttributeInput] = Field(min_length=1)
    short_description: str | None = Field(default=None, max_length=200)
    detail_description: str | None = Field(default=None, max_length=20000)
    #: 批量起草时同一批次的多次调用传相同值；单次起草留空。
    batch_key: str | None = Field(default=None, min_length=1, max_length=200)


class GetProductContentArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1, max_length=128)


def build_content_tools(database: Database) -> tuple[ToolSpec, ...]:
    async def get_product_content(ctx: ToolContext, args: GetProductContentArgs) -> ToolOutput:
        product = await _owned_product(database, ctx, args.product_id)
        missing = missing_required_attributes(
            category=product.category, attributes=product.attributes
        )
        return ToolOutput(
            payload={
                "product_id": str(product.id),
                "title": product.title,
                "category": product.category,
                "attributes": dict(product.attributes),
                "missing_required_attributes": sorted(missing),
                "short_description": product.short_description,
                "detail_description": product.detail_description,
                "content_version": product.content_version,
            },
            summary=f"已读取「{product.title}」的商品记录",
            row_count=1,
            produced=(ObjectRef(PRODUCT_OBJECT, str(product.id)),),
        )

    async def draft_content_change(
        ctx: ToolContext, args: DraftContentChangeArgs
    ) -> DraftProposal:
        product = await _owned_product(database, ctx, args.product_id)
        applied_attributes = {
            name: {
                "value": entry.value,
                "source_type": entry.source_type,
                "source_ref": (
                    {"span": entry.source_span} if entry.source_span is not None else None
                ),
            }
            for name, entry in args.attributes.items()
        }
        pending = sorted(
            missing_required_attributes(category=product.category, attributes=product.attributes)
            - set(args.attributes)
        )
        changes: dict[str, object] = {
            "attributes": applied_attributes,
            "base_attributes": dict(product.attributes),
            "pending_attributes": pending,
        }
        if args.short_description is not None:
            changes["short_description"] = args.short_description
        if args.detail_description is not None:
            changes["detail_description"] = args.detail_description
        if args.batch_key is not None:
            changes["batch_id"] = derive_batch_id(
                conversation_id=ctx.conversation_id, batch_key=args.batch_key
            )
        summary = f"已为「{product.title}」起草内容更新，请到审批界面确认后生效；我无法代为批准。"
        if pending:
            summary += f" 以下属性仍待补充：{'、'.join(pending)}。"
        return DraftProposal(
            target=ObjectRef(PRODUCT_OBJECT, str(product.id)),
            changes=changes,
            summary=summary,
        )

    return (
        ToolSpec(
            name="get_product_content",
            roles=frozenset({ToolRole.MERCHANT, ToolRole.MCP_READONLY}),
            args_model=GetProductContentArgs,
            write_policy=WritePolicy.READ_ONLY,
            parallelizable=True,
            description="读取商品的完整记录（属性、描述、内容版本），并标出该品类必填但缺失的属性。",
            executor=get_product_content,
        ),
        ToolSpec(
            name="draft_content_change",
            roles=frozenset({ToolRole.MERCHANT}),
            args_model=DraftContentChangeArgs,
            write_policy=WritePolicy.MERCHANT_DRAFT,
            parallelizable=False,
            description=(
                "为某个商品起草内容更新（属性、描述）。只生成待审批草稿，不会直接修改商品内容；"
                "生效必须由商家在审批界面批准。批量起草时用相同的 batch_key 让多份草稿归入同一批次"
            ),
            executor=draft_content_change,
            provenance_refs=(ProvenanceRef(arg="product_id", object_type=PRODUCT_OBJECT),),
            draft_kind=DraftKind.CONTENT_CHANGE,
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
    return FatalToolError(gate="ownership", tool_name="draft_content_change", detail=detail)
