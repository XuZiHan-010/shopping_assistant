"""确定性词典的零 LLM 查找行为。"""

from __future__ import annotations

from app.localization.catalog import localize_catalog_value
from app.localization.locales import SupportedLocale


def test_catalog_localizes_status_without_llm() -> None:
    assert localize_catalog_value("PAID", SupportedLocale.EN_US) == "Paid"
    assert localize_catalog_value("退款金额", SupportedLocale.EN_US) == "Refund amount"


def test_catalog_returns_none_for_unknown_value() -> None:
    """未登记的自由文本必须缺席，让调用方走 LLM 批量翻译路径。"""

    assert localize_catalog_value("今天天气怎么样", SupportedLocale.EN_US) is None
    assert localize_catalog_value("今天天气怎么样", SupportedLocale.ZH_CN) is None


def test_catalog_hit_returns_original_value_for_zh_cn_target() -> None:
    """目标语言与词典 key 的原生语言一致时原样返回，不额外改写。"""

    assert localize_catalog_value("退款金额", SupportedLocale.ZH_CN) == "退款金额"
    assert localize_catalog_value("PAID", SupportedLocale.ZH_CN) == "PAID"


def test_catalog_covers_contract_metric_and_dimension_labels() -> None:
    """抄自 backend/app/analytics/contract.py 的指标/维度展示名。"""

    assert localize_catalog_value("成交 GMV", SupportedLocale.EN_US) == "Transaction GMV"
    assert localize_catalog_value("退货率", SupportedLocale.EN_US) == "Return rate"
    assert localize_catalog_value("订单状态", SupportedLocale.EN_US) == "Order status"
    assert localize_catalog_value("退货件数", SupportedLocale.EN_US) == "Return quantity"


def test_catalog_covers_units() -> None:
    assert localize_catalog_value("元", SupportedLocale.EN_US) == "yuan"
    assert localize_catalog_value("件", SupportedLocale.EN_US) == "items"
    assert localize_catalog_value("人", SupportedLocale.EN_US) == "users"


def test_catalog_covers_field_comment_business_definitions() -> None:
    """抄自 backend/app/metrics/field_comments.py 的整句字段注释。"""

    assert (
        localize_catalog_value("订单主键数量。", SupportedLocale.EN_US)
        == "Count of order primary keys."
    )


def test_catalog_covers_metric_catalog_generated_notice_and_owner_literals() -> None:
    """抄自 backend/app/metrics/catalog.py 的生成口径提示语与 owner 字面量。"""

    from app.metrics.catalog import GENERATED_NOTICE

    translated = localize_catalog_value(GENERATED_NOTICE, SupportedLocale.EN_US)
    assert translated is not None
    assert "for reference only" in translated
    assert localize_catalog_value("字段注释", SupportedLocale.EN_US) == "Field comment"
    assert localize_catalog_value("待认领", SupportedLocale.EN_US) == "Unclaimed"


def test_catalog_covers_category_display_names() -> None:
    """实际来源是 backend/app/schemas/chat.py 的 CATEGORY_DISPLAY_NAMES，
    不是任务描述里写的 backend/app/intent/models.py（后者没有中文展示名常量）。"""

    from app.schemas.chat import CATEGORY_DISPLAY_NAMES

    for display_name in CATEGORY_DISPLAY_NAMES.values():
        assert localize_catalog_value(display_name, SupportedLocale.EN_US) is not None
    assert localize_catalog_value("电商交易", SupportedLocale.EN_US) == "E-commerce trade"


def test_catalog_covers_quality_loop_degrade_messages() -> None:
    assert (
        localize_catalog_value("达到最大重试次数，使用确定性降级结果", SupportedLocale.EN_US)
        == "Maximum retry count reached; using the deterministic fallback result."
    )


def test_catalog_covers_rate_limit_message() -> None:
    """实际来源是 backend/app/core/errors.py 的 RateLimitedError，
    不是任务描述里写的 backend/app/core/rate_limit.py（后者不含任何字符串常量）。"""

    assert (
        localize_catalog_value("请求过于频繁，请稍后重试", SupportedLocale.EN_US)
        == "Too many requests, please try again later."
    )


def test_catalog_covers_prefilter_rejection_message() -> None:
    from app.agent.graph import _PREFILTER_REJECTION_MESSAGE

    translated = localize_catalog_value(_PREFILTER_REJECTION_MESSAGE, SupportedLocale.EN_US)
    assert translated is not None
    assert "Borough Merchant AI Assistant" in translated


def test_catalog_covers_demo_data_categories_reasons_and_cities() -> None:
    assert localize_catalog_value("女装", SupportedLocale.EN_US) == "Women's wear"
    assert localize_catalog_value("尺码不合适", SupportedLocale.EN_US) == "Wrong size"
    assert localize_catalog_value("与描述不符", SupportedLocale.EN_US) == "Not as described"
    assert localize_catalog_value("物流查询", SupportedLocale.EN_US) == "Logistics inquiry"
    assert localize_catalog_value("杭州市", SupportedLocale.EN_US) == "Hangzhou"


def test_catalog_beautifies_closed_set_status_codes() -> None:
    assert localize_catalog_value("NOT_RUN", SupportedLocale.EN_US) == "Not Run"
    assert localize_catalog_value("AI_GENERATED", SupportedLocale.EN_US) == "AI Generated"
    assert localize_catalog_value("REFUNDED", SupportedLocale.EN_US) == "Refunded"
    assert localize_catalog_value("ONLINE", SupportedLocale.EN_US) == "Online"


def test_catalog_module_does_not_import_any_llm_client() -> None:
    """确定性词典查找路径不依赖任何 LLM 客户端类型，物理上不可能发起调用。"""

    from app.localization import catalog as catalog_module

    assert not any(name.startswith("Llm") for name in dir(catalog_module))
    imported_modules = {
        value.__name__
        for value in vars(catalog_module).values()
        if isinstance(value, type(catalog_module))
    }
    assert not any(name.startswith("app.llm") for name in imported_modules)
