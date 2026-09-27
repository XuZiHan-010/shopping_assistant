"""商品内容完整度规则（N3 阶段 C Task 3、Task 7，PRD D11③④）。

每个品类的必填属性清单**由后端配置**，不由模型判断——这是本模块存在的唯一理由。
Task 3（商品内容起草）用它判断哪些属性"待补"；Task 7（`CONTENT_GAP` 顾客信号）用同一份
清单判断顾客问到的属性是否计入信号，两处共享同一个事实源，不允许出现"起草说缺、
信号说不缺"这类分裂。

清单只登记 N3 演示数据实际用到的类目（`app/analytics/demo_data.py::_CATEGORIES`）；
未登记的类目没有必填属性，不臆造规则。

**`Product.attributes` 每个值都是 `{"value": str, ...}` 形状的 Mapping，不是裸字符串**
（与 `app/tools/customer/catalog.py::_attribute_values()`、`app/services/v2/catalog.py`
本地化服务读取同一字段时的假设一致，2026-09-26 统一）；值不是 Mapping 或没有字符串
`value` 的异常数据一律按"缺失"处理，不抛异常——数据形状本身不对不该拖垮判断逻辑。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

#: 类目 → 必填属性名集合。属性名与商家在起草对话中使用的中文名一致，
#: 不是内部字段标识——这些名字会原样出现在"待补"提示与顾客信号里。
REQUIRED_ATTRIBUTES_BY_CATEGORY: Final[dict[str, frozenset[str]]] = {
    "女装": frozenset({"产地", "材质", "尺码"}),
    "男装": frozenset({"产地", "材质", "尺码"}),
    "鞋靴": frozenset({"产地", "材质", "尺码"}),
    "家居": frozenset({"产地", "材质"}),
    "美妆": frozenset({"产地", "保质期"}),
}


@dataclass(frozen=True)
class ContentRule:
    min_description_length: int
    image_expected: bool


# 只配置本版演示类目；未配置的类目不推测商品内容要求。
CONTENT_RULES_BY_CATEGORY: Final[dict[str, ContentRule]] = {
    category: ContentRule(min_description_length=30, image_expected=True)
    for category in REQUIRED_ATTRIBUTES_BY_CATEGORY
}


def missing_content_fields(
    *, category: str, detail_description: str | None, image_url: str | None
) -> frozenset[str]:
    rule = CONTENT_RULES_BY_CATEGORY.get(category)
    if rule is None:
        return frozenset()
    missing = set[str]()
    if len((detail_description or "").strip()) < rule.min_description_length:
        missing.add("商品描述")
    if rule.image_expected and not (image_url or "").strip():
        missing.add("商品图片")
    return frozenset(missing)


def required_attributes_for(category: str) -> frozenset[str]:
    """该类目的必填属性清单；未登记的类目返回空集合（不臆造规则）。"""

    return REQUIRED_ATTRIBUTES_BY_CATEGORY.get(category, frozenset())


def _attribute_value(entry: Any) -> str | None:
    """从 Mapping 形状的属性条目里取出字符串值；形状不对时返回 `None`（视同缺失）。"""

    if not isinstance(entry, Mapping):
        return None
    value = entry.get("value")
    return value if isinstance(value, str) else None


def missing_required_attributes(
    *, category: str, attributes: dict[str, Any]
) -> frozenset[str]:
    """该类目必填、但在给定属性表里缺失或为空白的属性名。

    只判断必填清单内的属性——非必填属性缺失不计入结果（Task 7 据此决定信号是否计数）。
    空白值（纯空格）视同缺失，避免商家用一个空格"糊弄"过完整度校验。
    """

    required = required_attributes_for(category)
    return frozenset(
        name for name in required
        if not (_attribute_value(attributes.get(name)) or "").strip()
    )
