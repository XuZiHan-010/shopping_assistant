"""N3 阶段 C Task 3：商品内容起草工具（`draft_content_change`）。

只测参数校验与 `DraftProposal` 组装（不落库）：属性值三来源校验、缺失属性列为待补、
批次标识的确定性派生。落库路径（`DatabaseDraftSink._stage_content_change`）与
`ContentChangeHandler` 由集成测试覆盖。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.tools.merchant.content import (
    AttributeInput,
    DraftContentChangeArgs,
    derive_batch_id,
)


def test_attribute_source_type_restricted_to_three_values() -> None:
    with pytest.raises(ValidationError):
        AttributeInput(value="浙江", source_type="AI_GUESSED")


@pytest.mark.parametrize("source_type", ["MERCHANT_FILLED", "MERCHANT_STATED"])
def test_attribute_source_type_accepts_allowed_values(source_type: str) -> None:
    attr = AttributeInput(value="浙江", source_type=source_type)
    assert attr.source_type == source_type


def test_description_extract_requires_source_span() -> None:
    """D11②：从描述提取的属性必须指向原文片段，不能凭空声称"提取自描述"。"""

    with pytest.raises(ValidationError):
        AttributeInput(value="240ml", source_type="DESCRIPTION_EXTRACT", source_span=None)
    attr = AttributeInput(
        value="240ml", source_type="DESCRIPTION_EXTRACT", source_span="容量 240ml"
    )
    assert attr.source_span == "容量 240ml"


def test_merchant_filled_does_not_require_source_span() -> None:
    attr = AttributeInput(value="浙江", source_type="MERCHANT_FILLED", source_span=None)
    assert attr.source_span is None


def test_args_reject_empty_attributes() -> None:
    with pytest.raises(ValidationError):
        DraftContentChangeArgs(product_id="p1", attributes={})


def test_derive_batch_id_is_deterministic_for_same_key() -> None:
    """同一对话里用同一个批次标识起草多个商品，必须派生出相同的 batch_id。"""

    first = derive_batch_id(conversation_id="c1", batch_key="秋季女装补充")
    second = derive_batch_id(conversation_id="c1", batch_key="秋季女装补充")
    assert first == second


def test_derive_batch_id_differs_across_conversations() -> None:
    """不同对话即使用了同样的批次标识文字，也不能派生出同一个 batch_id——
    否则不同商家的两次批量起草可能撞成同一个批次（对话本身已经按会话隔离商家）。"""

    first = derive_batch_id(conversation_id="c1", batch_key="补充")
    second = derive_batch_id(conversation_id="c2", batch_key="补充")
    assert first != second


def test_derive_batch_id_differs_across_keys() -> None:
    first = derive_batch_id(conversation_id="c1", batch_key="批次A")
    second = derive_batch_id(conversation_id="c1", batch_key="批次B")
    assert first != second


def test_derive_batch_id_is_a_valid_uuid_string() -> None:
    from uuid import UUID

    value = derive_batch_id(conversation_id="c1", batch_key="x")
    UUID(value)  # 不抛异常即通过
