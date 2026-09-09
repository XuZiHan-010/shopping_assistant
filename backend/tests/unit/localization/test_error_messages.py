"""稳定错误码到双语提示的映射测试。

保证异常处理器改造后不会出现"英语响应直接复用中文原句"或
"某个错误码漏配双语文案"的回归——`docs/backend-development-plan.md` §8.6.1
明确禁止前者，后者会在生产环境表现为英文用户看到中文错误提示。
"""

from __future__ import annotations

import re

from app.core.errors import ErrorCode
from app.localization.error_messages import (
    localize_error_message,
    localize_validation_detail_message,
)
from app.localization.locales import SupportedLocale

_HAN_PATTERN = re.compile(r"[一-鿿]")


def contains_han(text: str) -> bool:
    return bool(_HAN_PATTERN.search(text))


def test_every_error_code_has_a_bilingual_message() -> None:
    """每个稳定错误码都必须同时有中英文文案，且互不相同、不互相污染。"""

    for code in ErrorCode:
        zh_message = localize_error_message(code, {}, SupportedLocale.ZH_CN)
        en_message = localize_error_message(code, {}, SupportedLocale.EN_US)

        assert zh_message, f"{code} 缺少中文文案"
        assert en_message, f"{code} 缺少英文文案"
        assert contains_han(zh_message), f"{code} 的中文文案不含汉字：{zh_message!r}"
        assert not contains_han(en_message), f"{code} 的英文文案混入了汉字：{en_message!r}"
        assert zh_message != en_message


def test_auth_required_localizes_by_audience() -> None:
    merchant_en = localize_error_message(
        ErrorCode.AUTH_REQUIRED, {"audience": "merchant"}, SupportedLocale.EN_US
    )
    admin_en = localize_error_message(
        ErrorCode.AUTH_REQUIRED, {"audience": "admin"}, SupportedLocale.EN_US
    )

    assert merchant_en != admin_en
    assert not contains_han(merchant_en)
    assert not contains_han(admin_en)

    merchant_zh = localize_error_message(
        ErrorCode.AUTH_REQUIRED, {"audience": "merchant"}, SupportedLocale.ZH_CN
    )
    admin_zh = localize_error_message(
        ErrorCode.AUTH_REQUIRED, {"audience": "admin"}, SupportedLocale.ZH_CN
    )
    assert merchant_zh != admin_zh


def test_auth_required_without_audience_param_still_renders() -> None:
    """老调用点不传 `audience` 时仍要渲染出完整句子，不留下未替换的占位符。"""

    message = localize_error_message(ErrorCode.AUTH_REQUIRED, {}, SupportedLocale.EN_US)

    assert "{audience}" not in message
    assert not contains_han(message)


def test_not_found_translates_known_resource_name() -> None:
    zh = localize_error_message(
        ErrorCode.NOT_FOUND, {"resource_name": "会话"}, SupportedLocale.ZH_CN
    )
    en = localize_error_message(
        ErrorCode.NOT_FOUND, {"resource_name": "会话"}, SupportedLocale.EN_US
    )

    assert contains_han(zh)
    assert not contains_han(en)
    assert "conversation" in en.lower()


def test_not_found_falls_back_for_unknown_resource_name() -> None:
    """未登记的资源名不能把原始中文字面量直接拼进英文句子。"""

    en = localize_error_message(
        ErrorCode.NOT_FOUND, {"resource_name": "未登记的新资源类型"}, SupportedLocale.EN_US
    )

    assert not contains_han(en)


def test_not_found_without_resource_name_param_still_renders() -> None:
    en = localize_error_message(ErrorCode.NOT_FOUND, {}, SupportedLocale.EN_US)

    assert "{resource_name}" not in en
    assert not contains_han(en)


def test_unknown_code_uses_generic_fallback_without_raising() -> None:
    zh = localize_error_message("SOME_UNDEFINED_CODE", {}, SupportedLocale.ZH_CN)
    en = localize_error_message("SOME_UNDEFINED_CODE", {}, SupportedLocale.EN_US)

    assert contains_han(zh)
    assert not contains_han(en)


def test_localize_error_message_accepts_none_params() -> None:
    message = localize_error_message(ErrorCode.RATE_LIMITED, None, SupportedLocale.EN_US)

    assert not contains_han(message)


def test_localize_validation_detail_message_known_type() -> None:
    zh = localize_validation_detail_message("missing", SupportedLocale.ZH_CN)
    en = localize_validation_detail_message("missing", SupportedLocale.EN_US)

    assert contains_han(zh)
    assert not contains_han(en)
    assert zh != en


def test_localize_validation_detail_message_unknown_type_falls_back() -> None:
    zh = localize_validation_detail_message("some_unheard_of_type", SupportedLocale.ZH_CN)
    en = localize_validation_detail_message("some_unheard_of_type", SupportedLocale.EN_US)

    assert contains_han(zh)
    assert not contains_han(en)
