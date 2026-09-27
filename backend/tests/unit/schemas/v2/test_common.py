import pytest
from pydantic import ValidationError

from app.core.session import SessionRole
from app.schemas.v2.common import (
    AnalysisSourceEntry,
    CursorPage,
    CursorPageRequest,
    DegradationMixin,
    IdempotentWriteRequest,
    SseEventName,
    V2ChatResponseBase,
)


def test_cursor_limit_rejects_out_of_range() -> None:
    with pytest.raises(ValidationError):
        CursorPageRequest(limit=0)
    with pytest.raises(ValidationError):
        CursorPageRequest(limit=101)


def test_cursor_defaults_to_first_page() -> None:
    page = CursorPageRequest()
    assert page.cursor is None
    assert page.limit == 20


@pytest.mark.parametrize(("next_cursor", "has_more"), [(None, True), ("c2", False), ("", True)])
def test_cursor_page_has_more_matches_next_cursor(next_cursor: str | None, has_more: bool) -> None:
    """§8.7.4：next_cursor 为 null 表示末页，has_more 必须与之一致。"""
    with pytest.raises(ValidationError):
        CursorPage[int].model_validate(
            {"items": [1], "next_cursor": next_cursor, "has_more": has_more}
        )
    assert CursorPage[int](items=[1], next_cursor="c2", has_more=True).has_more


def test_idempotent_write_requires_client_request_id() -> None:
    with pytest.raises(ValidationError):
        IdempotentWriteRequest()


def test_idempotent_write_rejects_merchant_id() -> None:
    """R5：请求侧永不接受 merchant_id / buyer_key。"""
    with pytest.raises(ValidationError):
        IdempotentWriteRequest(client_request_id="r1", merchant_id="m1")


def test_turn_level_pass_allows_single_degraded_source() -> None:
    payload = DegradationMixin(
        analysis_sources=[
            AnalysisSourceEntry(source="DATABASE", degraded=False, degraded_reason=None),
            AnalysisSourceEntry(source="KNOWLEDGE", degraded=True, degraded_reason="UPSTREAM"),
        ],
        degraded=False,
        degraded_reason=None,
        quality_status="NOT_RUN",
        quality_attempts=0,
        quality_notes=[],
    )
    assert payload.degraded is False
    assert payload.analysis_sources[1].degraded is True


def test_quality_notes_defaults_to_empty_list_not_none() -> None:
    payload = DegradationMixin(
        analysis_sources=[AnalysisSourceEntry(source="NONE", degraded=False, degraded_reason=None)],
        degraded=False,
        degraded_reason=None,
        quality_status="NOT_RUN",
        quality_attempts=0,
    )
    assert payload.quality_notes == []


def test_degraded_reason_must_match_degraded_flag() -> None:
    with pytest.raises(ValidationError):
        AnalysisSourceEntry(source="DATABASE", degraded=True, degraded_reason=None)
    with pytest.raises(ValidationError):
        DegradationMixin(
            analysis_sources=[
                AnalysisSourceEntry(source="DATABASE", degraded=False, degraded_reason=None)
            ],
            degraded=False,
            degraded_reason="unexpected",
            quality_status="NOT_RUN",
            quality_attempts=0,
        )


def test_none_source_must_be_exclusive() -> None:
    with pytest.raises(ValidationError):
        DegradationMixin(
            analysis_sources=[
                AnalysisSourceEntry(source="NONE", degraded=False, degraded_reason=None),
                AnalysisSourceEntry(source="DATABASE", degraded=False, degraded_reason=None),
            ],
            degraded=False,
            degraded_reason=None,
            quality_status="NOT_RUN",
            quality_attempts=0,
        )


def test_v2_rejects_removed_attachment_source() -> None:
    with pytest.raises(ValidationError):
        AnalysisSourceEntry(source="ATTACHMENT", degraded=False, degraded_reason=None)


def test_sse_event_names_match_contract() -> None:
    assert {e.value for e in SseEventName} == {
        "step",
        "tool_call",
        "tool_result",
        "turn_complete",
        "error",
    }


def test_session_role_is_closed_enum() -> None:
    assert {r.value for r in SessionRole} == {"CUSTOMER", "MERCHANT"}


def test_chat_base_has_conversation_id_not_session_id() -> None:
    """§8.7.7：认证会话与业务对话分名。"""
    fields = V2ChatResponseBase.model_fields
    assert "conversation_id" in fields
    assert "session_id" not in fields


def test_chat_base_leaves_answer_mode_to_subclasses() -> None:
    """两端枚举不同，基类不定义 answer_mode，避免 Task 3 依赖 Task 2。"""
    assert "answer_mode" not in V2ChatResponseBase.model_fields


def test_money_conversion_never_passes_through_float() -> None:
    from decimal import Decimal

    from app.schemas.v2.common import yuan_to_cents

    assert yuan_to_cents(Decimal("1.005")) == 101  # ROUND_HALF_UP
    assert yuan_to_cents(Decimal("0.07")) == 7  # float 路径会得到 6
    assert yuan_to_cents(Decimal("999999999999.99")) == 99999999999999


def test_money_upper_bound_is_js_safe() -> None:
    """Numeric(14,2) 上界换算成分后仍小于 Number.MAX_SAFE_INTEGER。"""
    assert 99999999999999 < 9007199254740991


@pytest.mark.parametrize("value", [-1, 100000000000000, True, "100", 1.5])
def test_money_rejects_invalid_wire_values(value: object) -> None:
    from pydantic import TypeAdapter

    from app.schemas.v2.common import MoneyCents

    with pytest.raises(ValidationError):
        TypeAdapter(MoneyCents).validate_python(value)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-0.01", "1000000000000"])
def test_yuan_conversion_rejects_invalid_values(value: str) -> None:
    from decimal import Decimal

    from app.schemas.v2.common import yuan_to_cents

    with pytest.raises(ValueError):
        yuan_to_cents(Decimal(value))


def test_money_round_trip_and_line_rounding() -> None:
    from decimal import Decimal

    from app.schemas.v2.common import cents_to_yuan, yuan_to_cents

    for value in (0, 7, 101, 99999999999999):
        assert yuan_to_cents(cents_to_yuan(value)) == value
    assert sum(yuan_to_cents(v) for v in [Decimal("1.005")] * 2) == 202


@pytest.mark.parametrize("field", ["merchant_id", "buyer_key", "offset"])
def test_cursor_rejects_extra_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        CursorPageRequest.model_validate({field: "untrusted"})


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_source_rejects_missing_or_blank_degradation_reason(reason: str | None) -> None:
    with pytest.raises(ValidationError):
        AnalysisSourceEntry(source="DATABASE", degraded=True, degraded_reason=reason)


def test_tool_display_rejects_raw_arguments_and_results() -> None:
    from app.schemas.v2.common import ToolCallDisplay, ToolResultDisplay

    with pytest.raises(ValidationError):
        ToolCallDisplay.model_validate(
            dict(
                tool_name="lookup",
                call_id="c1",
                status="RUNNING",
                summary="正在处理",
                arguments={},
            )
        )
    with pytest.raises(ValidationError):
        ToolResultDisplay.model_validate(
            dict(
                call_id="c1",
                status="SUCCEEDED",
                duration_ms=1,
                row_count=None,
                summary="处理完成",
                rows=[],
            )
        )


def test_chat_timestamp_is_utc_and_requires_timezone() -> None:
    payload = dict(
        id="a1",
        conversation_id="c1",
        answer="你好",
        tool_calls=[],
        analysis_sources=[dict(source="NONE", degraded=False, degraded_reason=None)],
        degraded=False,
        degraded_reason=None,
        quality_status="NOT_RUN",
        quality_attempts=0,
    )
    response = V2ChatResponseBase.model_validate(
        {**payload, "created_at": "2026-09-21T08:00:00+08:00"}
    )
    assert response.model_dump(mode="json")["created_at"] == "2026-09-21T00:00:00Z"
    with pytest.raises(ValidationError):
        V2ChatResponseBase.model_validate({**payload, "created_at": "2026-09-21T08:00:00"})


def test_fallback_cannot_be_reported_as_normal_model_analysis() -> None:
    with pytest.raises(ValidationError):
        DegradationMixin(
            analysis_sources=[
                AnalysisSourceEntry(source="FALLBACK", degraded=False, degraded_reason=None)
            ],
            quality_status="PASSED",
            quality_attempts=1,
            degraded=False,
            degraded_reason=None,
        )
    with pytest.raises(ValidationError):
        DegradationMixin(
            analysis_sources=[
                AnalysisSourceEntry(
                    source="FALLBACK", degraded=True, degraded_reason="RULE_FALLBACK"
                )
            ],
            quality_status="DEGRADED",
            quality_attempts=1,
            degraded=False,
            degraded_reason=None,
        )


def test_v2_source_schema_does_not_advertise_attachment() -> None:
    from pydantic import TypeAdapter

    schema = TypeAdapter(AnalysisSourceEntry).json_schema()
    source = schema["properties"]["source"]
    values = source.get("enum") or schema["$defs"][source["$ref"].split("/")[-1]]["enum"]
    assert "ATTACHMENT" not in values


def test_tool_display_rejects_sensitive_summary_and_unknown_status() -> None:
    from app.schemas.v2.common import ToolCallDisplay, ToolResultDisplay

    for model, fields, summary in (
        (ToolCallDisplay, dict(tool_name="lookup", call_id="c1", status="STARTED"), "正在处理"),
        (
            ToolResultDisplay,
            dict(call_id="c1", status="SUCCEEDED", duration_ms=1, row_count=0),
            "处理完成",
        ),
    ):
        with pytest.raises(ValidationError):
            model.model_validate({**fields, "summary": "SQL: SELECT * FROM private_table"})
        with pytest.raises(ValidationError):
            model.model_validate({**fields, "status": "token=FAKE-ONLY", "summary": summary})
        assert model.model_validate({**fields, "summary": summary}).summary == summary


@pytest.mark.parametrize("value", ["", " ", "\n", "id with spaces", "x\x00y"])
def test_idempotency_id_rejects_empty_or_control_characters(value: str) -> None:
    with pytest.raises(ValidationError):
        IdempotentWriteRequest(client_request_id=value)


@pytest.mark.parametrize("value", ["", "a" * 2049])
def test_cursor_rejects_empty_or_excessively_long_values(value: str) -> None:
    with pytest.raises(ValidationError):
        CursorPageRequest(cursor=value)


@pytest.mark.parametrize(
    ("status", "summary"),
    [
        ("FAILED", "处理完成"),
        ("SUCCEEDED", "Failed"),
        ("RUNNING", "处理完成"),
        ("UNAVAILABLE", "Completed"),
    ],
)
def test_tool_summary_must_match_status(status: str, summary: str) -> None:
    from app.schemas.v2.common import ToolCallDisplay, ToolResultDisplay

    with pytest.raises(ValidationError):
        ToolCallDisplay.model_validate(
            dict(tool_name="lookup", call_id="c1", status=status, summary=summary)
        )
    with pytest.raises(ValidationError):
        ToolResultDisplay.model_validate(
            dict(call_id="c1", status=status, duration_ms=1, row_count=None, summary=summary)
        )


# ---- 猜你想问（§8.7.10，M13）-------------------------------------------------------

_CHAT_PAYLOAD = dict(
    id="a1",
    conversation_id="c1",
    answer="你好",
    tool_calls=[],
    analysis_sources=[dict(source="NONE", degraded=False, degraded_reason=None)],
    degraded=False,
    degraded_reason=None,
    quality_status="NOT_RUN",
    quality_attempts=0,
    created_at="2026-09-21T00:00:00Z",
)


def _chat(**extra: object) -> V2ChatResponseBase:
    return V2ChatResponseBase.model_validate({**_CHAT_PAYLOAD, **extra})


def test_suggestions_default_to_empty_lists_not_none() -> None:
    response = _chat()
    assert response.suggestions == [] and response.suggestion_alternates == []
    dumped = response.model_dump(mode="json")
    assert dumped["suggestions"] == [] and dumped["suggestion_alternates"] == []


def test_suggestions_accept_a_current_group_and_distinct_alternates() -> None:
    response = _chat(suggestions=["a", "b", "c"], suggestion_alternates=[["d", "e", "f"]])
    assert response.suggestion_alternates == [["d", "e", "f"]]


@pytest.mark.parametrize(
    "extra",
    [
        dict(suggestions=["a", "b", "c", "d"]),
        dict(suggestions=[""]),
        dict(suggestions=["x" * 201]),
        dict(suggestions=["a"], suggestion_alternates=[[]]),
        dict(suggestions=["a"], suggestion_alternates=[["a"]]),
        dict(suggestions=["a"], suggestion_alternates=[["b", "c", "d", "e"]]),
        dict(suggestions=["a"], suggestion_alternates=[["b"]] * 6),
        dict(suggestions=[], suggestion_alternates=[["b"]]),
        dict(suggestions=None),
    ],
    ids=[
        "too-many-current",
        "blank-text",
        "text-too-long",
        "empty-alternate-group",
        "alternate-repeats-current",
        "alternate-group-too-large",
        "too-many-alternate-groups",
        "alternates-without-current",
        "null-not-allowed",
    ],
)
def test_suggestions_reject_invalid_shapes(extra: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _chat(**extra)
