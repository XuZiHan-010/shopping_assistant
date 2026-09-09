"""`SupportedLocale` / `SourceLanguage` 解析与分类的单元测试。

覆盖 `docs/backend-development-plan.md` §8.6.1 的 Header 解析规则，以及
brief 明确要求的三条 `detect_source_language` 反例不变式：混合文本里的单个
汉字不构成"中文"误判、代码/URL/SQL/数字/空白不构成"英文"误判。

`test_detect_source_language_rejects_sql_as_english` 单独覆盖 review 发现的
一个具体回归：纯 SQL 语句（尤其是不含下划线/数字的裸表名、列名，如
`orders`、`id`、`name`）曾经被逐词剔除步骤漏判成英文单词，误分类为
`en-US`。
"""

from __future__ import annotations

import pytest

from app.localization.locales import (
    SQL_KEYWORDS,
    SourceLanguage,
    SupportedLocale,
    detect_source_language,
    parse_accept_language,
)


@pytest.mark.parametrize(
    ("header", "expected"),
    [(None, "zh-CN"), ("zh-CN", "zh-CN"), ("en-US", "en-US"), ("en;q=0.9", "en-US")],
)
def test_parse_accept_language(header: str | None, expected: str) -> None:
    assert parse_accept_language(header).value == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Gross merchandise value", SourceLanguage.EN_US),
        ("退款 GMV increased", SourceLanguage.MIXED),
        ("sku_001 https://example.com 123", SourceLanguage.UND),
    ],
)
def test_detects_content_language_without_mislabeling_invariants(
    text: str, expected: SourceLanguage
) -> None:
    assert detect_source_language(text) is expected


def test_supported_locale_only_has_two_members() -> None:
    """契约明确只允许两个显示语言，多一个都会让前端选择器出现未定义分支。"""

    assert {member.value for member in SupportedLocale} == {"zh-CN", "en-US"}


def test_source_language_has_four_members() -> None:
    assert {member.value for member in SourceLanguage} == {
        "zh-CN",
        "en-US",
        "mixed",
        "und",
    }


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("", "zh-CN"),
        ("fr-FR", "zh-CN"),
        ("fr-FR,en;q=0.8", "en-US"),
        ("zh-CN;q=0.4,en-US;q=0.9", "en-US"),
        ("en-US;q=0.4,zh-CN;q=0.9", "zh-CN"),
        ("EN-US", "en-US"),
        ("zh", "zh-CN"),
        ("en", "en-US"),
        ("zh-Hans", "zh-CN"),
    ],
)
def test_parse_accept_language_handles_weights_and_case(header: str, expected: str) -> None:
    assert parse_accept_language(header).value == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", SourceLanguage.UND),
        ("   ", SourceLanguage.UND),
        ("这是一段完整的中文说明，用于介绍退款流程。", SourceLanguage.ZH_CN),
        ("退", SourceLanguage.ZH_CN),
        ("A", SourceLanguage.UND),
        ("order_id_12345 https://a.example/x 2026-09-01", SourceLanguage.UND),
    ],
)
def test_detect_source_language_additional_cases(text: str, expected: SourceLanguage) -> None:
    assert detect_source_language(text) is expected


@pytest.mark.parametrize(
    "text",
    [
        # Review 提供的三个精确反例：大写、小写、带列名列表的 SELECT。
        "SELECT * FROM orders WHERE merchant_id = 1",
        "select * from orders where id=1",
        "SELECT id, name FROM merchant_profile",
        # 补充：混合大小写、带聚合函数的真实查询，验证不是靠碰巧只覆盖了
        # 三个给定字符串——`count`/`from`/`where` 大小写各不相同。
        "Select COUNT(*) from Orders Where merchant_id = 1",
        # 补充：纯小写、SQL 关键字（sum/count/avg 等）需要不分大小写剔除。
        "select sum(amount) from orders",
    ],
)
def test_detect_source_language_rejects_sql_as_english(text: str) -> None:
    """纯 SQL 语句（含裸表名/列名）不得被误判为 `en-US`。"""

    assert detect_source_language(text) is SourceLanguage.UND


def test_sql_keywords_is_the_single_shared_source() -> None:
    """全分支复审 Finding 2：`app.services.localization_service` 过去独立
    维护了一份 `_SQL_KEYWORDS`，与这里的表各自漂移过（一份有 `DROP`/`TABLE`
    没有 `AS`/`AND`/`OR`，另一份反过来）。合并后 `localization_service` 直接
    从这里 `import SQL_KEYWORDS` 复用同一个对象，不再有第二份定义可以漂移——
    这里用对象恒等断言钉死"只有一份定义"，而不是比较两份取值是否恰好相等
    （那样即使又长出一份拷贝，只要凑巧取值相同也测不出来）。"""

    from app.services import localization_service

    assert localization_service.SQL_KEYWORDS is SQL_KEYWORDS
    assert not hasattr(localization_service, "_SQL_KEYWORDS")
    # 并集覆盖：两份历史拷贝各自独有的关键字都必须在合并后的表里出现。
    assert {"AS", "AND", "OR", "DROP", "TABLE"} <= SQL_KEYWORDS
