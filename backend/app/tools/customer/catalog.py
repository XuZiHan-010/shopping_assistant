"""顾客导购的只读工具：商品搜索、商品详情、店铺与平台规则（PRD C2，交易计划 Task 6）。

交给模型的商品数据与公开浏览同一个口径：价格（整数分）与库存**档位**，永远没有库存数量或阈值（D5）。
属性缺失时明确给出「缺失」，不给空字符串——空串会被模型读成「这个商品没有该属性」。
店铺与平台规则只从白名单路径段下的文档里取，内部流程文档不会因为关键词碰巧命中而漏给顾客。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import or_, select

from app.db.session import Database
from app.knowledge.retrieval import KnowledgeRetrieval
from app.models.analytics import Product
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.v2.catalog import ON_SALE_STATUS
from app.schemas.chat import QuestionCategory
from app.schemas.v2.common import yuan_to_cents
from app.services.v2.content_completeness import required_attributes_for
from app.services.v2.customer_signals import derive_content_gap_signal
from app.services.v2.stock_tier import stock_band
from app.tools.customer.search_terms import has_english, zh_search_terms
from app.tools.errors import FatalToolError
from app.tools.types import ObjectRef, ToolContext, ToolOutput, ToolRole, ToolSpec, WritePolicy

PRODUCT_OBJECT: Final = "PRODUCT"
MISSING: Final = "缺失"
_MAX_TERMS: Final = 5
_MAX_EXCERPT: Final = 2000
_MAX_BUNDLE_ITEMS: Final = 20
#: 英文关键词没有结果时给模型的说明：没搜到不等于没有，先换中文关键词再下结论。
_NO_MATCH_ENGLISH: Final = (
    "本店没有找到匹配的在售商品。本店商品名称为中文，这个英文关键词没有对应的检索词；"
    "请换成中文关键词（如「鞋」「围巾」）再搜一次，确认没有后再告诉顾客。"
)

PolicyTopic = Literal["RETURN_REFUND", "SHIPPING", "INVOICE", "GENERAL"]
#: 顾客可见的知识文档路径段（PRD C2「引用本店与平台规则文档」）；其余团队文档一律不给顾客。
CUSTOMER_VISIBLE_SEGMENTS: Final = ("平台规则", "退货", "售后")
_TOPIC_QUERY: Final[Mapping[str, tuple[QuestionCategory, tuple[str, ...]]]] = {
    "RETURN_REFUND": (QuestionCategory.REFUND, ()),
    "SHIPPING": (QuestionCategory.PLATFORM_RULE, ("运费", "物流", "发货", "配送", "shipping")),
    "INVOICE": (QuestionCategory.PLATFORM_RULE, ("发票", "invoice")),
    "GENERAL": (QuestionCategory.PLATFORM_RULE, ()),
}


class SearchProductsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=100, description="商品关键词，可含空格分隔的多个词")
    limit: int = Field(default=5, ge=1, le=10)


class GetProductArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1, max_length=128)
    attributes: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="顾客关心的属性名；商家没提供的属性会明确返回「缺失」",
    )


class GetProductAttributeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1, max_length=128)
    attribute: str = Field(min_length=1, max_length=100)


class EstimateBundleTotalArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_ids: list[str] = Field(
        min_length=1,
        max_length=_MAX_BUNDLE_ITEMS,
        description="要合计的商品标识（取自搜索或详情结果），每件按一件计；只能是本店在售商品",
    )
    budget_yuan: int | None = Field(
        default=None, ge=1, le=10_000_000, description="顾客说的预算（元，整数）；不传则只返回合计"
    )

    @field_validator("product_ids")
    @classmethod
    def unique_ids(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("商品标识不得重复；同一商品多件请让顾客在购物车里调整数量")
        return value


class ShopPolicyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: PolicyTopic


def product_card(product: Product) -> dict[str, Any]:
    """模型可见的商品摘要：与顾客端公开模型同口径，只有档位，没有数量。"""

    return {
        "product_id": str(product.id),
        "name": product.title,
        "short_description": product.short_description or MISSING,
        "price_cents": yuan_to_cents(product.price),
        # 给模型直接引用的写法：只给分的时候，模型会把价格写成「39900 分」（2026-10-07 真实评测）。
        "price": _yuan(product.price),
        "stock_band": stock_band(
            available=product.stock_available, low_stock_threshold=product.low_stock_threshold
        ).value,
    }


def _yuan(amount: Decimal) -> str:
    """模型直接引用的金额写法。"""

    return f"¥{amount:.2f}"


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _attribute_values(raw: Mapping[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    for name, entry in raw.items():
        if isinstance(entry, Mapping) and isinstance(entry.get("value"), str) and entry["value"]:
            values[name] = entry["value"]
    return values


def build_catalog_tools(database: Database) -> tuple[ToolSpec, ...]:
    async def search_products(ctx: ToolContext, args: SearchProductsArgs) -> ToolOutput:
        terms = args.query.split()[:_MAX_TERMS]
        if not terms:
            return ToolOutput(
                payload={"products": []}, summary="关键词为空，请给出商品关键词", row_count=0
            )
        # 搜索是字面包含匹配：英文关键词与中文口语说法（「外套」「裤子」）经固定词表展开成
        # 商品名称里实际出现的字样，与原词一起匹配（QLT-N5-007、QLT-N5-003）。
        expansions = zh_search_terms(args.query)
        conditions = [
            column.ilike(f"%{_escape_like(term)}%", escape="\\")
            for term in terms
            for column in (Product.title, Product.short_description)
        ] + [
            column.ilike(f"%{_escape_like(term)}%", escape="\\")
            for term in expansions
            for column in (Product.title, Product.short_description, Product.category)
        ]
        async with database.session() as session:
            products = (
                await session.scalars(
                    select(Product)
                    .where(
                        Product.merchant_id == ctx.session.merchant_id,
                        Product.status == ON_SALE_STATUS,
                        or_(*conditions),
                    )
                    .order_by(Product.created_at.desc(), Product.id.desc())
                    .limit(args.limit)
                )
            ).all()
        cards = [product_card(product) for product in products]
        if cards:
            summary = f"本店找到 {len(cards)} 件在售商品"
        elif has_english(args.query):
            summary = _NO_MATCH_ENGLISH
        else:
            summary = "本店没有找到匹配的在售商品"
        return ToolOutput(
            payload={"products": cards},
            summary=summary,
            row_count=len(cards),
            produced=tuple(ObjectRef(PRODUCT_OBJECT, card["product_id"]) for card in cards),
        )

    async def get_product(ctx: ToolContext, args: GetProductArgs) -> ToolOutput:
        product = await on_sale_product(database, ctx, args.product_id, tool_name="get_product")
        attributes = _attribute_values(product.attributes)
        for name in args.attributes:
            attributes.setdefault(name, MISSING)
        return ToolOutput(
            payload={
                **product_card(product),
                "description": product.detail_description or MISSING,
                "attributes": attributes,
                "content_version": product.content_version,
            },
            summary=f"商品「{product.title}」的详情；标为「{MISSING}」的信息商家没有提供，不要推测",
            row_count=1,
            produced=(ObjectRef(PRODUCT_OBJECT, str(product.id)),),
        )

    async def get_product_attribute(ctx: ToolContext, args: GetProductAttributeArgs) -> ToolOutput:
        try:
            target = UUID(args.product_id)
        except ValueError:
            raise _forbidden("get_product_attribute", "商品标识不是合法 UUID") from None
        async with database.session() as session:
            product = (
                await session.execute(
                    select(Product).where(
                        Product.id == target,
                        Product.merchant_id == ctx.session.merchant_id,
                        Product.status == ON_SALE_STATUS,
                    )
                )
            ).scalar_one_or_none()
            if product is None:
                raise _forbidden("get_product_attribute", "商品不属于本店或不在售")
            values = _attribute_values(product.attributes)
            value = values.get(args.attribute)
            required = required_attributes_for(product.category)
            if value is None and args.attribute in required:
                await derive_content_gap_signal(
                    session, merchant_id=product.merchant_id, product_id=product.id,
                    product_name=product.title, content_version=product.content_version,
                    now=datetime.now(UTC),
                )
            await session.commit()
        return ToolOutput(
            payload={"attribute": args.attribute, "value": value},
            summary=(
                f"「{args.attribute}」的值是「{value}」"
                if value is not None
                else f"商家没有提供「{args.attribute}」，不要替商家编造"
            ),
            row_count=1,
            produced=(ObjectRef(PRODUCT_OBJECT, str(product.id)),),
        )

    async def estimate_bundle_total(ctx: ToolContext, args: EstimateBundleTotalArgs) -> ToolOutput:
        """一组商品的标价合计与预算差额。加法由后端做：模型不许自己算（R4），而顾客问
        「一千元以内搭一套」时必须有人算（2026-10-10 真实复测 QLT-N5-003）。"""

        try:
            targets = [UUID(product_id) for product_id in args.product_ids]
        except ValueError:
            raise _forbidden("estimate_bundle_total", "商品标识不是合法 UUID") from None
        async with database.session() as session:
            rows = (
                await session.scalars(
                    select(Product).where(
                        Product.id.in_(targets),
                        Product.merchant_id == ctx.session.merchant_id,
                        Product.status == ON_SALE_STATUS,
                    )
                )
            ).all()
        by_id = {product.id: product for product in rows}
        if len(by_id) != len(targets):
            # 与 get_product 同一口径：非本店、下架、不存在对外是同一个中性 403（R5）。
            raise _forbidden("estimate_bundle_total", "商品不存在、不属于本店或不在售")
        products = [by_id[target] for target in targets]  # 按顾客给的顺序
        total = sum((product.price for product in products), Decimal("0"))
        payload: dict[str, Any] = {
            "items": [
                {
                    "product_id": str(product.id),
                    "name": product.title,
                    "price_cents": yuan_to_cents(product.price),
                    "price": _yuan(product.price),
                }
                for product in products
            ],
            "item_count": len(products),
            "total_cents": yuan_to_cents(total),
            "total": _yuan(total),
        }
        summary = f"这 {len(products)} 件商品各一件的标价合计为 {_yuan(total)}"
        if args.budget_yuan is not None:
            budget = Decimal(args.budget_yuan)
            within = total <= budget
            difference = _yuan(abs(budget - total))
            payload.update(
                budget=_yuan(budget),
                within_budget=within,
                **({"remaining": difference} if within else {"over_by": difference}),
            )
            summary += (
                f"，在 {_yuan(budget)} 预算内，还剩 {difference}"
                if within
                else f"，超出 {_yuan(budget)} 预算 {difference}"
            )
        return ToolOutput(
            payload=payload,
            summary=summary + "。未含优惠券与运费；结算以顾客提交订单时后端重算为准。",
            row_count=len(products),
            produced=tuple(ObjectRef(PRODUCT_OBJECT, str(product.id)) for product in products),
        )

    async def get_shop_policy(ctx: ToolContext, args: ShopPolicyArgs) -> ToolOutput:
        del ctx  # 规则文档对所有店铺一致；本店规则摘要尚无数据来源（见 Task 1 台账）。
        category, keywords = _TOPIC_QUERY[args.topic]
        async with database.session() as session:
            result = await KnowledgeRetrieval(KnowledgeRepository(session)).load_domain(
                category, keywords
            )
        hits = [hit for hit in result.hits if _customer_visible(hit.source_path)]
        # 成文规则排在「待补充」的骨架文档之前（稳定排序，同类内保持检索顺序）。
        hits.sort(key=lambda hit: not hit.is_complete)
        documents = [
            {
                "title": hit.title,
                "citation": hit.source_path,
                "excerpt": hit.content[:_MAX_EXCERPT],
                "is_complete": hit.is_complete,
            }
            for hit in hits
        ]
        return ToolOutput(
            payload={"found": bool(documents), "documents": documents},
            summary=(
                "以下是可引用的规则原文，回答时注明出处，不要承诺规则之外的事"
                if documents
                else "没有找到相关规则文档，请如实告知顾客暂无可引用的规则"
            ),
            row_count=len(documents),
        )

    return (
        ToolSpec(
            name="search_products",
            roles=frozenset({ToolRole.CUSTOMER}),
            args_model=SearchProductsArgs,
            write_policy=WritePolicy.READ_ONLY,
            parallelizable=True,
            description=(
                "按关键词搜索本店在售商品，返回名称、价格与库存档位。"
                "商品名称为中文；常见的英文商品词（如 shoes、scarf）会自动对应到中文。"
            ),
            executor=search_products,
        ),
        ToolSpec(
            name="get_product",
            roles=frozenset({ToolRole.CUSTOMER}),
            args_model=GetProductArgs,
            write_policy=WritePolicy.READ_ONLY,
            parallelizable=True,
            description="读取本店某个在售商品的详情与属性；商家未提供的属性返回「缺失」。",
            executor=get_product,
        ),
        ToolSpec(
            name="get_product_attribute",
            roles=frozenset({ToolRole.CUSTOMER}),
            args_model=GetProductAttributeArgs,
            write_policy=WritePolicy.READ_ONLY,
            parallelizable=False,
            description="查询商品某个具体属性的值；商家未提供时返回空值，不要替商家编造。",
            executor=get_product_attribute,
        ),
        ToolSpec(
            name="estimate_bundle_total",
            roles=frozenset({ToolRole.CUSTOMER}),
            args_model=EstimateBundleTotalArgs,
            write_policy=WritePolicy.READ_ONLY,
            parallelizable=True,
            description=(
                "计算一组本店在售商品（各一件）的标价合计；传入预算时一并返回是否在预算内与差额。"
                "回答里需要合计或预算判断时用它，不要自己做加减。"
            ),
            executor=estimate_bundle_total,
        ),
        ToolSpec(
            name="get_shop_policy",
            roles=frozenset({ToolRole.CUSTOMER}),
            args_model=ShopPolicyArgs,
            write_policy=WritePolicy.READ_ONLY,
            parallelizable=True,
            description="查询退换货、运费、发票等店铺与平台规则原文，并给出可引用的出处。",
            executor=get_shop_policy,
        ),
    )


def _customer_visible(source_path: str) -> bool:
    return any(segment in source_path for segment in CUSTOMER_VISIBLE_SEGMENTS)


async def on_sale_product(
    database: Database, ctx: ToolContext, product_id: str, *, tool_name: str
) -> Product:
    """归属与在售检查是致命错误：非本店、下架、不存在、非法标识对外同一个中性 403（R5）。"""

    try:
        target = UUID(product_id)
    except ValueError:
        raise _forbidden(tool_name, "商品标识不是合法 UUID") from None
    async with database.session() as session:
        product = (
            await session.execute(
                select(Product).where(
                    Product.id == target,
                    Product.merchant_id == ctx.session.merchant_id,
                    Product.status == ON_SALE_STATUS,
                )
            )
        ).scalar_one_or_none()
    if product is None:
        raise _forbidden(tool_name, "商品不存在、不属于本店或不在售")
    return product


def _forbidden(tool_name: str, detail: str) -> FatalToolError:
    return FatalToolError(gate="ownership", tool_name=tool_name, detail=detail)
