"""记忆写入前与最终落库值的隐私过滤。"""

from dataclasses import dataclass

import pytest

from app.memory.filters import filter_candidate, filter_persisted


@dataclass(frozen=True)
class CustomerFact:
    value: str
    key: str = "偏好"
    category: str = "购物"


@dataclass(frozen=True)
class MerchantFact:
    content: str
    category: str = "运营"


@pytest.mark.parametrize(
    "text",
    [
        "我电话 13800138000",
        "身份证 110101199001011234",
        "卡号 6222 0212 3456 7890",
        "寄到朝阳区XX路1号",
        "邮箱 a@b.com",
    ],
)
def test_candidate_rejects_personal_identifiers(text: str) -> None:
    assert filter_candidate(CustomerFact(text)).rejected


@pytest.mark.parametrize(
    "text",
    ["顾客可能有糖尿病", "顾客信仰佛教", "顾客支持某政党"],
)
def test_candidate_rejects_sensitive_inferences(text: str) -> None:
    assert filter_candidate(CustomerFact(text)).rejected


def test_candidate_scans_key_and_category_as_well_as_value() -> None:
    assert filter_candidate(CustomerFact("喜欢蓝色", key="邮箱 a@b.com")).rejected
    assert filter_candidate(CustomerFact("喜欢蓝色", category="宗教信仰")).rejected


def test_merchant_content_uses_same_filter() -> None:
    assert filter_candidate(MerchantFact("客户电话是 13800138000")).rejected
    assert not filter_candidate(MerchantFact("商家偏好周一补货")).rejected


def test_persisted_filter_catches_sensitive_value_created_by_merge() -> None:
    first = CustomerFact("送货前打 138")
    second = CustomerFact("00138000 这个号")
    assert not filter_candidate(first).rejected
    assert not filter_candidate(second).rejected

    merged = CustomerFact(first.value + second.value)
    assert filter_persisted(merged).rejected


def test_persisted_filter_rejects_normalized_card_number() -> None:
    assert filter_persisted(CustomerFact("6222021234567890")).rejected


def test_candidate_rejects_phone_with_grouping_spaces() -> None:
    assert filter_candidate(CustomerFact("联系 138 0013 8000")).rejected


def test_non_sensitive_preference_survives_both_filters() -> None:
    fact = CustomerFact("喜欢蓝色、宽松版型")
    assert not filter_candidate(fact).rejected
    assert not filter_persisted(fact).rejected
