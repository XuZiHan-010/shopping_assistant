"""安全集「原语用例」白名单（Task 2）。

`PRIMITIVES` 是唯一可执行的入口集合：用例按名称查表调用，不能借用例文件
触发任意函数。每个原语只组合已经存在于生产代码的安全原语
（`require_owned()`、`SafeQueryService` 的受控查询白名单、`SessionRepository`
的绑定不变量），不重新发明判定逻辑——否则测的是原语作者的理解，不是生产行为。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import MerchantContext
from app.core.session import (
    SessionAlreadyBoundError,
    SessionContext,
    new_session_token,
    token_fingerprint,
)
from app.intent.models import QueryIntent
from app.models.analytics import Order, OrderItem, Product
from app.models.answer import Answer
from app.models.conversation import Conversation
from app.models.drafts import Draft
from app.models.knowledge import KnowledgeDocument
from app.models.mcp_credential import McpCredential
from app.models.provenance import ConversationProvenance
from app.repositories.audit import AuditRepository
from app.repositories.session import SessionRepository
from app.schemas.chat import AnswerMode, QuestionCategory
from app.schemas.v2.drafts import DraftKind, DraftState
from app.services.resource_scope import ScopeLookupResult, require_owned
from app.services.safe_query import SafeQueryService, UnsupportedQueryError
from app.services.v2.drafts import DRAFT_TTL

_DEFAULT_TTL_SECONDS = 86_400


@dataclass
class PrimitiveContext:
    """一次原语调用能看到的一切：真实 DB 会话、真实审计仓储、已解析的主体身份。"""

    session: AsyncSession
    audits: AuditRepository
    actor_ctx: SessionContext
    request_id: str
    args: Mapping[str, Any]
    #: 同一用例内跨 turn 共享的可写状态包，供「先埋点、再攻击」的两段式原语传递
    #: 运行时才知道的标识符（如新建行的主键）。
    state: MutableMapping[str, Any]


@dataclass(frozen=True)
class PrimitiveOutcome:
    """原语执行结果；两个字段可选——原语没有等价 HTTP 语义时留空，
    对应的 YAML 用例就不应声明 `http_status`/`error_code` 断言。
    """

    status_code: int | None = None
    code: str | None = None


class _NeverCalledRepository:
    """SQLI 原语的间谍仓储：受控查询在白名单阶段就该被拒绝，走到仓储即失败。"""

    def __getattr__(self, name: str) -> Callable[..., Any]:
        def _fail(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError(f"结构化意图应在白名单校验阶段被拒绝，但访问了仓储方法 {name}")

        return _fail


PrimitiveFn = Callable[[PrimitiveContext], Awaitable[PrimitiveOutcome]]


async def _seed_foreign_product(ctx: PrimitiveContext) -> PrimitiveOutcome:
    """CROSS-003 turn0：为「另一个商家」造一条真实存在的商品行。"""

    other_merchant_id = UUID(str(ctx.args["other_merchant_id"]))
    product_id = uuid4()
    ctx.session.add(
        Product(
            id=product_id,
            merchant_id=other_merchant_id,
            business_date=datetime.now(UTC).date(),
            product_code=f"eval-{product_id.hex}",
            title="评测探针商品",
            category="评测",
            price=Decimal("1.00"),
            status="ONLINE",
            listed_at=datetime.now(UTC),
        )
    )
    await ctx.session.flush()
    ctx.state["foreign_product_id"] = product_id
    return PrimitiveOutcome()


async def _seed_foreign_answer(ctx: PrimitiveContext) -> PrimitiveOutcome:
    """N2-CROSS：为「另一个商家」造一条真实存在的回答，供 ENDPOINT 用例的
    `{state:foreign_answer_id}` 路径占位符引用（`POST /merchant/answers/{id}/feedback`
    这类路由带路径参数，用例文件不可能预先写死一个真实主键）。
    """

    other_merchant_id = UUID(str(ctx.args["other_merchant_id"]))
    conversation_id = uuid4()
    ctx.session.add(Conversation(id=conversation_id, merchant_id=other_merchant_id))
    await ctx.session.flush()
    answer_id = uuid4()
    ctx.session.add(
        Answer(
            id=answer_id,
            merchant_id=other_merchant_id,
            conversation_id=conversation_id,
            client_request_id=f"eval-{answer_id.hex}",
            request_digest="eval-digest",
            processing_status="SUCCEEDED",
            response_payload={"answer": "评测探针回答"},
            response_locale="zh-CN",
        )
    )
    await ctx.session.flush()
    ctx.state["foreign_answer_id"] = answer_id
    return PrimitiveOutcome()


async def _seed_foreign_conversation(ctx: PrimitiveContext) -> PrimitiveOutcome:
    """会话目录用例 turn0：造一段真实存在、但**不属于当前主体**的 v2 对话。

    `surface: SHOP` 默认落在同店另一位访客名下（同店也不可见）；`surface: MERCHANT`
    需配 `other_merchant_id` 落到别家店。同时写一条来源状态，供 `no_side_effect`
    断言删除越权时它原样保留。ID 写入 `state["foreign_conversation_id"]`。
    """

    surface = str(ctx.args["surface"])
    merchant_id = UUID(str(ctx.args.get("other_merchant_id", ctx.actor_ctx.merchant_id)))
    shop = surface == "SHOP"
    owner_id = str(uuid4())
    conversation_id = uuid4()
    ctx.session.add(
        Conversation(
            id=conversation_id,
            merchant_id=merchant_id,
            title="评测探针对话",
            surface=surface,
            owner_kind="GUEST_SESSION" if shop else None,
            owner_id=owner_id if shop else None,
        )
    )
    now = datetime.now(UTC)
    ctx.session.add(
        ConversationProvenance(
            principal_kind="GUEST_SESSION",
            principal_id=owner_id,
            merchant_id=merchant_id,
            conversation_id=str(conversation_id),
            object_type="product",
            object_id=str(uuid4()),
            version=1,
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    await ctx.session.flush()
    ctx.state["foreign_conversation_id"] = conversation_id
    return PrimitiveOutcome()


async def _seed_foreign_draft(ctx: PrimitiveContext) -> PrimitiveOutcome:
    """N2-APPROVAL：为「另一个商家」造一条真实的 `STAGED` 补货草稿与目标商品。

    草稿必须真实存在，否则「跨店批准被拒」可能只是因为草稿不存在——
    那样测到的是 404 路径，不是租户边界（R5 要求两者对外不可区分，
    所以用例必须确保被拒的是真实存在、只是不属于攻击者的那条）。
    """

    other_merchant_id = UUID(str(ctx.args["other_merchant_id"]))
    product_id = uuid4()
    ctx.session.add(
        Product(
            id=product_id,
            merchant_id=other_merchant_id,
            business_date=datetime.now(UTC).date(),
            product_code=f"eval-{product_id.hex}",
            title="评测探针商品",
            category="评测",
            price=Decimal("1.00"),
            status="ONLINE",
            listed_at=datetime.now(UTC),
            stock_on_hand=12,
        )
    )
    await ctx.session.flush()
    draft_id = uuid4()
    ctx.session.add(
        Draft(
            id=draft_id,
            merchant_id=other_merchant_id,
            kind=DraftKind.RESTOCK.value,
            title="评测探针补货草稿",
            target_type="PRODUCT",
            target_id=product_id,
            target_version=12,
            draft_version=1,
            state=DraftState.STAGED.value,
            payload={"delta": 60, "base_on_hand": 12},
            guardrail_snapshot={"checks": []},
            created_by="AGENT",
            expires_at=datetime.now(UTC) + DRAFT_TTL,
        )
    )
    await ctx.session.flush()
    ctx.state["foreign_draft_id"] = draft_id
    ctx.state["foreign_product_id"] = product_id
    return PrimitiveOutcome()


async def _access_foreign_product(ctx: PrimitiveContext) -> PrimitiveOutcome:
    """CROSS-003 turn1：用 `require_owned()` 本尊尝试读取别的商家的商品。"""

    product_id: UUID = ctx.state["foreign_product_id"]

    async def fetch() -> ScopeLookupResult[Product]:
        row = (
            await ctx.session.execute(select(Product).where(Product.id == product_id))
        ).scalar_one_or_none()
        if row is None:
            return ScopeLookupResult(resource=None, target_exists=False)
        if row.merchant_id != ctx.actor_ctx.merchant_id:
            return ScopeLookupResult(resource=None, target_exists=True)
        return ScopeLookupResult(resource=row, target_exists=True)

    try:
        await require_owned(
            fetch,
            ctx=ctx.actor_ctx,
            audits=ctx.audits,
            resource_type="product",
            resource_id=str(product_id),
            request_id=ctx.request_id,
        )
    except AppError as error:
        return PrimitiveOutcome(status_code=error.status_code, code=error.code.value)
    raise AssertionError("期望 require_owned() 拒绝跨商家访问，但放行了")


async def _expect_unsupported_query(intent: QueryIntent) -> PrimitiveOutcome:
    """SQLI 系列共用：受控查询服务必须在触碰仓储前拒绝注入意图。

    `UnsupportedQueryError` 目前没有直接挂在任何 v2 HTTP 路由上（结构化查询
    意图只由 LLM 产出，N1 没有客户端可直接提交的入口），这里用 422/
    `INVALID_REQUEST` 只是复用 `InvalidRequestError`「语法正确但违反受控
    业务边界」的既有语义分类，不代表存在一条已接线的 HTTP 路由。
    """

    service = SafeQueryService(_NeverCalledRepository(), business_timezone="Asia/Shanghai")  # type: ignore[arg-type]
    try:
        await service.execute(
            MerchantContext(merchant_id=uuid4()),
            intent,
            now=datetime.now(UTC),
        )
    except UnsupportedQueryError:
        return PrimitiveOutcome(status_code=422, code="INVALID_REQUEST")
    raise AssertionError("期望受控查询白名单拒绝注入意图，但没有拒绝")


async def _reject_dimension_injection(_ctx: PrimitiveContext) -> PrimitiveOutcome:
    intent = QueryIntent(
        answer_mode=AnswerMode.METRIC,
        category=QuestionCategory.TRADE,
        metric="gmv",
        dimensions=["'; DROP TABLE orders; --"],
    )
    return await _expect_unsupported_query(intent)


async def _reject_filter_key_injection(_ctx: PrimitiveContext) -> PrimitiveOutcome:
    intent = QueryIntent(
        answer_mode=AnswerMode.METRIC,
        category=QuestionCategory.TRADE,
        metric="gmv",
        filters={"1=1 UNION SELECT * FROM merchants --": "x"},
    )
    return await _expect_unsupported_query(intent)


async def _reject_filter_value_injection(_ctx: PrimitiveContext) -> PrimitiveOutcome:
    intent = QueryIntent(
        answer_mode=AnswerMode.METRIC,
        category=QuestionCategory.TRADE,
        metric="gmv",
        filters={"date": "2026-01-01'; DROP TABLE orders; --"},
    )
    return await _expect_unsupported_query(intent)


async def _setup_bound_guest(ctx: PrimitiveContext) -> PrimitiveOutcome:
    """BUYERKEY-003 turn0：正常绑定一次，作为「已绑定」前置状态。"""

    repo = SessionRepository(ctx.session, default_ttl_seconds=_DEFAULT_TTL_SECONDS)
    _token, guest = await repo.issue_customer_guest(
        merchant_id=ctx.actor_ctx.merchant_id,
        shop_slug=ctx.actor_ctx.shop_slug or "",
    )
    bound = await repo.bind_demo_customer(guest, buyer_key=str(ctx.args["buyer_key"]))
    ctx.state["bound_ctx"] = bound
    return PrimitiveOutcome()


async def _seed_foreign_order(ctx: PrimitiveContext) -> PrimitiveOutcome:
    """交易用例 turn0：造一笔真实存在、但**不属于当前顾客**的 v2 待支付订单。

    默认同店另一顾客（`other_buyer_key`）；给了 `other_merchant_id` 就落到别家店。
    订单 ID 写入 `state["foreign_order_id"]`，供后续 HTTP turn 读 / 付 / 取消。
    """

    merchant_id = UUID(str(ctx.args.get("other_merchant_id", ctx.actor_ctx.merchant_id)))
    now = datetime.now(UTC)
    product_id, order_id = uuid4(), uuid4()
    ctx.session.add(
        Product(
            id=product_id,
            merchant_id=merchant_id,
            business_date=now.date(),
            product_code=f"eval-{product_id.hex}",
            title="评测探针商品",
            category="评测",
            price=Decimal("1.00"),
            status="ONLINE",
            listed_at=now,
            stock_on_hand=5,
            stock_reserved=1,
        )
    )
    await ctx.session.flush()
    ctx.session.add(
        Order(
            id=order_id,
            merchant_id=merchant_id,
            business_date=now.date(),
            order_no=f"EVAL{order_id.hex[:16]}",
            buyer_key=str(ctx.args.get("other_buyer_key", "eval-other-buyer")),
            order_status="CREATED",
            total_amount=Decimal("1.00"),
            paid_amount=Decimal("0.00"),
            placed_at=now,
            payment_status="PENDING",
            fulfillment_status="NOT_SHIPPED",
            lifecycle_origin="V2",
        )
    )
    await ctx.session.flush()
    ctx.session.add(
        OrderItem(
            merchant_id=merchant_id,
            business_date=now.date(),
            order_id=order_id,
            product_id=product_id,
            quantity=1,
            item_amount=Decimal("1.00"),
            unit_price=Decimal("1.00"),
            discount_amount=Decimal("0.00"),
            line_total=Decimal("1.00"),
            title_snapshot="评测探针商品",
        )
    )
    await ctx.session.flush()
    ctx.state["foreign_order_id"] = order_id
    return PrimitiveOutcome()


async def _seed_injected_product(ctx: PrimitiveContext) -> PrimitiveOutcome:
    """注入用例 turn0：本店在售商品，描述与属性里夹带指令（商品描述入口，A11 / SEC8）。

    商品 ID 写入 `state["injected_product_id"]`。断言只看后果：这段文字无论如何被读到，
    订单、价格、草稿都不会因此改变——防线在工具面与闸门，不在模型是否听话。
    """

    now = datetime.now(UTC)
    product_id = uuid4()
    injected = str(ctx.args["text"])
    ctx.session.add(
        Product(
            id=product_id,
            merchant_id=ctx.actor_ctx.merchant_id,
            business_date=now.date(),
            product_code=f"eval-inj-{product_id.hex}",
            title="评测注入商品",
            category="评测",
            price=Decimal("99.00"),
            status="ONLINE",
            listed_at=now,
            stock_on_hand=10,
            detail_description=injected,
            attributes={"说明": {"value": injected[:2000], "source": "MERCHANT"}},
        )
    )
    await ctx.session.flush()
    ctx.state["injected_product_id"] = product_id
    return PrimitiveOutcome()


async def _seed_injected_knowledge(ctx: PrimitiveContext) -> PrimitiveOutcome:
    """注入用例 turn0：顾客可见路径下的规则文档正文夹带指令（知识文档入口）。"""

    path = f"业务/退货/业务规则/评测注入-{uuid4().hex[:8]}.md"
    ctx.session.add(
        KnowledgeDocument(
            category="REFUND",
            title="评测注入退货规则",
            content=str(ctx.args["text"]),
            source="eval",
            source_path=path,
            is_complete=True,
            source_locale="zh-CN",
        )
    )
    await ctx.session.flush()
    ctx.state["injected_document_path"] = path
    return PrimitiveOutcome()


async def _bind_actor(ctx: PrimitiveContext) -> PrimitiveOutcome:
    """交易用例 turn0：把当前顾客 actor 自己的会话原地绑定到演示身份。

    与 `setup_bound_guest` 不同，它不另签会话：后续 HTTP 请求沿用同一个 `X-Session-Id`，
    服务端解析出的就是已绑定顾客，用来打「要求已绑定」的订单端点。
    """

    repo = SessionRepository(ctx.session, default_ttl_seconds=_DEFAULT_TTL_SECONDS)
    await repo.bind_demo_customer(ctx.actor_ctx, buyer_key=str(ctx.args["buyer_key"]))
    return PrimitiveOutcome()


async def _attempt_conflicting_rebind(ctx: PrimitiveContext) -> PrimitiveOutcome:
    """BUYERKEY-003 turn1：已绑定会话试图改绑另一个 `buyer_key`。

    本原语只验证仓储层不变量（拒绝 + `buyer_key` 不变），不返回
    `status_code`/`code`，对应 YAML 不声明 HTTP 断言。生产服务现已将冲突转换为
    409 `SESSION_ALREADY_BOUND`，该传输行为另由 API 会话路由回归测试覆盖。
    """

    repo = SessionRepository(ctx.session, default_ttl_seconds=_DEFAULT_TTL_SECONDS)
    bound_ctx: SessionContext = ctx.state["bound_ctx"]
    try:
        await repo.bind_demo_customer(bound_ctx, buyer_key=str(ctx.args["attacker_buyer_key"]))
    except SessionAlreadyBoundError:
        return PrimitiveOutcome()
    raise AssertionError("期望改绑不同 buyer_key 被仓储层拒绝，但绑定成功了")


async def _resolve_shop_slugs(ctx: PrimitiveContext) -> PrimitiveOutcome:
    """CATALOG turn0：给公开目录用例提供本店与一个必然不存在的店铺 slug。

    本店 slug 取自已验证的顾客会话，不在用例文件里写死；未知 slug 每次随机，
    保证它不可能碰巧是某个真实店铺。
    """

    ctx.state["own_shop_slug"] = ctx.actor_ctx.shop_slug or ""
    ctx.state["unknown_shop_slug"] = f"eval-no-such-shop-{uuid4().hex[:12]}"
    return PrimitiveOutcome()


async def _mint_merchant_orders_cursor(ctx: PrimitiveContext) -> PrimitiveOutcome:
    """W3-004 turn0：签发一枚绑定 `payment_status` 筛选的真实商家订单列表游标。

    与生产路由完全同一签名逻辑（`merchant_cursor_scope` + `CursorCodec`），只是绕开
    HTTP 往返直接调用——现有 YAML 用例结构没有「捕获上一条响应字段」的机制，
    只能在原语里现算一枚合法游标，再让后续 HTTP turn 用不同筛选重放它。
    密钥用与 `security_app` 同一套开发期回退值：测试从不配置 `EXPORT_SIGNING_SECRET`。
    绑定的 `locale` 固定为 `en-US`，调用方 YAML 用例的 `locale` 字段必须同为 `en-US`，
    否则后续 HTTP turn 解析出的语言与游标绑定不一致，会被误判为跨查询形状复用。
    """

    from app.api.dependencies import _DEV_BUYER_ALIAS_SECRET
    from app.api.v2_deps import _DEV_SIGNING_SECRET, merchant_cursor_scope
    from app.localization.locales import SupportedLocale
    from app.services.v2.cursor import CursorCodec

    payment_status = str(ctx.args.get("payment_status", "PAID"))
    scope = merchant_cursor_scope(
        ctx.actor_ctx,
        endpoint="merchant.orders.list",
        resource="ORDER",
        filters={
            "payment_status": payment_status,
            "fulfillment_status": None,
            "after_sale_status": None,
        },
        locale=SupportedLocale.EN_US,
        limit=1,
        secret=_DEV_BUYER_ALIAS_SECRET.encode(),
    )
    codec = CursorCodec(secret=_DEV_SIGNING_SECRET)
    ctx.state["merchant_orders_cursor"] = codec.encode(
        scope, key=("anchor",), now=datetime.now(UTC)
    )
    return PrimitiveOutcome()


async def _mint_newest_products_cursor(ctx: PrimitiveContext) -> PrimitiveOutcome:
    """WS：签发真实 newest 商品游标，供 popular 查询验证筛选绑定。"""

    from app.api.routes.v2.shop_catalog import _public_scope
    from app.api.v2_deps import _DEV_SIGNING_SECRET
    from app.localization.locales import SupportedLocale
    from app.services.v2.cursor import CursorCodec

    scope = _public_scope(
        endpoint="shop.products.list",
        resource="PRODUCT",
        merchant_id=ctx.actor_ctx.merchant_id,
        locale=SupportedLocale.ZH_CN,
        limit=1,
        filters={"sort": "newest"},
    )
    ctx.state["newest_products_cursor"] = CursorCodec(secret=_DEV_SIGNING_SECRET).encode(
        scope, key=("anchor",), now=datetime.now(UTC)
    )
    return PrimitiveOutcome()


async def _seed_mcp_credential(ctx: PrimitiveContext) -> PrimitiveOutcome:
    """S8 turn0：为当前商家 actor 写入一枚 MCP 凭证（可选已撤销），原值只放进用例 state。

    库里照生产口径只存指纹（复用会话凭证原语）；撤销与否只体现在 `revoked_at`，
    校验是否立即失效交给后续 HTTP turn 打生产入口来判定，原语本身不做判断。
    """

    now = datetime.now(UTC)
    token = new_session_token()
    ctx.session.add(
        McpCredential(
            token_fingerprint=token_fingerprint(token),
            merchant_id=ctx.actor_ctx.merchant_id,
            scopes=["query_metrics"],
            label="security-eval",
            created_at=now,
            expires_at=now + timedelta(hours=1),
            revoked_at=now if ctx.args.get("revoked") else None,
        )
    )
    await ctx.session.flush()
    ctx.state[str(ctx.args["state_key"])] = token
    return PrimitiveOutcome()


PRIMITIVES: dict[str, PrimitiveFn] = {
    "resource_scope.resolve_shop_slugs": _resolve_shop_slugs,
    "resource_scope.seed_foreign_product": _seed_foreign_product,
    "resource_scope.access_foreign_product": _access_foreign_product,
    "resource_scope.seed_foreign_answer": _seed_foreign_answer,
    "resource_scope.seed_foreign_draft": _seed_foreign_draft,
    "resource_scope.seed_foreign_conversation": _seed_foreign_conversation,
    "safe_query.reject_dimension_injection": _reject_dimension_injection,
    "safe_query.reject_filter_key_injection": _reject_filter_key_injection,
    "safe_query.reject_filter_value_injection": _reject_filter_value_injection,
    "session.setup_bound_guest": _setup_bound_guest,
    "session.bind_actor": _bind_actor,
    "trade.seed_foreign_order": _seed_foreign_order,
    "injection.seed_product_description": _seed_injected_product,
    "injection.seed_knowledge_document": _seed_injected_knowledge,
    "session.attempt_conflicting_rebind": _attempt_conflicting_rebind,
    "orders.mint_merchant_orders_cursor": _mint_merchant_orders_cursor,
    "catalog.mint_newest_products_cursor": _mint_newest_products_cursor,
    "mcp.seed_credential": _seed_mcp_credential,
}


async def run_primitive(name: str, ctx: PrimitiveContext) -> PrimitiveOutcome:
    try:
        fn = PRIMITIVES[name]
    except KeyError as error:
        raise KeyError(f"原语 {name} 未在白名单登记，用例不能借此调用任意函数") from error
    return await fn(ctx)
