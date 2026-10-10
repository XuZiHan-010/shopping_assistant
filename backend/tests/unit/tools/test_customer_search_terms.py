"""商品搜索的英文 → 中文检索词表（2026-10-10 整改；真实评测 QLT-N5-007）。"""

from __future__ import annotations

import pytest

from app.analytics.demo_data import _DEMO_PRODUCTS
from app.tools.customer.search_terms import MAX_EXPANSIONS, has_english, zh_search_terms

_TITLES = tuple(product.title for product in _DEMO_PRODUCTS)


def _matches(query: str) -> list[str]:
    terms = zh_search_terms(query)
    return [title for title in _TITLES if any(term in title for term in terms)]


@pytest.mark.parametrize(
    ("query", "expected_title"),
    [
        ("shoes", "复古德训运动鞋"),
        ("Shoes for commuting", "软底乐福鞋"),
        ("sneakers", "复古德训运动鞋"),
        ("boots", "防泼水徒步短靴"),
        ("chelsea boots", "手工缝线切尔西靴"),
        ("loafers", "软底乐福鞋"),
        ("scarf", "格纹羊绒围巾"),
        ("scarves", "格纹羊绒围巾"),
        ("sweater", "羊毛混纺高领毛衣"),
        ("knit cardigan", "美利奴羊毛针织开衫"),
        ("dresses", "法式碎花连衣裙"),
        ("jeans", "高腰直筒牛仔裤"),
        ("candle", "无花果雪松香氛蜡烛"),
        ("perfume", "苦橙花淡香水"),
        ("face cream", "燕麦舒缓保湿面霜"),
        ("linen", "亚麻宽松开衫"),
        ("cutting board", "橡木砧板"),
    ],
)
def test_common_english_words_reach_the_demo_catalog(query: str, expected_title: str) -> None:
    assert expected_title in _matches(query)


def test_chinese_queries_are_left_alone() -> None:
    assert zh_search_terms("围巾 羊绒") == ()
    assert has_english("围巾") is False and has_english("T恤") is True


def test_unknown_english_word_expands_to_nothing() -> None:
    assert zh_search_terms("zyzzyva") == ()


def test_word_boundaries_are_respected() -> None:
    assert zh_search_terms("shoelaces") == ()  # 不是「shoe」


def test_category_words_are_only_a_fallback() -> None:
    """「women」会命中全部女装：有具体商品词时不用它，免得把商品挤出结果。"""

    assert zh_search_terms("women") == ("女装",)
    assert zh_search_terms("women shoes") == ("鞋",)


def test_expansion_is_deduplicated_and_bounded() -> None:
    terms = zh_search_terms("sweater jumper knit knitwear pullover")

    assert terms == ("毛衣", "针织")
    everything = zh_search_terms(
        "shoes boots loafers shirt sweater cardigan jacket coat jeans skirt dress scarf hat bag"
    )
    assert len(everything) == MAX_EXPANSIONS == len(set(everything))


@pytest.mark.parametrize(
    ("query", "expected_title"),
    [
        ("外套", "水洗帆布工装夹克"),
        ("秋天 外套 针织衫", "美利奴羊毛针织开衫"),
        ("裤子 长裤", "高腰直筒牛仔裤"),
        ("裤子", "修身斜纹休闲裤"),
        ("上衣", "牛津纺长袖衬衫"),
        ("靴子", "防泼水徒步短靴"),
        ("护肤", "燕麦舒缓保湿面霜"),
        ("香薰", "无花果雪松香氛蜡烛"),
    ],
)
def test_chinese_everyday_words_reach_the_demo_catalog(query: str, expected_title: str) -> None:
    """2026-10-10 真实复测：搜「外套」找不到「夹克」，助手告诉顾客本店没有。"""

    assert expected_title in _matches(query)


def test_chinese_synonyms_combine_with_english_words() -> None:
    assert zh_search_terms("外套 shoes") == ("夹克", "开衫", "大衣", "鞋")
    assert zh_search_terms("裤子 women") == ("裤", "女装")  # 中文近义词不挤掉英文品类词的兜底
