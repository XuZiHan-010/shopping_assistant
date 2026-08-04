"""业务域常量的可用行为。"""

from __future__ import annotations

import pytest

from app.knowledge.domains import (
    DOMAIN_KEYWORDS,
    DOMAIN_TABLES,
    INDEX_PATH_MARKERS,
    MAX_KNOWLEDGE_CHARS,
    MAX_PROMPT_KNOWLEDGE_CHARS,
    merchant_filter_key,
)
from app.schemas.chat import QuestionCategory


def test_every_business_category_can_be_matched_by_non_empty_aliases() -> None:
    """别名缺失会导致相应业务问题无法进入正确的知识检索范围。"""

    for category in QuestionCategory:
        if category is QuestionCategory.UNKNOWN:
            continue
        assert DOMAIN_KEYWORDS[category]
        assert all(keyword.strip() for keyword in DOMAIN_KEYWORDS[category])


def test_merchant_filter_key_preserves_b4_merchant_isolation() -> None:
    """错误的过滤列会令 B4 查询跨商家泄漏。"""

    assert {merchant_filter_key(category) for category in QuestionCategory} == {"merchant_id"}


def test_platform_rules_do_not_route_to_data_tables() -> None:
    """平台规则只检索知识，不应被 B4 当成经营数据查询。"""

    assert DOMAIN_TABLES[QuestionCategory.PLATFORM_RULE] == ()


def test_domain_tables_match_b4_business_table_contract() -> None:
    assert DOMAIN_TABLES[QuestionCategory.TRADE] == ("orders", "order_items")
    assert DOMAIN_TABLES[QuestionCategory.REFUND] == ("refunds", "returns")
    assert DOMAIN_TABLES[QuestionCategory.CS_TICKET] == ("support_tickets",)
    assert DOMAIN_TABLES[QuestionCategory.GOODS] == ("products",)
    assert all(
        not table.endswith("_detail") for tables in DOMAIN_TABLES.values() for table in tables
    )


def test_domain_aliases_do_not_expose_the_legacy_brand() -> None:
    """新系统的词汇不能把旧品牌泄漏到用户可见的模型上下文。"""

    assert all(
        "yshopping" not in keyword.lower()
        for keywords in DOMAIN_KEYWORDS.values()
        for keyword in keywords
    )


@pytest.mark.parametrize("marker", ["index", "rule", "目录"])
def test_index_markers_select_the_three_knowledge_index_forms(marker: str) -> None:
    """遗漏任一标记会让分类阶段缺少应有的领域词汇。"""

    assert marker in INDEX_PATH_MARKERS


def test_prompt_knowledge_limit_is_stricter_than_retrieval_limit() -> None:
    """缺少第二次截断会让完整检索结果直接撑大模型上下文。"""

    assert MAX_PROMPT_KNOWLEDGE_CHARS < MAX_KNOWLEDGE_CHARS
