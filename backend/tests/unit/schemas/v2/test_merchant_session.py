"""商家会话与对话目录的传输边界，不访问数据库或模型。"""

import pytest
from pydantic import ValidationError

from app.schemas.v2 import merchant_session as m
from app.schemas.v2 import shop_session as s
from app.schemas.v2.merchant_session import (
    MerchantAnswerMode,
    MerchantChatRequest,
    MerchantChatResponse,
    MerchantConversationMessage,
    MerchantSessionCreateRequest,
    MerchantSessionCreateResponse,
)

TOKEN = "a" * 43


def chat_response(**changes: object) -> dict[str, object]:
    return {
        "id": "a1",
        "conversation_id": "c1",
        "answer": "你好",
        "answer_mode": "CHAT",
        "analysis_sources": [{"source": "NONE", "degraded": False, "degraded_reason": None}],
        "quality_status": "NOT_RUN",
        "quality_attempts": 0,
        "degraded": False,
        "degraded_reason": None,
        "tool_calls": [],
        "created_at": "2026-09-21T00:00:00Z",
        **changes,
    }


@pytest.mark.parametrize("field", ["merchant_id", "token", "buyer_key"])
def test_session_create_request_is_empty_body(field: str) -> None:
    assert MerchantSessionCreateRequest().model_dump() == {}
    with pytest.raises(ValidationError):
        MerchantSessionCreateRequest.model_validate({field: "x"})


def test_session_response_exposes_display_name_not_id() -> None:
    fields = MerchantSessionCreateResponse.model_fields
    assert set(fields) == {"session_id", "role", "expires_at", "merchant_display_name"}
    assert "merchant_id" not in fields


def test_session_response_role_is_merchant_and_credential_is_high_entropy() -> None:
    base = {
        "session_id": TOKEN,
        "role": "MERCHANT",
        "expires_at": "2026-09-22T00:00:00Z",
        "merchant_display_name": "Borough商家100",
    }
    assert MerchantSessionCreateResponse.model_validate(base).role == "MERCHANT"
    for changes in [{"role": "CUSTOMER"}, {"session_id": "uuid"}, {"merchant_display_name": ""}]:
        with pytest.raises(ValidationError):
            MerchantSessionCreateResponse.model_validate({**base, **changes})


def test_answer_mode_drops_attachment() -> None:
    assert {item.value for item in MerchantAnswerMode} == {
        "METRIC",
        "DETAIL",
        "RULE",
        "IDENTITY",
        "CHAT",
        "INVALID",
    }


def test_chat_request_requires_client_request_id_and_defaults_new_thread() -> None:
    with pytest.raises(ValidationError):
        MerchantChatRequest.model_validate({"message": "今天销售额"})
    request = MerchantChatRequest(message=" 今天销售额 ", client_request_id="r1")
    assert request.conversation_id is None
    assert request.message == "今天销售额"
    with pytest.raises(ValidationError):
        MerchantChatRequest(message="  ", client_request_id="r1")


@pytest.mark.parametrize("field", ["session_id", "attachment_ids", "merchant_id", "buyer_key"])
def test_chat_request_rejects_untrusted_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        MerchantChatRequest.model_validate(
            {"message": "今天销售额", "client_request_id": "r1", field: []}
        )


def test_chat_response_has_no_session_and_enforces_none_source() -> None:
    assert "session_id" not in MerchantChatResponse.model_fields
    assert MerchantChatResponse.model_validate(chat_response()).answer == "你好"
    metric_source = [{"source": "DATABASE", "degraded": False, "degraded_reason": None}]
    with pytest.raises(ValidationError):
        MerchantChatResponse.model_validate(chat_response(analysis_sources=metric_source))
    assert (
        MerchantChatResponse.model_validate(
            chat_response(answer_mode="METRIC", analysis_sources=metric_source)
        ).answer_mode
        == "METRIC"
    )
    with pytest.raises(ValidationError):
        MerchantChatResponse.model_validate(chat_response(answer_mode="ATTACHMENT"))


def test_history_messages_carry_final_answer_only_for_assistant() -> None:
    base = {"id": "m1", "created_at": "2026-09-21T00:00:00Z"}
    assert MerchantConversationMessage.model_validate(
        {**base, "role": "user", "content": "你好", "answer": None, "feedback": None}
    )
    assistant = MerchantConversationMessage.model_validate(
        {
            **base,
            "role": "assistant",
            "content": "你好",
            "answer": chat_response(),
            "feedback": {"adopted": True, "reaction": "DISLIKE", "reason": "不准确"},
        }
    )
    assert assistant.feedback is not None
    assert assistant.feedback.adopted is True
    assert assistant.feedback.reason == "不准确"
    with pytest.raises(ValidationError):
        MerchantConversationMessage.model_validate(
            {**base, "role": "assistant", "content": "你好", "answer": chat_response()}
        )
    with pytest.raises(ValidationError):
        MerchantConversationMessage.model_validate(
            {
                **base,
                "role": "user",
                "content": "你好",
                "answer": None,
                "feedback": {"adopted": False, "reaction": None, "reason": None},
            }
        )
    with pytest.raises(ValidationError):
        MerchantConversationMessage.model_validate(
            {**base, "role": "user", "content": "你好", "answer": chat_response()}
        )
    with pytest.raises(ValidationError):
        MerchantConversationMessage.model_validate(
            {**base, "role": "assistant", "content": "其他", "answer": chat_response()}
        )


def test_conversation_summary_matches_shop_and_leaks_no_identity() -> None:
    """两端目录摘要字段对称，且都不含租户或顾客标识。"""
    shop_fields = set(s.ShopConversationSummary.model_fields)
    merchant_fields = set(m.MerchantConversationSummary.model_fields)
    assert shop_fields ^ merchant_fields == set()
    assert not ({"merchant_id", "buyer_key"} & (shop_fields | merchant_fields))
