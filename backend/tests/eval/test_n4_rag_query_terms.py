"""v2 规则检索的集外口语与跨语言改写；只读种子，零 LLM。"""

import pytest

from app.eval.rag_e5 import search_rules_retriever


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("买家说东西损坏要求赔偿", "业务/理赔赔付/业务流程/理赔赔付业务流程图.md"),
        ("新款挂上去之前需要审核什么", "业务/商品/业务流程/商品业务流程图.md"),
        ("新品发布需要哪些审核", "业务/商品/业务流程/商品业务流程图.md"),
        ("Can merchants appeal penalties?", "业务/商家其他/业务流程/商家其他业务流程图.md"),
        (
            "Explain coupon redemption and settlement steps",
            "业务/优惠券/业务流程/优惠券业务流程图.md",
        ),
    ],
)
async def test_business_paraphrases_retrieve_existing_process(query: str, expected: str) -> None:
    ranked, matched = await search_rules_retriever(query)
    assert matched
    assert expected in ranked


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "挂上去的壁画掉了",
        "这幅画很有 appeal",
        "penalty shootout tactics",
        "redemption arc in a novel",
        "settlement on Mars",
    ],
)
async def test_unrelated_vocabulary_does_not_create_rule_matches(query: str) -> None:
    ranked, matched = await search_rules_retriever(query)
    assert not matched
    assert not ranked


def test_alias_expansion_does_not_split_identifiers() -> None:
    from app.agent.prefilter import tokenize
    from app.knowledge.query_terms import rule_query_terms

    query = "appeal_id penalty_code coupon_redemption settlement_id"
    assert rule_query_terms(query) == tokenize(query)
