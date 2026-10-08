"""MCP 工具面投影（N5 A Task 3；契约 §8.14.3；后端计划 §6.9）。

MCP 是工具注册表的另一个出口：工具面 = `surface_for_mcp()` ∩ 凭证 scope；执行走与商家会话同一套
`ToolGates`，`merchant_id` 只从凭证主体注入。审批证据、确认令牌与图表数据不外发。
"""

from __future__ import annotations

from uuid import UUID

import pytest
from mcp_types.jsonrpc import INTERNAL_ERROR, INVALID_PARAMS
from pydantic import BaseModel, ConfigDict

from app.core.session import SessionRole
from app.mcp.credentials import McpPrincipal
from app.mcp.server import McpToolError
from app.mcp.tools import RegistryToolBridge
from app.tools.gates import ToolGates
from app.tools.registry import build_tool_registry
from app.tools.types import ToolContext, ToolOutput, ToolRole, ToolSpec, WritePolicy
from tests.unit.tools.tool_doubles import (
    PRINCIPAL_SECRET,
    InMemoryProvenance,
    PriceChangeArgs,
    RecordingAudit,
    RecordingDraftSink,
    draft_price_change,
)

MERCHANT_A = UUID("00000000-0000-4000-8000-0000000000a1")
SEEN: list[ToolContext] = []


class MetricArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: str


async def query_metrics(ctx: ToolContext, args: MetricArgs) -> ToolOutput:
    SEEN.append(ctx)
    return ToolOutput(
        payload={
            "metric": args.metric,
            "value": "42.00",
            "merchant": str(ctx.session.merchant_id),
            "approval_evidence": "should-never-leave",
            "nested": [{"confirmation_token": "nope", "keep": 1}],
        },
        summary="已查询",
        row_count=1,
        chart_data={"series": [1, 2, 3]},
    )


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


async def get_inventory_alerts(ctx: ToolContext, args: NoArgs) -> ToolOutput:
    return ToolOutput(payload={"alerts": []}, summary="无告警")


def _spec(
    name: str, executor, args_model, roles, policy=WritePolicy.READ_ONLY, **extra
) -> ToolSpec:  # type: ignore[no-untyped-def]
    return ToolSpec(
        name=name,
        roles=frozenset(roles),
        args_model=args_model,
        write_policy=policy,
        parallelizable=policy is WritePolicy.READ_ONLY,
        description=f"{name} 说明",
        executor=executor,
        **extra,
    )


@pytest.fixture
def audit() -> RecordingAudit:
    return RecordingAudit()


@pytest.fixture
def bridge(audit: RecordingAudit) -> RegistryToolBridge:
    SEEN.clear()
    registry = build_tool_registry(
        (
            _spec(
                "query_metrics",
                query_metrics,
                MetricArgs,
                {ToolRole.MERCHANT, ToolRole.MCP_READONLY},
            ),
            _spec(
                "get_inventory_alerts",
                get_inventory_alerts,
                NoArgs,
                {ToolRole.MERCHANT, ToolRole.MCP_READONLY},
            ),
            _spec(
                "draft_price_change",
                draft_price_change,
                PriceChangeArgs,
                {ToolRole.MERCHANT},
                policy=WritePolicy.MERCHANT_DRAFT,
                draft_kind=_draft_kind(),
            ),
        )
    )
    gates = ToolGates(
        registry,
        provenance=InMemoryProvenance(),
        principal_secret=PRINCIPAL_SECRET,
        audit=audit,
        drafts=RecordingDraftSink(),
    )
    return RegistryToolBridge(gates)


def _draft_kind():  # type: ignore[no-untyped-def]
    from app.schemas.v2.drafts import DraftKind

    return next(iter(DraftKind))


def principal(*scopes: str) -> McpPrincipal:
    return McpPrincipal(credential_id=UUID(int=9), merchant_id=MERCHANT_A, scopes=frozenset(scopes))


def test_tools_list_is_intersection_of_mcp_surface_and_scopes(bridge: RegistryToolBridge) -> None:
    names = [tool.name for tool in bridge.list_tools(principal("query_metrics"))]

    assert names == ["query_metrics"]


def test_tools_list_never_contains_write_tools_even_if_scoped(bridge: RegistryToolBridge) -> None:
    names = {
        tool.name for tool in bridge.list_tools(principal("query_metrics", "draft_price_change"))
    }

    assert names == {"query_metrics"}


def test_tools_list_exposes_input_schema(bridge: RegistryToolBridge) -> None:
    (tool,) = bridge.list_tools(principal("query_metrics"))

    assert tool.input_schema["type"] == "object"
    assert "metric" in tool.input_schema["properties"]


async def test_merchant_id_comes_from_credential(bridge: RegistryToolBridge) -> None:
    payload = await bridge.call_tool(
        principal("query_metrics"), "query_metrics", {"metric": "gross_gmv"}, request_id="r-1"
    )

    assert payload["merchant"] == str(MERCHANT_A)
    (ctx,) = SEEN
    assert ctx.session.role is SessionRole.MERCHANT
    assert ctx.session.merchant_id == MERCHANT_A
    assert ctx.session.buyer_key is None
    assert ctx.request_id == "r-1"


async def test_output_strips_evidence_tokens_and_chart_data(bridge: RegistryToolBridge) -> None:
    payload = await bridge.call_tool(
        principal("query_metrics"), "query_metrics", {"metric": "gross_gmv"}, request_id="r-1"
    )

    text = repr(payload)
    assert "approval_evidence" not in text and "should-never-leave" not in text
    assert "confirmation_token" not in text
    assert "chart_data" not in text and "series" not in text
    assert payload["nested"] == [{"keep": 1}]


async def test_write_tool_unreachable_even_if_named(bridge: RegistryToolBridge) -> None:
    with pytest.raises(McpToolError) as error:
        await bridge.call_tool(
            principal("query_metrics", "draft_price_change"),
            "draft_price_change",
            {"product_id": "p-1", "new_price_cents": 1},
            request_id="r-1",
        )

    assert error.value.code == INVALID_PARAMS


async def test_unscoped_and_unknown_tools_look_identical(bridge: RegistryToolBridge) -> None:
    with pytest.raises(McpToolError) as unscoped:
        await bridge.call_tool(
            principal("query_metrics"), "get_inventory_alerts", {}, request_id="r"
        )
    with pytest.raises(McpToolError) as unknown:
        await bridge.call_tool(principal("query_metrics"), "no_such_tool", {}, request_id="r")

    assert (unscoped.value.code, unscoped.value.message) == (
        unknown.value.code,
        unknown.value.message,
    )


async def test_identity_argument_is_rejected_and_audited(
    bridge: RegistryToolBridge, audit: RecordingAudit
) -> None:
    with pytest.raises(McpToolError) as error:
        await bridge.call_tool(
            principal("query_metrics"),
            "query_metrics",
            {"metric": "gross_gmv", "merchant_id": str(UUID(int=1))},
            request_id="r-1",
        )

    assert error.value.code == INVALID_PARAMS
    assert SEEN == []
    assert audit.events and audit.events[0]["gate"] == "identity"


async def test_invalid_arguments_are_json_rpc_invalid_params(bridge: RegistryToolBridge) -> None:
    with pytest.raises(McpToolError) as error:
        await bridge.call_tool(
            principal("query_metrics"), "query_metrics", {"wrong": 1}, request_id="r"
        )

    assert error.value.code == INVALID_PARAMS


# ---------- 审查整改（F4） ----------


async def leaky_object(ctx: ToolContext, args: NoArgs) -> ToolOutput:
    from dataclasses import dataclass

    @dataclass
    class Hidden:
        approval_evidence: str = "should-never-leave"

    return ToolOutput(payload={"item": Hidden()}, summary="对象载荷")


async def test_non_json_payload_objects_are_rejected_not_stringified(audit: RecordingAudit) -> None:
    registry = build_tool_registry(
        (_spec("query_metrics", leaky_object, NoArgs, {ToolRole.MERCHANT, ToolRole.MCP_READONLY}),)
    )
    gates = ToolGates(
        registry, provenance=InMemoryProvenance(), principal_secret=PRINCIPAL_SECRET, audit=audit
    )

    with pytest.raises(McpToolError) as error:
        await RegistryToolBridge(gates).call_tool(
            principal("query_metrics"), "query_metrics", {}, request_id="r"
        )

    assert error.value.code == INTERNAL_ERROR
    assert "should-never-leave" not in str(error.value.data) + error.value.message
