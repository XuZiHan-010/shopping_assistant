"""N3 阶段 C Task 3 / Task 7：商品内容完整度规则（`services/v2/content_completeness.py`）。

后端配置的必填属性清单是**事实源**，不由模型判断（D11③④）；Task 3 的起草工具与 Task 7 的
`CONTENT_GAP` 信号都读同一份规则，避免两处各自维护一套"这个类目必填什么"的判断标准。

**`Product.attributes` 的每个值都是 Mapping（`{"value": ..., ...}`），不是裸字符串**——
这与 `app/tools/customer/catalog.py::_attribute_values()`、
`app/services/v2/catalog.py`（本地化服务）读取同一个字段时的假设一致（2026-09-26 修正，
三处此前对这个字段的形状有过不一致假设，统一为 Mapping 是本次裁定）。
"""

from __future__ import annotations

from app.services.v2.content_completeness import (
    missing_content_fields,
    missing_required_attributes,
    required_attributes_for,
)


def test_missing_content_fields_uses_category_description_and_image_rules() -> None:
    assert missing_content_fields(
        category="女装", detail_description="简短说明。", image_url=None
    ) == frozenset({"商品描述", "商品图片"})
    assert missing_content_fields(
        category="女装", detail_description="完整的商品描述。" * 5,
        image_url="/demo/products/01.png",
    ) == frozenset()
    assert missing_content_fields(
        category="未配置类目", detail_description=None, image_url=None
    ) == frozenset()


def _attr(value: str) -> dict[str, str]:
    return {"value": value, "source": "MERCHANT"}


def test_required_attributes_are_defined_per_category() -> None:
    women = required_attributes_for("女装")
    assert "产地" in women
    assert "材质" in women


def test_unknown_category_has_no_required_attributes() -> None:
    """未登记的类目没有必填清单，不臆造规则——按 D11③④，事实源必须是后端配置。"""

    assert required_attributes_for("未知类目") == frozenset()


def test_missing_required_attributes_lists_only_absent_ones() -> None:
    missing = missing_required_attributes(
        category="女装", attributes={"产地": _attr("浙江")}
    )
    assert "产地" not in missing
    assert "材质" in missing


def test_missing_required_attributes_ignores_optional_attributes() -> None:
    """"包装颜色"不在女装必填清单里，缺失也不计入 missing（Task 7 用它判断是否计数）。"""

    missing = missing_required_attributes(category="女装", attributes={})
    assert "包装颜色" not in missing


def test_missing_required_attributes_treats_blank_value_as_missing() -> None:
    missing = missing_required_attributes(category="女装", attributes={"产地": _attr("  ")})
    assert "产地" in missing


def test_missing_required_attributes_treats_malformed_entry_as_missing() -> None:
    """值不是 Mapping（数据被绕过校验直接写入等异常情况）时按缺失处理，不抛异常。"""

    missing = missing_required_attributes(category="女装", attributes={"产地": "浙江"})
    assert "产地" in missing
