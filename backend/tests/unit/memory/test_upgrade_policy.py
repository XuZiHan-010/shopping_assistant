"""长期偏好准入：拦住任务限定、缩短证据和不受控键。"""

import json

import pytest

from app.core.session import SessionRole
from app.llm.client import LlmBudget, LlmMessage
from app.llm.fake import FakeLlmClient
from app.memory.extractor import MemoryExtractor


async def extract(source: str, value: str, evidence: str, **fields: str) -> list:
    fact = {
        "category": "偏好",
        "key": "颜色偏好",
        "value": value,
        "source_index": 0,
        "evidence": evidence,
        **fields,
    }
    return await MemoryExtractor().extract(
        [LlmMessage("user", source)],
        llm=FakeLlmClient(responses=[json.dumps({"facts": [fact]}, ensure_ascii=False)]),
        budget=LlmBudget(max_calls=1, max_tokens=4000),
    )


@pytest.mark.parametrize(
    ("source", "value", "evidence"),
    [
        ("这次我要彩色款，以前喜欢素色", "彩色款", "彩色款"),
        ("今天只买蓝色", "蓝色", "蓝色"),
        ("这次送人，选修身款", "修身款", "修身款"),
        ("这次我想试试平时没穿过的蓝色", "蓝色", "蓝色"),
        ("For this order I prefer blue", "prefer blue", "prefer blue"),
        ("This is a gift, I prefer blue for this purchase", "prefer blue", "prefer blue"),
    ],
)
async def test_task_qualification_cannot_be_removed_by_shortening_evidence(
    source: str,
    value: str,
    evidence: str,
) -> None:
    assert await extract(source, value, evidence) == []


@pytest.mark.parametrize(
    ("category", "key"),
    [("偏好", "颜色偏好"), ("preference", "colour"), ("颜色", "color")],
)
async def test_aliases_produce_one_canonical_color_identity(category: str, key: str) -> None:
    facts = await extract("我平时喜欢蓝色", "喜欢蓝色", "喜欢蓝色", category=category, key=key)
    assert [(fact.category, fact.key) for fact in facts] == [("appearance", "color")]


async def test_unknown_preference_key_is_not_persistable() -> None:
    assert await extract("我喜欢蓝色", "喜欢蓝色", "喜欢蓝色", key="arbitrary_sql") == []


async def test_stable_clause_is_kept_separately_from_this_purchase() -> None:
    facts = await extract("这次送人选修身款，但我平时喜欢蓝色", "喜欢蓝色", "喜欢蓝色")
    assert [fact.value for fact in facts] == ["喜欢蓝色"]


async def test_explicit_long_term_change_from_today_is_kept() -> None:
    facts = await extract("从今天起一直喜欢蓝色", "喜欢蓝色", "喜欢蓝色")
    assert [fact.value for fact in facts] == ["喜欢蓝色"]


async def test_model_session_scope_is_not_promoted_to_long_term() -> None:
    assert await extract("我喜欢蓝色", "喜欢蓝色", "喜欢蓝色", scope="SESSION") == []


async def test_model_long_term_claim_does_not_override_task_qualification() -> None:
    assert await extract("这次只要蓝色", "只要蓝色", "只要蓝色", scope="LONG_TERM") == []


@pytest.mark.parametrize("key", ["detail", "详略"])
async def test_merchant_aliases_are_normalized_to_presentation(key: str) -> None:
    facts = await MemoryExtractor().extract(
        [LlmMessage("user", "以后回答简短些")],
        llm=FakeLlmClient(
            responses=[
                json.dumps(
                    {
                        "facts": [
                            {
                                "category": "呈现",
                                "key": key,
                                "value": "回答简短些",
                                "source_index": 0,
                                "evidence": "回答简短些",
                            }
                        ]
                    },
                    ensure_ascii=False,
                )
            ]
        ),
        budget=LlmBudget(max_calls=1, max_tokens=4000),
        role=SessionRole.MERCHANT,
    )
    assert [(fact.category, fact.key) for fact in facts] == [("presentation", "detail")]


async def test_merchant_cannot_store_customer_profile_key() -> None:
    facts = await MemoryExtractor().extract(
        [LlmMessage("user", "我喜欢蓝色")],
        llm=FakeLlmClient(
            responses=[
                json.dumps(
                    {
                        "facts": [
                            {
                                "category": "偏好",
                                "key": "color",
                                "value": "喜欢蓝色",
                                "source_index": 0,
                                "evidence": "喜欢蓝色",
                            }
                        ]
                    },
                    ensure_ascii=False,
                )
            ]
        ),
        budget=LlmBudget(max_calls=1, max_tokens=4000),
        role=SessionRole.MERCHANT,
    )
    assert facts == []


async def test_confirmation_of_one_time_question_is_not_saved() -> None:
    facts = await MemoryExtractor().extract(
        [LlmMessage("assistant", "这次要蓝色吗？"), LlmMessage("user", "是的")],
        llm=FakeLlmClient(
            responses=[
                json.dumps(
                    {
                        "facts": [
                            {
                                "category": "偏好",
                                "key": "color",
                                "value": "要蓝色",
                                "source_index": 1,
                                "evidence": "是的",
                            }
                        ]
                    },
                    ensure_ascii=False,
                )
            ]
        ),
        budget=LlmBudget(max_calls=1, max_tokens=4000),
    )
    assert facts == []


@pytest.mark.parametrize(
    ("role", "category", "key", "value"),
    [
        (SessionRole.CUSTOMER, "appearance", "color", "库存还有8件"),
        (SessionRole.MERCHANT, "presentation", "detail", "昨天销售额199元"),
        (SessionRole.MERCHANT, "presentation", "detail", "店铺规则是七天无理由退货"),
        (SessionRole.MERCHANT, "presentation", "detail", "订单123已发货"),
        (SessionRole.MERCHANT, "presentation", "tone", "所有商品均不支持退货"),
        (SessionRole.MERCHANT, "presentation", "structure", "先批准草稿再扣减库存"),
    ],
)
async def test_business_fact_cannot_be_saved_by_labeling_it_as_preference(
    role: SessionRole,
    category: str,
    key: str,
    value: str,
) -> None:
    facts = await MemoryExtractor().extract(
        [LlmMessage("user", value)],
        llm=FakeLlmClient(
            responses=[
                json.dumps(
                    {
                        "facts": [
                            {
                                "category": category,
                                "key": key,
                                "value": value,
                                "source_index": 0,
                                "evidence": value,
                            }
                        ]
                    },
                    ensure_ascii=False,
                )
            ]
        ),
        budget=LlmBudget(max_calls=1, max_tokens=4000),
        role=role,
    )
    assert facts == []


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("tone", "回复语气正式"),
        ("detail", "回答简洁"),
        ("structure", "回答先给结论再列明细"),
        ("language", "回答使用中文"),
    ],
)
async def test_merchant_presentation_preferences_still_work(key: str, value: str) -> None:
    facts = await MemoryExtractor().extract(
        [LlmMessage("user", f"以后{value}")],
        llm=FakeLlmClient(
            responses=[
                json.dumps(
                    {
                        "facts": [
                            {
                                "category": "presentation",
                                "key": key,
                                "value": value,
                                "source_index": 0,
                                "evidence": value,
                            }
                        ]
                    },
                    ensure_ascii=False,
                )
            ]
        ),
        budget=LlmBudget(max_calls=1, max_tokens=4000),
        role=SessionRole.MERCHANT,
    )
    assert [fact.value for fact in facts] == [value]
