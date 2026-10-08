"""回答的叙述语言是否与显示语言一致：确定性判定，不交给 LLM 裁判。

2026-10-07 真实对照里，LLM 裁判三票一致把英文显示下的中文回答判成「语言通过」，
下一轮又把英文回答判成「叙述语言为中文」。下面的样本取自那两轮的真实回答。
"""

from __future__ import annotations

import pytest

from app.eval.graders.language import narrative_matches_locale

CHINESE_WITH_CODES = (
    "今天（2026-10-07）的净成交额是 **¥12,923.00**。\n\n"
    "- 数据来源：实时（REALTIME），截至 2026-10-07\n"
    "- 指标口径：净成交额（net_gmv），定义版本 n3-metric-caliber-v1"
)
CHINESE_SHORT = (
    "昨天（2026-10-06）的总 GMV 是 **¥10,607.00**。\n\n数据来源：实时口径，数据截至 2026-10-06。"
)
ENGLISH_WITH_CODES = (
    "Today's (2026-10-07) net sales figure:\n\n- **Net GMV: 12,923.00**\n"
    "- Metric: `net_gmv` · Source: realtime · Data cutoff: 2026-10-07 · "
    "Definition version: n3-metric-caliber-v1"
)
ENGLISH_WITH_CHINESE_PRODUCT_NAME = (
    "Your best seller this week is 亚麻宽松开衫, with 12 units sold and no stock alerts."
)


@pytest.mark.parametrize(
    ("answer", "locale", "expected"),
    [
        (CHINESE_SHORT, "en-US", False),
        (CHINESE_SHORT, "zh-CN", True),
        (CHINESE_WITH_CODES, "zh-CN", True),
        (CHINESE_WITH_CODES, "en-US", False),
        (ENGLISH_WITH_CODES, "en-US", True),
        (ENGLISH_WITH_CODES, "zh-CN", False),
        (ENGLISH_WITH_CHINESE_PRODUCT_NAME, "en-US", True),
        ("Structured understanding complete.", "en-US", True),
        ("已完成结构化理解。", "en-US", False),
    ],
)
def test_narrative_language_is_compared_with_the_display_locale(
    answer: str, locale: str, expected: bool
) -> None:
    assert narrative_matches_locale(answer, locale) is expected


def test_answer_with_no_narrative_text_has_nothing_to_contradict() -> None:
    assert narrative_matches_locale("¥12,923.00", "en-US") is True
    assert narrative_matches_locale("", "zh-CN") is True
