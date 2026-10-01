"""记忆、反馈与 MCP 白名单的传输边界，不访问数据库。"""

import pytest
from pydantic import ValidationError

from app.core.errors import ConfirmationRequiredError
from app.schemas.v2 import memory
from app.schemas.v2.memory import (
    MCP_PROTOCOL_VERSION,
    CustomerMemoriesResponse,
    CustomerMemoryItem,
    FeedbackKind,
    McpReadOnlyTool,
    MemoryLayer,
    MemoryPreferenceRequest,
    MemoryPreferenceResponse,
    MerchantMemoriesResponse,
    MerchantMemoryDeleteResponse,
    MerchantMemoryItem,
    V2FeedbackRequest,
    V2FeedbackResponse,
)

T0 = "2026-09-21T00:00:00Z"
T1 = "2027-03-20T00:00:00Z"


def customer_memory(**changes: object) -> dict[str, object]:
    return {
        "id": "m1",
        "shop_slug": "borough-100",
        "category": "偏好",
        "key": "颜色",
        "value": "蓝色",
        "last_confirmed_at": T0,
        "expires_at": T1,
        **changes,
    }


def fact(**changes: object) -> dict[str, object]:
    return {
        "id": "f1",
        "layer": "FACT",
        "category": "语气",
        "content": "回复简洁",
        "source_ref": {"conversation_id": "c1", "message_id": "m1"},
        "updated_at": T0,
        **changes,
    }


def summary(**changes: object) -> dict[str, object]:
    return {**fact(id="s1", layer="SUMMARY", source_ref=None), **changes}


def page(*items: dict[str, object]) -> dict[str, object]:
    return {"items": list(items), "next_cursor": None, "has_more": False}


def test_customer_memory_isolated_by_shop_without_raw_identifiers() -> None:
    fields = CustomerMemoryItem.model_fields
    assert {"shop_slug", "last_confirmed_at"} <= set(fields)
    assert "buyer_key" not in fields
    assert "merchant_id" not in fields
    assert CustomerMemoryItem.model_validate(customer_memory()).shop_slug == "borough-100"
    for extra in ("buyer_key", "merchant_id"):
        with pytest.raises(ValidationError):
            CustomerMemoryItem.model_validate(customer_memory(**{extra: "x"}))
    with pytest.raises(ValidationError):
        CustomerMemoryItem.model_validate(customer_memory(expires_at=T0))


def test_customer_memories_response_is_cursor_paged() -> None:
    response = CustomerMemoriesResponse.model_validate(
        {"memory_enabled": True, "memories": page(customer_memory())}
    )
    assert response.memories.has_more is False


def test_disabling_memory_requires_purge_confirmation() -> None:
    with pytest.raises(ConfirmationRequiredError):
        MemoryPreferenceRequest(enabled=False)
    ok = MemoryPreferenceRequest(enabled=False, purge_confirmation="yes")
    assert ok.purge_confirmation == "yes"
    with pytest.raises(ValidationError):
        MemoryPreferenceRequest.model_validate({"enabled": False, "purge_confirmation": "no"})


def test_enabling_memory_does_not_require_confirmation() -> None:
    """条件必填，不是无条件必填。"""
    assert MemoryPreferenceRequest(enabled=True).purge_confirmation is None
    with pytest.raises(ValidationError):
        MemoryPreferenceRequest(enabled=True, purge_confirmation="yes")


def test_preference_request_is_idempotent_by_state_and_rejects_extras() -> None:
    assert "client_request_id" not in MemoryPreferenceRequest.model_fields
    with pytest.raises(ValidationError):
        MemoryPreferenceRequest.model_validate({"enabled": True, "buyer_key": "k"})


def test_preference_response_reports_purge_only_when_disabled() -> None:
    assert MemoryPreferenceResponse(memory_enabled=False, purged_count=3).purged_count == 3
    assert MemoryPreferenceResponse(memory_enabled=True, purged_count=0)
    with pytest.raises(ValidationError):
        MemoryPreferenceResponse(memory_enabled=True, purged_count=1)


def test_fact_layer_requires_source_ref() -> None:
    with pytest.raises(ValidationError):
        MerchantMemoryItem.model_validate({"layer": "FACT", "content": "x"})
    with pytest.raises(ValidationError):
        MerchantMemoryItem.model_validate(fact(source_ref=None))
    assert MerchantMemoryItem.model_validate(fact()).layer == MemoryLayer.FACT


def test_summary_layer_is_a_rebuildable_document_without_source() -> None:
    assert MerchantMemoryItem.model_validate(summary()).source_ref is None
    with pytest.raises(ValidationError):
        MerchantMemoryItem.model_validate(
            summary(source_ref={"conversation_id": "c", "message_id": "m"})
        )


def test_merchant_memories_keep_layers_separate() -> None:
    assert MerchantMemoriesResponse.model_validate(
        {"facts": page(fact()), "summaries": [summary()]}
    )
    with pytest.raises(ValidationError):
        MerchantMemoriesResponse.model_validate({"facts": page(summary()), "summaries": []})
    with pytest.raises(ValidationError):
        MerchantMemoriesResponse.model_validate({"facts": page(), "summaries": [fact()]})
    with pytest.raises(ValidationError):
        MerchantMemoriesResponse.model_validate(
            {"facts": page(), "summaries": [summary(), summary(id="s2")]}
        )


def test_delete_response_reports_summary_rebuild() -> None:
    assert "summary_rebuild_scheduled" in MerchantMemoryDeleteResponse.model_fields
    assert MerchantMemoryDeleteResponse(deleted_id="f1", summary_rebuild_scheduled=True)


def test_memory_contract_has_no_promotion_to_team_knowledge() -> None:
    """团队知识与记忆是单向边界。"""
    all_fields = set(MerchantMemoryItem.model_fields) | set(CustomerMemoryItem.model_fields)
    assert not any("promote" in f or "team_knowledge" in f for f in all_fields)
    assert not any("promote" in name.lower() or "team" in name.lower() for name in dir(memory))


def test_feedback_adoption_and_reaction_do_not_overwrite_each_other() -> None:
    adoption = V2FeedbackRequest(client_request_id="r1", kind=FeedbackKind.ADOPTION, adopted=True)
    assert adoption.reaction is None
    reaction = V2FeedbackRequest(
        client_request_id="r2", kind=FeedbackKind.REACTION, reaction="LIKE"
    )
    assert reaction.adopted is None
    clear = V2FeedbackRequest(client_request_id="r3", kind=FeedbackKind.REACTION)
    assert clear.reaction is None


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "ADOPTION"},
        {"kind": "ADOPTION", "adopted": True, "reaction": "LIKE"},
        {"kind": "ADOPTION", "adopted": True, "reason": "好"},
        {"kind": "REACTION", "adopted": True, "reaction": "LIKE"},
        {"kind": "REACTION", "reason": "没有赞踩却带原因"},
        {"kind": "REACTION", "reaction": "DISLIKE", "reason": "   "},
        {"kind": "REACTION", "reaction": "LOVE"},
        {"kind": "REACTION", "reaction": "LIKE", "is_adopted": True},
    ],
)
def test_feedback_request_rejects_mixed_semantics(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        V2FeedbackRequest.model_validate({"client_request_id": "r1", **payload})


def test_feedback_requires_client_request_id_and_allows_optional_reason() -> None:
    with pytest.raises(ValidationError):
        V2FeedbackRequest.model_validate({"kind": "ADOPTION", "adopted": True})
    dislike = V2FeedbackRequest(
        client_request_id="r1", kind=FeedbackKind.REACTION, reaction="DISLIKE", reason=" 不准确 "
    )
    assert dislike.reason == "不准确"


def test_feedback_response_returns_both_current_states() -> None:
    ok = V2FeedbackResponse(
        answer_id="a1", adopted=True, reaction="LIKE", reason="好", updated_at=T0
    )
    assert ok.adopted and ok.reaction == "LIKE"
    with pytest.raises(ValidationError):
        V2FeedbackResponse(answer_id="a1", adopted=False, reaction=None, reason="好", updated_at=T0)


def test_mcp_protocol_version_is_pinned() -> None:
    assert MCP_PROTOCOL_VERSION == "2026-07-28"


def test_mcp_whitelist_is_read_only_and_excludes_side_effect_tools() -> None:
    names = {tool.value for tool in McpReadOnlyTool}
    assert names == {
        "query_metrics",
        "attribute_change",
        "get_inventory_alerts",
        "get_product_content",
        "list_coupons",
        "get_metric_definition",
        "search_rules",
    }
    assert not any(
        name.startswith(("draft_", "apply_", "create_", "regenerate_")) for name in names
    )
    assert not {"list_signals", "create_export", "regenerate_brief"} & names
