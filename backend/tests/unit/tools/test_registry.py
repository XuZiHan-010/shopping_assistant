"""工具注册表自检与按角色出工具面（§6.9，N2 Task 1）。

自检在注册时执行：错误的工具定义应该让服务起不来，而不是在某个顾客提问时才暴露。
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict

from app.core.session import SessionRole
from app.schemas.v2.drafts import DraftKind
from app.tools.registry import ToolRegistrationError, ToolRegistry
from app.tools.types import (
    ConfirmationPreview,
    DraftProposal,
    ObjectRef,
    ProvenanceRef,
    ToolContext,
    ToolOutput,
    ToolRole,
    ToolSpec,
    WritePolicy,
)


class QueryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    q: str


class ProductArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: str


class MerchantIdArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    merchant_id: str
    q: str


class BuyerKeyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    buyer_key: str
    q: str


class NestedScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    merchant_id: str


class NestedIdentityArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: NestedScope


class LooseArgs(BaseModel):
    q: str


async def read_exec(ctx: ToolContext, args: QueryArgs) -> ToolOutput:
    return ToolOutput(payload={"q": args.q}, summary="ok")


async def product_exec(ctx: ToolContext, args: ProductArgs) -> ToolOutput:
    return ToolOutput(payload={}, summary="ok")


async def draft_exec(ctx: ToolContext, args: ProductArgs) -> DraftProposal:
    return DraftProposal(
        target=ObjectRef("PRODUCT", args.product_id), changes={}, summary="restock"
    )


async def preview_exec(ctx: ToolContext, args: ProductArgs) -> ConfirmationPreview:
    return ConfirmationPreview(payload={}, summary="preview")


async def untyped_exec(ctx, args):  # type: ignore[no-untyped-def]
    return ToolOutput(payload={}, summary="ok")


async def no_context_exec(args: QueryArgs) -> ToolOutput:
    return ToolOutput(payload={}, summary="ok")


def sync_exec(ctx: ToolContext, args: QueryArgs) -> ToolOutput:
    return ToolOutput(payload={}, summary="ok")


def spec(**overrides: object) -> ToolSpec:
    values: dict[str, object] = {
        "name": "search_products",
        "roles": frozenset({ToolRole.CUSTOMER}),
        "args_model": QueryArgs,
        "write_policy": WritePolicy.READ_ONLY,
        "parallelizable": True,
        "description": "搜索本店商品",
        "executor": read_exec,
    }
    values.update(overrides)
    return ToolSpec(**values)  # type: ignore[arg-type]


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry()


def test_registering_tool_with_merchant_id_arg_fails(registry: ToolRegistry) -> None:
    """§6.9：merchant_id 由注册表注入，出现在签名里即为契约错误。"""

    with pytest.raises(ToolRegistrationError, match="merchant_id"):
        registry.register(spec(name="bad", args_model=MerchantIdArgs))


def test_registering_tool_with_buyer_key_arg_fails(registry: ToolRegistry) -> None:
    with pytest.raises(ToolRegistrationError, match="buyer_key"):
        registry.register(spec(name="bad", args_model=BuyerKeyArgs))


def test_identity_field_in_nested_model_also_fails(registry: ToolRegistry) -> None:
    """嵌套一层就放行，等于给模型开了一条改写身份的侧门。"""

    with pytest.raises(ToolRegistrationError, match="merchant_id"):
        registry.register(spec(name="bad", args_model=NestedIdentityArgs))


def test_args_model_must_forbid_extra(registry: ToolRegistry) -> None:
    """默认 extra="ignore" 会静默吞掉越权字段。"""

    with pytest.raises(ToolRegistrationError, match="extra"):
        registry.register(spec(name="loose", args_model=LooseArgs))


def test_parallelizable_requires_read_only_policy(registry: ToolRegistry) -> None:
    """§6.9：parallelizable=True 只允许与 WritePolicy.READ_ONLY 组合。"""

    with pytest.raises(ToolRegistrationError, match="parallelizable"):
        registry.register(
            spec(
                name="w",
                roles=frozenset({ToolRole.MERCHANT}),
                args_model=ProductArgs,
                write_policy=WritePolicy.MERCHANT_DRAFT,
                parallelizable=True,
                executor=draft_exec,
                draft_kind=DraftKind.RESTOCK,
            )
        )


def test_duplicate_name_fails(registry: ToolRegistry) -> None:
    registry.register(spec())
    with pytest.raises(ToolRegistrationError, match="重复"):
        registry.register(spec())


def test_invalid_name_fails(registry: ToolRegistry) -> None:
    with pytest.raises(ToolRegistrationError, match="名称"):
        registry.register(spec(name="Search Products"))


def test_empty_roles_fails(registry: ToolRegistry) -> None:
    with pytest.raises(ToolRegistrationError, match="角色"):
        registry.register(spec(roles=frozenset()))


# --- executor 自检：必须显式接收 SessionContext（经 ToolContext）------------------


def test_executor_must_receive_tool_context(registry: ToolRegistry) -> None:
    """§6.9：内部 executor 明确接收 SessionContext，不得靠全局变量。"""

    with pytest.raises(ToolRegistrationError, match="ToolContext"):
        registry.register(spec(executor=no_context_exec))


def test_executor_must_be_annotated(registry: ToolRegistry) -> None:
    with pytest.raises(ToolRegistrationError, match="ToolContext"):
        registry.register(spec(executor=untyped_exec))


def test_executor_must_be_async(registry: ToolRegistry) -> None:
    with pytest.raises(ToolRegistrationError, match="async"):
        registry.register(spec(executor=sync_exec))


def test_executor_args_annotation_must_match_args_model(registry: ToolRegistry) -> None:
    with pytest.raises(ToolRegistrationError, match="args_model"):
        registry.register(spec(args_model=ProductArgs, executor=read_exec))


# --- 四种 WritePolicy 各有正反例 ----------------------------------------------------


def test_read_only_accepts_tool_output(registry: ToolRegistry) -> None:
    registry.register(spec())
    assert registry.get("search_products").write_policy is WritePolicy.READ_ONLY


def test_read_only_rejects_draft_returning_executor(registry: ToolRegistry) -> None:
    with pytest.raises(ToolRegistrationError, match="返回"):
        registry.register(spec(args_model=ProductArgs, executor=draft_exec, parallelizable=False))


def test_customer_direct_accepts_customer_only_tool(registry: ToolRegistry) -> None:
    registry.register(
        spec(
            name="set_cart_quantity",
            args_model=ProductArgs,
            write_policy=WritePolicy.CUSTOMER_DIRECT,
            parallelizable=False,
            executor=product_exec,
        )
    )


def test_customer_direct_rejects_merchant_role(registry: ToolRegistry) -> None:
    """PRD SEC6：顾客写与商家草稿审批不得混用。"""

    with pytest.raises(ToolRegistrationError, match="CUSTOMER_DIRECT"):
        registry.register(
            spec(
                name="set_cart_quantity",
                roles=frozenset({ToolRole.CUSTOMER, ToolRole.MERCHANT}),
                args_model=ProductArgs,
                write_policy=WritePolicy.CUSTOMER_DIRECT,
                parallelizable=False,
                executor=product_exec,
            )
        )


def test_customer_confirmation_requires_preview_executor(registry: ToolRegistry) -> None:
    registry.register(
        spec(
            name="prepare_after_sale",
            args_model=ProductArgs,
            write_policy=WritePolicy.CUSTOMER_CONFIRMATION,
            parallelizable=False,
            executor=preview_exec,
        )
    )
    with pytest.raises(ToolRegistrationError, match="ConfirmationPreview"):
        registry.register(
            spec(
                name="after_sale_directly",
                args_model=ProductArgs,
                write_policy=WritePolicy.CUSTOMER_CONFIRMATION,
                parallelizable=False,
                executor=product_exec,
            )
        )


# --- 顾客 Agent 不得有下单 / 支付能力（交易计划 Task 0，PRD C2）-------------------


@pytest.mark.parametrize("name", ["submit_order", "pay_order", "checkout", "create_payment"])
def test_customer_agent_cannot_register_order_or_payment_tools(
    registry: ToolRegistry, name: str
) -> None:
    """名称兜底：主防线是这些工具根本不被写出来，这里挡住将来「顺手」加一个。"""

    with pytest.raises(ToolRegistrationError, match="下单或支付"):
        registry.register(
            spec(
                name=name,
                args_model=ProductArgs,
                write_policy=WritePolicy.CUSTOMER_CONFIRMATION,
                parallelizable=False,
                executor=preview_exec,
            )
        )


def test_customer_direct_order_tool_is_blocked(registry: ToolRegistry) -> None:
    with pytest.raises(ToolRegistrationError, match="下单或支付"):
        registry.register(
            spec(
                name="place_order",
                args_model=ProductArgs,
                write_policy=WritePolicy.CUSTOMER_DIRECT,
                parallelizable=False,
                executor=product_exec,
            )
        )


def test_customer_read_only_order_lookup_is_allowed(registry: ToolRegistry) -> None:
    """只读查询自己的订单不是「下单或支付能力」；拦截只针对写策略不是 READ_ONLY 的工具。"""

    registry.register(spec(name="read_order"))


def test_order_word_inside_unrelated_token_is_not_blocked(registry: ToolRegistry) -> None:
    """按下划线切词匹配，而不是子串：`display` 里的 pay 不算。"""

    registry.register(spec(name="display_shop_policy"))


def test_merchant_tool_may_mention_orders(registry: ToolRegistry) -> None:
    registry.register(spec(name="order_summary", roles=frozenset({ToolRole.MERCHANT})))


def test_customer_tool_cannot_use_merchant_draft_policy(registry: ToolRegistry) -> None:
    with pytest.raises(ToolRegistrationError, match="MERCHANT_DRAFT"):
        registry.register(
            spec(
                name="draft_anything",
                args_model=ProductArgs,
                write_policy=WritePolicy.MERCHANT_DRAFT,
                parallelizable=False,
                executor=draft_exec,
                draft_kind=DraftKind.RESTOCK,
            )
        )


def test_merchant_draft_requires_draft_proposal_and_kind(registry: ToolRegistry) -> None:
    registry.register(
        spec(
            name="draft_restock",
            roles=frozenset({ToolRole.MERCHANT}),
            args_model=ProductArgs,
            write_policy=WritePolicy.MERCHANT_DRAFT,
            parallelizable=False,
            executor=draft_exec,
            draft_kind=DraftKind.RESTOCK,
        )
    )
    with pytest.raises(ToolRegistrationError, match="draft_kind"):
        registry.register(
            spec(
                name="draft_without_kind",
                roles=frozenset({ToolRole.MERCHANT}),
                args_model=ProductArgs,
                write_policy=WritePolicy.MERCHANT_DRAFT,
                parallelizable=False,
                executor=draft_exec,
            )
        )


def test_merchant_draft_rejects_direct_write_executor(registry: ToolRegistry) -> None:
    """草稿工具若返回 ToolOutput，就意味着它自己写了目标对象。"""

    with pytest.raises(ToolRegistrationError, match="DraftProposal"):
        registry.register(
            spec(
                name="restock_now",
                roles=frozenset({ToolRole.MERCHANT}),
                args_model=ProductArgs,
                write_policy=WritePolicy.MERCHANT_DRAFT,
                parallelizable=False,
                executor=product_exec,
                draft_kind=DraftKind.RESTOCK,
            )
        )


def test_draft_kind_only_allowed_on_merchant_draft(registry: ToolRegistry) -> None:
    with pytest.raises(ToolRegistrationError, match="draft_kind"):
        registry.register(spec(draft_kind=DraftKind.RESTOCK))


# --- 来源引用自检 ------------------------------------------------------------------


def test_provenance_ref_must_name_existing_arg(registry: ToolRegistry) -> None:
    with pytest.raises(ToolRegistrationError, match="provenance"):
        registry.register(
            spec(
                args_model=ProductArgs,
                executor=product_exec,
                provenance_refs=(ProvenanceRef(arg="sku", object_type="PRODUCT"),),
            )
        )


# --- 工具面 ------------------------------------------------------------------------


def _populated() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(spec())
    registry.register(
        spec(
            name="get_inventory_alerts",
            roles=frozenset({ToolRole.MERCHANT, ToolRole.MCP_READONLY}),
        )
    )
    registry.register(spec(name="get_sales_detail", roles=frozenset({ToolRole.MERCHANT})))
    registry.register(
        spec(
            name="apply_draft",
            roles=frozenset({ToolRole.MERCHANT}),
            args_model=ProductArgs,
            write_policy=WritePolicy.MERCHANT_DRAFT,
            parallelizable=False,
            executor=draft_exec,
            draft_kind=DraftKind.RESTOCK,
        )
    )
    return registry


def test_customer_surface_excludes_merchant_tools() -> None:
    surface = _populated().surface_for(SessionRole.CUSTOMER)
    assert {t.name for t in surface} == {"search_products"}


def test_merchant_surface_excludes_customer_tools() -> None:
    names = {t.name for t in _populated().surface_for(SessionRole.MERCHANT)}
    assert "search_products" not in names
    assert "apply_draft" in names


def test_mcp_surface_is_strict_subset_of_merchant_readonly() -> None:
    registry = _populated()
    mcp = {t.name for t in registry.surface_for_mcp()}
    merchant_ro = {
        t.name
        for t in registry.surface_for(SessionRole.MERCHANT)
        if t.write_policy is WritePolicy.READ_ONLY
    }
    assert mcp == {"get_inventory_alerts"}
    assert mcp < merchant_ro


def test_mcp_role_requires_read_only_merchant_tool(registry: ToolRegistry) -> None:
    with pytest.raises(ToolRegistrationError, match="MCP_READONLY"):
        registry.register(spec(roles=frozenset({ToolRole.CUSTOMER, ToolRole.MCP_READONLY})))
    with pytest.raises(ToolRegistrationError, match="MCP_READONLY"):
        registry.register(
            spec(
                name="draft_restock",
                roles=frozenset({ToolRole.MERCHANT, ToolRole.MCP_READONLY}),
                args_model=ProductArgs,
                write_policy=WritePolicy.MERCHANT_DRAFT,
                parallelizable=False,
                executor=draft_exec,
                draft_kind=DraftKind.RESTOCK,
            )
        )


def test_every_session_role_maps_to_a_surface() -> None:
    """穷尽映射：新增 SessionRole 却忘了映射，应当在这里失败，而不是运行时 KeyError。"""

    registry = _populated()
    for role in SessionRole:
        registry.surface_for(role)


def test_tool_schemas_are_exported_from_args_model() -> None:
    schemas = {s.name: s for s in _populated().schemas_for(SessionRole.CUSTOMER)}
    assert set(schemas) == {"search_products"}
    assert schemas["search_products"].parameters["properties"] == {
        "q": {"title": "Q", "type": "string"}
    }
    assert schemas["search_products"].parameters["additionalProperties"] is False


def test_get_unknown_tool_returns_none(registry: ToolRegistry) -> None:
    assert registry.find("nope") is None
