"""Chat Schema 契约测试。"""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.chat import (
    CATEGORY_DISPLAY_NAMES,
    AnalysisSource,
    AnswerMode,
    ChatRequest,
    ChatResponse,
    QualityStatus,
    QuestionCategory,
)

METRIC_FIELDS: dict[str, object] = {
    "query_plan": {"summary": "演示查询计划"},
    "metric_code": "gmv",
    "metric_display_name": "总 GMV 金额",
    "metric_unit": "元",
    "metric_definition": "统计周期内已提交订单的商品金额合计。",
    "metric_sql_definition": "SUM(orders.paid_amount)",
    "metric_dimensions": ["date", "product", "category"],
    "metric_source_database": "public",
    "metric_source_table": "orders",
    "metric_report_url": None,
    "metric_source": "METRIC_CATALOG",
    "metric_generated": False,
    "metric_notice": None,
    "metric_owner": "交易数据组",
    "metric_status": "ACTIVE",
    "data_rows": [{"date": "2026-07-28", "value": 256920}],
    "total_rows": 1,
    "truncated": False,
    "visualization": {"enabled": False},
    "recommendations": [
        {"title": "承接增长流量", "evidence": "演示数据呈上升趋势", "action": "核对库存"},
        {"title": "复盘转化", "evidence": "演示数据周末增长", "action": "对比渠道"},
    ],
}


def _base_response(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": uuid4(),
        "session_id": uuid4(),
        "answer": "你好，我可以协助分析商家经营问题。",
        "answer_mode": AnswerMode.CHAT,
        "category": None,
        "thinking_steps": [],
        "quality_status": QualityStatus.NOT_RUN,
        "quality_attempts": 0,
        "quality_notes": [],
        "analysis_sources": [AnalysisSource.NONE],
        "degraded": False,
        "degraded_reason": None,
        "suggestions": ["昨天总 GMV 是多少？", "最近7天退货量趋势", "我要货品上架，具体规则有吗？"],
        "suggestion_alternates": [],
    }
    payload.update(overrides)
    return payload


def _metric_response(**overrides: object) -> dict[str, object]:
    payload = _base_response(
        answer_mode=AnswerMode.METRIC,
        category="TRADE",
        analysis_sources=[AnalysisSource.FALLBACK],
        degraded=True,
        degraded_reason="当前为演示规则结果，未查询经营数据库",
        **METRIC_FIELDS,
    )
    payload.update(overrides)
    return payload


# --- ChatRequest --------------------------------------------------------


def test_request_strips_whitespace_and_rejects_blank_messages() -> None:
    assert ChatRequest(message="  你好  ", client_request_id="r1").message == "你好"

    with pytest.raises(ValidationError):
        ChatRequest(message="   ", client_request_id="r1")


def test_request_rejects_attachments_in_p0() -> None:
    with pytest.raises(ValidationError, match="attachment_ids"):
        ChatRequest(
            message="你好",
            client_request_id="r1",
            attachment_ids=[uuid4()],
        )


def test_request_requires_a_client_request_id() -> None:
    with pytest.raises(ValidationError, match="client_request_id"):
        ChatRequest(message="你好")  # type: ignore[call-arg]


def test_request_ignores_unknown_merchant_id_field() -> None:
    """身份只来自 Bearer Token，请求体里的 merchant_id 不得成为模型字段。"""

    request = ChatRequest.model_validate(
        {"message": "你好", "client_request_id": "r1", "merchant_id": str(uuid4())}
    )

    assert not hasattr(request, "merchant_id")


# --- 来源与降级 ---------------------------------------------------------


def test_chat_accepts_none_source_without_degradation() -> None:
    response = ChatResponse.model_validate(_base_response())

    assert response.analysis_sources == [AnalysisSource.NONE]
    assert response.degraded is False


def test_no_data_modes_are_not_blocked_by_data_fields() -> None:
    """§8.2：CHAT / INVALID / RULE 缺 data_rows 必须放行。"""

    for mode in (AnswerMode.CHAT, AnswerMode.INVALID):
        assert ChatResponse.model_validate(_base_response(answer_mode=mode)).data_rows is None

    rule = ChatResponse.model_validate(
        _base_response(
            answer_mode=AnswerMode.RULE,
            category=QuestionCategory.PLATFORM_RULE,
            analysis_sources=[AnalysisSource.KNOWLEDGE],
        )
    )
    assert rule.data_rows is None


def test_empty_analysis_sources_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ChatResponse.model_validate(_base_response(analysis_sources=[]))


def test_none_cannot_be_combined_with_another_source() -> None:
    with pytest.raises(ValidationError, match="NONE"):
        ChatResponse.model_validate(
            _base_response(analysis_sources=[AnalysisSource.NONE, AnalysisSource.KNOWLEDGE])
        )


@pytest.mark.parametrize("mode", [AnswerMode.CHAT, AnswerMode.INVALID])
def test_chat_and_invalid_must_use_none_only(mode: AnswerMode) -> None:
    with pytest.raises(ValidationError, match="NONE"):
        ChatResponse.model_validate(
            _base_response(answer_mode=mode, analysis_sources=[AnalysisSource.KNOWLEDGE])
        )


def test_fallback_source_requires_degradation() -> None:
    with pytest.raises(ValidationError, match="FALLBACK"):
        ChatResponse.model_validate(
            _base_response(
                answer_mode=AnswerMode.RULE,
                analysis_sources=[AnalysisSource.FALLBACK],
                degraded=False,
            )
        )


def test_chat_response_allows_visible_degradation_when_llm_is_unavailable() -> None:
    response = ChatResponse.model_validate(
        _base_response(
            answer_mode=AnswerMode.CHAT,
            analysis_sources=[AnalysisSource.FALLBACK],
            degraded=True,
            degraded_reason="LLM 未配置或暂不可用",
            quality_status=QualityStatus.DEGRADED,
        )
    )

    assert response.degraded is True


def test_degraded_answer_must_explain_why() -> None:
    with pytest.raises(ValidationError, match="degraded_reason"):
        ChatResponse.model_validate(_metric_response(degraded_reason=None))


def test_non_degraded_answer_must_not_carry_a_reason() -> None:
    with pytest.raises(ValidationError, match="degraded_reason"):
        ChatResponse.model_validate(_base_response(degraded_reason="不该出现"))


# --- 质量状态 -----------------------------------------------------------


def test_quality_attempts_supports_up_to_three_attempts() -> None:
    assert ChatResponse.model_validate(_base_response(quality_attempts=3)).quality_attempts == 3


@pytest.mark.parametrize("attempts", [-1, 4])
def test_quality_attempts_outside_zero_to_three_is_rejected(attempts: int) -> None:
    with pytest.raises(ValidationError):
        ChatResponse.model_validate(_base_response(quality_attempts=attempts))


def test_quality_notes_default_to_an_empty_list_not_null() -> None:
    payload = _base_response()
    payload.pop("quality_notes")

    assert ChatResponse.model_validate(payload).quality_notes == []


# --- 按模式必填 ---------------------------------------------------------


@pytest.mark.parametrize(
    "missing",
    [
        "metric_code",
        "metric_display_name",
        "metric_unit",
        "metric_definition",
        "metric_sql_definition",
        "metric_dimensions",
        "metric_source_database",
        "metric_source_table",
        "metric_source",
        "metric_generated",
        "metric_owner",
        "metric_status",
        "visualization",
        "query_plan",
        "data_rows",
        "total_rows",
        "truncated",
    ],
)
def test_metric_requires_every_metric_field(missing: str) -> None:
    with pytest.raises(ValidationError, match=missing):
        ChatResponse.model_validate(_metric_response(**{missing: None}))


def test_metric_requires_complete_traceability_definition() -> None:
    """指标回答不能只给业务口径，必须给出完整的口径追溯信息。"""

    with pytest.raises(ValidationError, match="metric_sql_definition"):
        ChatResponse.model_validate(_metric_response(metric_sql_definition=None))


def test_metric_requires_at_least_two_recommendations() -> None:
    only_one = list(METRIC_FIELDS["recommendations"])[:1]  # type: ignore[call-overload]

    with pytest.raises(ValidationError, match="recommendations"):
        ChatResponse.model_validate(_metric_response(recommendations=only_one))


def test_detail_requires_export() -> None:
    payload = _metric_response(answer_mode=AnswerMode.DETAIL)
    payload.pop("export", None)

    with pytest.raises(ValidationError, match="export"):
        ChatResponse.model_validate(payload)


def test_detail_passes_once_export_is_present() -> None:
    response = ChatResponse.model_validate(
        _metric_response(
            answer_mode=AnswerMode.DETAIL,
            export={
                "id": str(uuid4()),
                "url": "https://example.test/exports/1",
                "expires_at": "2026-07-31T12:00:00Z",
            },
        )
    )

    assert response.answer_mode is AnswerMode.DETAIL


def test_table_only_detail_allows_an_empty_answer_without_recommendations() -> None:
    """纯明细只有表格；把它当成不完整响应会迫使 Agent 伪造分析正文。"""

    response = ChatResponse.model_validate(
        _metric_response(
            answer="",
            answer_mode=AnswerMode.DETAIL,
            export={
                "id": str(uuid4()),
                "url": "https://example.test/exports/1",
                "expires_at": "2026-07-31T12:00:00Z",
            },
            recommendations=[],
        )
    )

    assert response.answer == ""
    assert response.recommendations == []


@pytest.mark.parametrize("mode", [AnswerMode.CHAT, AnswerMode.METRIC, AnswerMode.RULE])
def test_non_detail_modes_reject_an_empty_answer(mode: AnswerMode) -> None:
    """非明细的空正文会让用户得到没有任何解释的回答卡片。"""

    with pytest.raises(ValidationError, match="answer"):
        ChatResponse.model_validate(_base_response(answer_mode=mode, answer=""))


def test_detail_with_analysis_text_still_requires_two_recommendations() -> None:
    """要求分析的明细不能借由放宽纯明细契约而丢掉行动建议。"""

    with pytest.raises(ValidationError, match="recommendations"):
        ChatResponse.model_validate(
            _metric_response(
                answer_mode=AnswerMode.DETAIL,
                export={
                    "id": str(uuid4()),
                    "url": "https://example.test/exports/1",
                    "expires_at": "2026-07-31T12:00:00Z",
                },
                recommendations=[],
            )
        )


def test_identity_requires_query_plan_and_rows_but_not_metric_fields() -> None:
    payload = _base_response(
        answer_mode=AnswerMode.IDENTITY,
        category="TRADE",
        analysis_sources=[AnalysisSource.DATABASE],
        query_plan={"summary": "演示查询计划"},
        data_rows=[{"order_id": "A1"}],
        total_rows=1,
        truncated=False,
    )

    assert ChatResponse.model_validate(payload).metric_code is None

    payload.pop("query_plan")
    with pytest.raises(ValidationError, match="query_plan"):
        ChatResponse.model_validate(payload)


def test_response_has_no_conversation_id_alias() -> None:
    """§8.2 强调只有 session_id，不存在 conversation_id。"""

    assert "conversation_id" not in ChatResponse.model_fields
    assert "session_id" in ChatResponse.model_fields


# --- 业务分类 -----------------------------------------------------------

# 逐字对照参考实现 model/QuestionCategory.java，顺序与其枚举声明一致。
REFERENCE_CATEGORIES = [
    ("PLATFORM_RULE", "平台商家规则"),
    ("TRADE", "电商交易"),
    ("REFUND", "电商退货"),
    ("CS_TICKET", "电商客服工单"),
    ("COMPENSATION", "电商理赔/赔付"),
    ("COUPON", "电商优惠券"),
    ("GOODS", "商品管理"),
    ("MERCHANT_OTHER", "商家其他信息"),
    ("IDENTITY", "身份信息"),
    ("SCM", "供应链"),
    ("UNKNOWN", "未知"),
]


def test_question_category_matches_the_reference_enum() -> None:
    """业务域 1:1 照搬参考实现，缺一个都会让 B3 的意图分类对不上。"""

    assert [member.value for member in QuestionCategory] == [
        value for value, _ in REFERENCE_CATEGORIES
    ]


def test_every_category_has_a_chinese_display_name() -> None:
    expected = {
        QuestionCategory(value): display_name for value, display_name in REFERENCE_CATEGORIES
    }

    assert expected == CATEGORY_DISPLAY_NAMES


def test_category_enum_values_are_ascii_codes_not_chinese() -> None:
    """枚举值是对外契约码，中文只能出现在 display name 里。"""

    for member in QuestionCategory:
        assert member.value.isascii()
        assert member.value == member.name


def test_response_rejects_a_category_outside_the_enum() -> None:
    with pytest.raises(ValidationError, match="category"):
        ChatResponse.model_validate(_base_response(category="NOT_A_CATEGORY"))


def test_response_accepts_every_reference_category() -> None:
    for member in QuestionCategory:
        response = ChatResponse.model_validate(
            _base_response(
                answer_mode=AnswerMode.RULE,
                category=member.value,
                analysis_sources=[AnalysisSource.KNOWLEDGE],
            )
        )
        assert response.category is member
