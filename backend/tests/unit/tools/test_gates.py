"""四类闸门（§6.9，N2 Task 2；Astra N2-1）。

执行顺序固定：来源 → 选项 → 护栏 → 审批，前一道不过不进下一道；
任何闸门都在工具 executor 执行之前生效，且整条闸门路径零 LLM。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from app.core.errors import ErrorCode
from app.localization.locales import SupportedLocale
from app.schemas.v2.common import ToolDisplayStatus
from app.schemas.v2.drafts import DraftKind
from app.tools.errors import FatalToolError, GuardrailRejection
from app.tools.gates import ToolGates, provenance_scope
from app.tools.registry import ToolRegistry
from app.tools.types import ObjectRef, ToolOutcome, ToolResult

from .tool_doubles import (
    PRINCIPAL_SECRET,
    PRODUCTS,
    GateHarness,
    InMemoryProvenance,
    RecordingAudit,
    ctx_for,
    customer_session,
    merchant_session,
)


async def _see_product(harness: GateHarness, ctx, product_id: str = "p-1") -> None:  # type: ignore[no-untyped-def]
    """让对象在本对话中「由工具返回过」：走真实工具调用，而不是直接往来源表里塞。"""

    result = await harness.gates.invoke(ctx, "get_product", {"product_id": product_id})
    assert result.ok
    harness.stages.clear()


# --- 来源闸门 ---------------------------------------------------------------------


async def test_provenance_gate_rejects_object_from_other_conversation(
    harness: GateHarness,
) -> None:
    """O2：隔离键是登录主体 + 店铺 + 对话 ID。"""

    session = customer_session()
    await _see_product(harness, ctx_for(session, "c1"))

    with pytest.raises(FatalToolError):
        await harness.gates.invoke(
            ctx_for(session, "c2"), "set_cart_quantity", {"product_id": "p-1"}
        )


async def test_provenance_gate_accepts_object_seen_in_same_conversation(
    harness: GateHarness,
) -> None:
    ctx = ctx_for(customer_session(), "c1")
    await _see_product(harness, ctx)

    result = await harness.gates.invoke(ctx, "set_cart_quantity", {"product_id": "p-1"})

    assert result.ok is True
    assert result.outcome is ToolOutcome.SUCCEEDED
    assert result.display.status is ToolDisplayStatus.SUCCEEDED


async def test_provenance_does_not_leak_between_buyers_in_same_conversation_id(
    harness: GateHarness,
) -> None:
    """同一个对话 ID 换一个主体，资格同样不跟着走。"""

    await _see_product(harness, ctx_for(customer_session("buyer-a"), "c1"))

    with pytest.raises(FatalToolError):
        await harness.gates.invoke(
            ctx_for(customer_session("buyer-b"), "c1"),
            "set_cart_quantity",
            {"product_id": "p-1"},
        )


async def test_provenance_checks_every_element_of_a_list_argument(harness: GateHarness) -> None:
    ctx = ctx_for(customer_session(), "c1")
    await _see_product(harness, ctx, "p-1")

    with pytest.raises(FatalToolError):
        await harness.gates.invoke(ctx, "compare_products", {"product_ids": ["p-1", "p-9"]})


def test_guest_and_bound_principals_use_distinct_scope_kinds() -> None:
    guest = provenance_scope(ctx_for(customer_session(None)), principal_secret=PRINCIPAL_SECRET)
    bound = provenance_scope(ctx_for(customer_session()), principal_secret=PRINCIPAL_SECRET)
    merchant = provenance_scope(ctx_for(merchant_session()), principal_secret=PRINCIPAL_SECRET)

    assert guest.principal_kind == "GUEST_SESSION"
    assert bound.principal_kind == merchant.principal_kind == "BOUND_PRINCIPAL"
    # 主体键不得是原始 buyer_key（D7⑤ 别名不可逆）。
    assert "buyer-a" not in bound.principal_id


# --- 固定顺序 ---------------------------------------------------------------------


async def test_gates_run_in_fixed_order_and_stop_at_first_failure(harness: GateHarness) -> None:
    """来源不过时，后面的闸门与 executor 都不得被调用。"""

    with pytest.raises(FatalToolError):
        await harness.gates.invoke(
            ctx_for(merchant_session()),
            "draft_price_change",
            {"product_id": "p-unseen", "new_price_cents": 9_000},
        )

    assert harness.stages == ["provenance"]
    assert harness.drafts.staged == []


async def test_all_gates_precede_executor_on_success(harness: GateHarness) -> None:
    """spy 断言的是「在工具执行前被调用」，不只是「被调用过」。"""

    ctx = ctx_for(merchant_session())
    await _see_product(harness, ctx)

    await harness.gates.invoke(
        ctx, "draft_price_change", {"product_id": "p-1", "new_price_cents": 9_000}
    )

    assert harness.stages == ["provenance", "options", "guardrail", "approval", "execute"]


async def test_guardrail_failure_stops_before_approval(harness: GateHarness) -> None:
    ctx = ctx_for(merchant_session())
    await _see_product(harness, ctx)

    await harness.gates.invoke(
        ctx, "draft_price_change", {"product_id": "p-1", "new_price_cents": 5_000}
    )

    assert harness.stages == ["provenance", "options", "guardrail"]
    assert harness.drafts.staged == []


# --- 选项闸门 ---------------------------------------------------------------------


async def test_options_gate_rejects_value_outside_backend_options(harness: GateHarness) -> None:
    with pytest.raises(FatalToolError):
        await harness.gates.invoke(
            ctx_for(merchant_session()), "query_metric", {"metric_code": "drop_table"}
        )
    assert harness.stages == ["provenance", "options"]


async def test_options_gate_accepts_backend_option(harness: GateHarness) -> None:
    result = await harness.gates.invoke(
        ctx_for(merchant_session()), "query_metric", {"metric_code": "gmv"}
    )
    assert result.ok


# --- 护栏闸门：可见原因（两类失败用不同表达）----------------------------------------


async def test_guardrail_reason_visible_to_merchant(harness: GateHarness) -> None:
    ctx = ctx_for(merchant_session())
    await _see_product(harness, ctx)

    result = await harness.gates.invoke(
        ctx, "draft_price_change", {"product_id": "p-1", "new_price_cents": 5_000}
    )

    assert isinstance(result, ToolResult)
    assert result.ok is False
    assert result.reason_code is ErrorCode.GUARDRAIL_REJECTED
    assert result.outcome is ToolOutcome.REJECTED
    assert result.display.status is ToolDisplayStatus.FAILED  # 对外只有契约里的封闭状态
    guardrail = result.guardrail
    assert guardrail is not None
    assert guardrail.code == "DISCOUNT_EXCEEDS_LIMIT"
    assert guardrail.current_limit is not None and "20%" in guardrail.current_limit
    assert guardrail.remediation  # 修正方法
    assert harness.audit.events == []  # 业务护栏不是安全事件


async def test_guardrail_rejection_is_not_a_fatal_error() -> None:
    """类型层面分开：护栏异常不是 FatalToolError 的子类，反之亦然。"""

    assert not issubclass(GuardrailRejection, FatalToolError)
    assert not issubclass(FatalToolError, GuardrailRejection)


# --- 安全闸门中性 -----------------------------------------------------------------


@pytest.mark.parametrize("session_factory", [merchant_session, customer_session])
async def test_security_gate_is_neutral_for_all_roles(
    harness: GateHarness,
    caplog: pytest.LogCaptureFixture,
    session_factory,  # type: ignore[no-untyped-def]
) -> None:
    """O5：安全闸门对所有角色只给中性说明，内部闸门名只进安全日志。"""

    caplog.set_level(logging.WARNING, logger="app.security.tools")
    with pytest.raises(FatalToolError) as exc:
        await harness.gates.invoke(
            ctx_for(session_factory()), "read_order", {"order_id": "o-foreign"}
        )

    for public in (exc.value.public_message, str(exc.value), repr(exc.value)):
        assert "provenance" not in public
        assert "来源闸门" not in public
        assert "o-foreign" not in public
    assert exc.value.status_code == 403
    assert exc.value.code is ErrorCode.RESOURCE_FORBIDDEN
    assert "provenance" in caplog.text  # 内部日志可区分
    assert harness.audit.events == [
        {"tool": "read_order", "gate": "provenance", "role": session_factory().role.value}
    ]


async def test_all_fatal_gates_share_one_public_shape(harness: GateHarness) -> None:
    """不同闸门的致命错误对外逐字段一致，外部无法据此推断撞的是哪一道。"""

    merchant = ctx_for(merchant_session())
    failures: list[FatalToolError] = []
    for tool, args in (
        ("read_order", {"order_id": "o-x"}),  # 来源
        ("query_metric", {"metric_code": "nope"}),  # 选项
        ("set_cart_quantity", {"product_id": "p-1"}),  # 工具面
        ("query_metric", {"metric_code": "gmv", "merchant_id": "m-2"}),  # 身份参数
    ):
        with pytest.raises(FatalToolError) as exc:
            await harness.gates.invoke(merchant, tool, args)
        failures.append(exc.value)

    shapes = {(f.code, f.status_code, f.public_message, str(f)) for f in failures}
    assert len(shapes) == 1
    assert [e["gate"] for e in harness.audit.events] == [
        "provenance",
        "options",
        "surface",
        "identity",
    ]


# --- 工具面与身份参数 --------------------------------------------------------------


async def test_unknown_tool_name_is_returned_to_model_not_fatal(harness: GateHarness) -> None:
    """编出一个不存在的工具名是模型的错误，不是越权：不终止回合、不写审计。"""

    result = await harness.gates.invoke(
        ctx_for(customer_session()), "Delete Everything!", {}, call_id="call_x"
    )

    assert result.ok is False
    assert result.reason_code is ErrorCode.INVALID_REQUEST
    assert result.outcome is ToolOutcome.INVALID_ARGUMENTS
    assert harness.audit.events == []
    # 模型编的名字不进 SSE：不合格式时显示为占位名。
    assert result.display.tool_name == "unknown_tool"
    assert result.display.result_event(SupportedLocale.ZH_CN).summary == "处理失败"


async def test_customer_calling_merchant_tool_is_fatal_and_audited(harness: GateHarness) -> None:
    """§6.9：顾客会话调用商家工具 → 403 + 审计，且不产生 ToolResult。"""

    with pytest.raises(FatalToolError):
        await harness.gates.invoke(
            ctx_for(customer_session()), "query_metric", {"metric_code": "gmv"}
        )
    assert harness.audit.events[0]["gate"] == "surface"
    assert harness.stages == []  # 连来源闸门都没进


@pytest.mark.parametrize("field", ["merchant_id", "buyer_key"])
async def test_model_cannot_override_identity_through_arguments(
    harness: GateHarness, field: str
) -> None:
    """模型不能经工具参数改写身份或商家范围（R5）；这是安全事件，不是参数错误。"""

    ctx = ctx_for(customer_session())
    await _see_product(harness, ctx)

    with pytest.raises(FatalToolError):
        await harness.gates.invoke(
            ctx, "set_cart_quantity", json.dumps({"product_id": "p-1", field: "other"})
        )
    assert harness.audit.events[-1]["gate"] == "identity"


async def test_invalid_arguments_return_neutral_tool_result(harness: GateHarness) -> None:
    """普通参数错误可以交还模型修正，但 display 不含原始校验信息。"""

    ctx = ctx_for(merchant_session())
    await _see_product(harness, ctx)

    result = await harness.gates.invoke(ctx, "restock", {"product_id": "p-1", "quantity": -5})

    assert result.ok is False
    assert result.reason_code is ErrorCode.INVALID_REQUEST
    assert result.outcome is ToolOutcome.INVALID_ARGUMENTS
    assert "greater_than" not in result.summary
    assert "-5" not in result.summary
    assert harness.stages == []  # 校验不过就不进四类闸门


async def test_malformed_json_arguments_return_invalid_request(harness: GateHarness) -> None:
    result = await harness.gates.invoke(
        ctx_for(merchant_session()), "query_metric", '{"metric_code": '
    )
    assert result.reason_code is ErrorCode.INVALID_REQUEST


# --- 审批闸门：四种 WritePolicy ------------------------------------------------------


async def test_approval_gate_converts_write_to_draft(harness: GateHarness) -> None:
    ctx = ctx_for(merchant_session())
    await _see_product(harness, ctx)
    before = {k: dict(v) for k, v in PRODUCTS.items()}

    result = await harness.gates.invoke(ctx, "restock", {"product_id": "p-1", "quantity": 20})

    assert result.ok is True
    assert result.outcome is ToolOutcome.DRAFT_CREATED
    assert result.display.status is ToolDisplayStatus.SUCCEEDED
    assert isinstance(result.payload, dict) and result.payload["draft_id"] == "drf_1"
    assert before == PRODUCTS  # 目标对象未被修改
    kind, proposal = harness.drafts.staged[0]
    assert kind is DraftKind.RESTOCK
    assert proposal.changes == {"stock_delta": 20}
    # 草稿本身成为本对话见过的对象，后续工具可以引用它。
    scope = harness.gates.scope_for(ctx)
    assert await harness.provenance.has(scope, ObjectRef("DRAFT", "drf_1"))


async def test_customer_confirmation_tool_never_writes_in_loop(harness: GateHarness) -> None:
    ctx = ctx_for(customer_session())
    await _see_product(harness, ctx)

    result = await harness.gates.invoke(ctx, "prepare_after_sale", {"product_id": "p-1"})

    assert result.ok is False
    assert result.reason_code is ErrorCode.CONFIRMATION_REQUIRED
    assert result.outcome is ToolOutcome.AWAITING_CONFIRMATION
    assert harness.drafts.staged == []  # 顾客写不得套进商家草稿审批（PRD SEC6）


async def test_read_only_tool_records_produced_objects(harness: GateHarness) -> None:
    ctx = ctx_for(customer_session())
    await harness.gates.invoke(ctx, "get_product", {"product_id": "p-7"})
    assert await harness.provenance.has(harness.gates.scope_for(ctx), ObjectRef("PRODUCT", "p-7"))


async def test_display_carries_no_arguments_or_rows_for_any_policy(harness: GateHarness) -> None:
    """每种写策略的 display 都不含参数与结果；工具说明（含参数）只留在 ToolResult.summary。"""

    customer = ctx_for(customer_session())
    merchant = ctx_for(merchant_session())
    await _see_product(harness, customer, "p-secret-42")
    await _see_product(harness, merchant, "p-secret-42")
    results = [
        await harness.gates.invoke(customer, "get_product", {"product_id": "p-secret-42"}),
        await harness.gates.invoke(customer, "set_cart_quantity", {"product_id": "p-secret-42"}),
        await harness.gates.invoke(customer, "prepare_after_sale", {"product_id": "p-secret-42"}),
        await harness.gates.invoke(
            merchant, "restock", {"product_id": "p-secret-42", "quantity": 937}
        ),
    ]

    assert "937" in results[-1].summary  # 说明里有参数，这是给模型的
    for result in results:
        for locale in SupportedLocale:
            event = result.display.result_event(locale).model_dump_json()
            assert "p-secret-42" not in event
            assert "937" not in event
            assert "忽略以上指令" not in event  # payload 的第三方文本不进 display
        assert "p-secret-42" not in repr(result.display)


@pytest.mark.parametrize("outcome", list(ToolOutcome))
@pytest.mark.parametrize("locale", list(SupportedLocale))
def test_every_outcome_projects_to_a_valid_sse_payload(
    outcome: ToolOutcome, locale: SupportedLocale
) -> None:
    """ToolDisplay 必须能投影成 §8.7.5 的契约模型：状态与固定短句由契约校验器把关。"""

    from app.tools.types import DISPLAY_STATUS, ToolDisplay

    display = ToolDisplay(
        tool_name="get_product",
        call_id="call_1",
        status=DISPLAY_STATUS[outcome],
        duration_ms=3,
        row_count=None,
    )
    assert display.result_event(locale).status is DISPLAY_STATUS[outcome]
    assert display.call_event(locale).status is ToolDisplayStatus.STARTED


async def test_display_carries_the_model_call_id(harness: GateHarness) -> None:
    result = await harness.gates.invoke(
        ctx_for(customer_session()), "get_product", {"product_id": "p-1"}, call_id="call_abc"
    )
    assert result.display.call_id == "call_abc"
    assert result.display.result_event(SupportedLocale.EN_US).call_id == "call_abc"


def test_gates_require_draft_sink_when_draft_tools_registered() -> None:
    from .tool_doubles import SPECS

    registry = ToolRegistry()
    for spec in SPECS:
        registry.register(spec)
    with pytest.raises(ValueError, match="DraftSink"):
        ToolGates(
            registry,
            provenance=InMemoryProvenance(),
            principal_secret=PRINCIPAL_SECRET,
            audit=RecordingAudit(),
        )


def test_gates_module_has_no_llm_dependency() -> None:
    """闸门零 LLM：闸门模块不 import 任何 LLM 客户端，也没有注入点。"""

    source = Path(__file__).resolve().parents[3].joinpath("app", "tools", "gates.py")
    text = source.read_text(encoding="utf-8")
    assert "app.llm" not in text
    assert "converse" not in text
